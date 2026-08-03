"""Network-free tests for coordinator MQTT state ingestion."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import logging
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
FABRICATED_HUB_ID = "0123456789abcdef0123456789abcdef"


def _load_coordinator_module():
    package_name = "_grit_coordinator_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules[package_name] = package

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class DataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(
            self, hass, logger, *, name=None, update_interval=None
        ):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
            self.updated_data = []
            self.listener_updates = 0

        def async_set_updated_data(self, data):
            self.data = data
            self.updated_data.append(data)

        def async_update_listeners(self):
            self.listener_updates += 1

    class UpdateFailed(Exception):
        pass

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed
    homeassistant.helpers = helpers
    helpers.update_coordinator = update_coordinator
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules[
        "homeassistant.helpers.update_coordinator"
    ] = update_coordinator

    api_module = types.ModuleType(f"{package_name}.api")

    class GritHubApiClient:
        pass

    class GritHubApiError(Exception):
        pass

    api_module.GritHubApiClient = GritHubApiClient
    api_module.GritHubApiError = GritHubApiError
    sys.modules[api_module.__name__] = api_module

    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", COMPONENT_ROOT / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)

    coordinator_spec = importlib.util.spec_from_file_location(
        f"{package_name}.coordinator", COMPONENT_ROOT / "coordinator.py"
    )
    coordinator_module = importlib.util.module_from_spec(coordinator_spec)
    sys.modules[coordinator_spec.name] = coordinator_module
    coordinator_spec.loader.exec_module(coordinator_module)
    return coordinator_module


coordinator_module = _load_coordinator_module()


def _run_immediate(coroutine):
    """Run a fake-I/O coroutine that must complete without suspension."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise AssertionError("fake API coroutine unexpectedly suspended")


class FakeApi:
    """In-memory API replacement with no I/O capabilities."""

    def __init__(self, collections=None):
        self.collections = deepcopy(collections or {})
        self.health = {"status": "ok"}
        self.hub = {
            "id": FABRICATED_HUB_ID,
            "displayName": "Fabricated Hub",
            "hubVersion": "1.2.3-test",
        }
        self.hub_error = False
        self.hub_calls = 0
        self.collection_errors: set[str] = set()
        self.telemetry_calls: list[tuple[str, str]] = []
        self.telemetry_errors: set[tuple[str, str]] = set()
        self.telemetry_unexpected_errors: set[tuple[str, str]] = set()
        self.telemetry_entered: asyncio.Event | None = None
        self.telemetry_release: asyncio.Event | None = None
        self.telemetry_active = 0
        self.telemetry_max_active = 0
        self.telemetry_cancelled = 0

    async def health_check(self):
        return deepcopy(self.health)

    async def get_hub(self):
        self.hub_calls += 1
        if self.hub_error:
            raise coordinator_module.GritHubApiError(
                "fabricated hub request failure"
            )
        return deepcopy(self.hub)

    async def get_collection(self, device_type):
        if device_type in self.collection_errors:
            raise coordinator_module.GritHubApiError(
                "fabricated collection request failure"
            )
        return deepcopy(self.collections.get(device_type, []))

    async def request_device_telemetry(self, device_type, device_id):
        target = (device_type, str(device_id))
        self.telemetry_calls.append(target)
        self.telemetry_active += 1
        self.telemetry_max_active = max(
            self.telemetry_max_active,
            self.telemetry_active,
        )
        try:
            if self.telemetry_entered is not None:
                self.telemetry_entered.set()
            if target in self.telemetry_unexpected_errors:
                raise RuntimeError("fabricated unexpected telemetry failure")
            if self.telemetry_release is not None:
                await self.telemetry_release.wait()
            if target in self.telemetry_errors:
                raise coordinator_module.GritHubApiError(
                    "fabricated telemetry request failure"
                )
        except asyncio.CancelledError:
            self.telemetry_cancelled += 1
            raise
        finally:
            self.telemetry_active -= 1


def _device_map():
    devices = {
        device_type: [] for device_type in coordinator_module.DEVICE_TYPES
    }
    devices["gate"] = [{"id": "device-gate", "name": "Test gate"}]
    devices["solenoid"] = [{"id": "device-switch"}]
    devices["rfid"] = [{"id": "device-rfid"}]
    return devices


class CoordinatorMqttTests(unittest.TestCase):
    def setUp(self):
        connect_patch = mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_ex_patch = mock.patch.object(
            socket.socket,
            "connect_ex",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connection_patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_patch.start()
        connect_ex_patch.start()
        connection_patch.start()
        self.addCleanup(connect_patch.stop)
        self.addCleanup(connect_ex_patch.stop)
        self.addCleanup(connection_patch.stop)

    def coordinator(self, *, expected="hub-expected", devices=None, api=None):
        instance = coordinator_module.GritHubCoordinator(
            object(),
            api or FakeApi(),
            30,
            expected_mqtt_hub_id=expected,
        )
        instance.data = {
            "devices": deepcopy(devices or _device_map()),
            "hub": None,
            "health": None,
            "errors": {},
        }
        return instance

    def mqtt_state(self, instance, device_type="gate", index=0):
        return instance.data["devices"][device_type][index][
            coordinator_module.MQTT_STATE_KEY
        ]

    def send(
        self,
        instance,
        *,
        hub_id="hub-expected",
        device_type="gate",
        device_id="device-gate",
        message_type="status",
        payload=None,
    ):
        return instance.handle_mqtt_message(
            hub_id,
            device_type,
            device_id,
            message_type,
            {"online": True} if payload is None else payload,
        )

    def test_connection_state_notifies_only_on_changes(self):
        instance = self.coordinator()
        original_data = deepcopy(instance.data)

        self.assertFalse(instance.mqtt_connected)
        self.assertFalse(instance.set_mqtt_connected(False))
        self.assertTrue(instance.set_mqtt_connected(True))
        self.assertTrue(instance.mqtt_connected)
        self.assertFalse(instance.set_mqtt_connected(True))
        self.assertTrue(instance.set_mqtt_connected(False))
        self.assertFalse(instance.mqtt_connected)

        self.assertEqual(instance.listener_updates, 2)
        self.assertEqual(instance.data, original_data)
        self.assertEqual(instance.updated_data, [])

    def test_connection_state_requires_boolean(self):
        instance = self.coordinator()
        for value in (1, 0, None, "true"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                instance.set_mqtt_connected(value)
    def test_invalid_expected_hub_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            self.coordinator(expected=" ")

    def test_expected_hub_is_fail_closed(self):
        instance = self.coordinator(expected=None)
        self.assertFalse(self.send(instance))
        self.assertEqual(instance.updated_data, [])

    def test_matching_hub_routes_exact_device_once(self):
        instance = self.coordinator()
        self.assertTrue(self.send(instance))
        self.assertEqual(len(instance.updated_data), 1)
        self.assertTrue(self.mqtt_state(instance)["online"])

    def test_wrong_hub_is_rejected(self):
        instance = self.coordinator()
        self.assertFalse(self.send(instance, hub_id="other-hub"))
        self.assertEqual(instance.updated_data, [])

    def test_unknown_and_ambiguous_devices_are_rejected(self):
        instance = self.coordinator()
        self.assertFalse(self.send(instance, device_id="missing-device"))
        devices = _device_map()
        devices["gate"].append({"deviceId": "device-gate"})
        instance = self.coordinator(devices=devices)
        self.assertFalse(self.send(instance))
        self.assertEqual(instance.updated_data, [])

    def test_same_identifier_in_other_type_does_not_cross_route(self):
        devices = _device_map()
        devices["solenoid"] = [{"id": "device-gate"}]
        instance = self.coordinator(devices=devices)
        self.assertTrue(self.send(instance))
        self.assertNotIn(
            coordinator_module.MQTT_STATE_KEY,
            instance.data["devices"]["solenoid"][0],
        )

    def test_identifier_aliases_are_supported(self):
        aliases = (
            "id",
            "deviceId",
            "deviceID",
            "_id",
            "uuid",
            "key",
            "serialNumber",
            "serial",
            "deviceIdentifier",
        )
        for alias in aliases:
            with self.subTest(alias=alias):
                devices = _device_map()
                devices["gate"] = [{alias: "alias-device"}]
                instance = self.coordinator(devices=devices)
                self.assertTrue(
                    self.send(instance, device_id="alias-device")
                )

    def test_gate_position_and_open_derivation(self):
        cases = ((0, False), (65, False), (75, True), (100, True))
        for position, expected_open in cases:
            with self.subTest(position=position):
                instance = self.coordinator()
                self.assertTrue(
                    self.send(instance, payload={"p": position})
                )
                state = self.mqtt_state(instance)
                self.assertEqual(state["position"], position)
                self.assertIs(state["open"], expected_open)

    def test_gate_mid_position_preserves_previous_open_state(self):
        instance = self.coordinator()
        self.assertTrue(self.send(instance, payload={"open": True}))
        self.assertTrue(self.send(instance, payload={"position": 70}))
        state = self.mqtt_state(instance)
        self.assertEqual(state["position"], 70)
        self.assertTrue(state["open"])

    def test_invalid_gate_positions_are_rejected(self):
        values = (-1, 101, float("nan"), float("inf"), "50", 10**10000)
        for value in values:
            with self.subTest(value=type(value).__name__):
                instance = self.coordinator()
                self.assertFalse(
                    self.send(instance, payload={"position": value})
                )

    def test_strict_boolean_conversions(self):
        values = (
            (True, True),
            (False, False),
            (1, True),
            (0, False),
            ("true", True),
            ("false", False),
            ("on", True),
            ("off", False),
            ("open", True),
            ("closed", False),
            ("1", True),
            ("0", False),
        )
        for raw, expected in values:
            with self.subTest(raw=raw):
                instance = self.coordinator()
                self.assertTrue(
                    self.send(
                        instance,
                        device_type="solenoid",
                        device_id="device-switch",
                        message_type="s",
                        payload={"state": raw},
                    )
                )
                self.assertIs(
                    self.mqtt_state(instance, "solenoid")["state"], expected
                )

    def test_ambiguous_boolean_values_are_rejected(self):
        for raw in ("yes", "enabled", 2, -1, 0.0, None, [], {}):
            with self.subTest(raw=raw):
                instance = self.coordinator()
                self.assertFalse(
                    self.send(
                        instance,
                        device_type="solenoid",
                        device_id="device-switch",
                        message_type="s",
                        payload={"s": raw},
                    )
                )

    def test_rfid_status_hydrates_lock_and_diagnostic_state(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                device_type="rfid",
                device_id="device-rfid",
                message_type="sts",
                payload={
                    "s": 0,
                    "sts": 1,
                    "av": "1.1.test",
                    "rssi": -61,
                },
            )
        )
        state = self.mqtt_state(instance, "rfid")
        self.assertFalse(state["locked"])
        self.assertTrue(state["online"])
        self.assertEqual(state["firmware_version"], "1.1.test")
        self.assertEqual(state["rssi"], -61)

    def test_switch_message_aliases_are_bounded(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                device_type="solenoid",
                device_id="device-switch",
                message_type="gls/detail",
                payload={"state": "closed"},
            )
        )
        self.assertFalse(self.mqtt_state(instance, "solenoid")["state"])

    def test_rfid_authoritative_state_topics_apply_in_source_order(self):
        for message_type in ("s", "st"):
            with self.subTest(message_type=message_type):
                instance = self.coordinator()
                self.assertTrue(
                    self.send(
                        instance,
                        device_type="rfid",
                        device_id="device-rfid",
                        message_type=message_type,
                        payload={"state": True, "seq": 1},
                    )
                )
                self.assertFalse(self.mqtt_state(instance, "rfid")["locked"])
                self.assertTrue(
                    self.send(
                        instance,
                        device_type="rfid",
                        device_id="device-rfid",
                        message_type=message_type,
                        payload={"state": False, "seq": 2},
                    )
                )
                self.assertTrue(self.mqtt_state(instance, "rfid")["locked"])

    def test_rfid_status_one_is_locked_and_semantics_are_device_specific(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                device_type="rfid",
                device_id="device-rfid",
                message_type="sts",
                payload={"s": 1},
            )
        )
        self.assertTrue(self.mqtt_state(instance, "rfid")["locked"])

        self.assertFalse(
            self.send(
                instance,
                device_type="gate",
                device_id="device-gate",
                message_type="sts",
                payload={"s": 1},
            )
        )
        self.assertNotIn(
            coordinator_module.MQTT_STATE_KEY,
            instance.data["devices"]["gate"][0],
        )

    def test_rssi_range_is_enforced(self):
        instance = self.coordinator()
        self.assertTrue(self.send(instance, payload={"rssi": -62}))
        self.assertEqual(self.mqtt_state(instance)["rssi"], -62)
        for value in (-201, 1, "minus-60", float("nan")):
            with self.subTest(value=value):
                fresh = self.coordinator()
                self.assertFalse(
                    self.send(fresh, payload={"rssi": value})
                )

    def test_firmware_is_bounded_printable_text(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(instance, payload={"firmwareVersion": "v1.2.3"})
        )
        self.assertEqual(
            self.mqtt_state(instance)["firmware_version"], "v1.2.3"
        )
        for value in ("x" * 129, "bad\nvalue", 123):
            with self.subTest(value=type(value).__name__):
                fresh = self.coordinator()
                self.assertFalse(
                    self.send(fresh, payload={"version": value})
                )

    def test_unknown_and_nested_payload_data_is_ignored(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                payload={
                    "online": True,
                    "unknown": "do-not-keep",
                    "nested": {"secret": "do-not-keep"},
                },
            )
        )
        state = self.mqtt_state(instance)
        self.assertNotIn("unknown", state)
        self.assertNotIn("nested", state)
        self.assertFalse(
            self.send(self.coordinator(), payload={"unknown": True})
        )

    def test_reserved_state_schema_contains_no_routing_or_raw_data(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                message_type="status/detail",
                payload={
                    "position": 88,
                    "online": True,
                    "rssi": -50,
                    "version": "v2",
                    "raw_payload": "never-retain",
                },
            )
        )
        state = self.mqtt_state(instance)
        self.assertLessEqual(
            set(state),
            {
                "position",
                "open",
                "state",
                "online",
                "rssi",
                "firmware_version",

                "last_received_at",
                "source_sequence",
                "source_timestamp",
                "_ordering",
                coordinator_module._LOCAL_RECEIVE_SEQUENCE_KEY,
                coordinator_module._FIELD_OBSERVATIONS_KEY,
            },
        )
        serialized = repr(state)
        for forbidden in (
            "raw_payload",
            "hub-expected",
            "device-gate",
            "grit/",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_repeated_unordered_value_is_a_fresh_observation(self):
        instance = self.coordinator()
        self.assertTrue(self.send(instance, payload={"online": True}))
        first_sequence = instance.mqtt_receive_sequence
        self.assertTrue(self.send(instance, payload={"online": True}))
        state = self.mqtt_state(instance)
        self.assertEqual(len(instance.updated_data), 2)
        self.assertGreater(instance.mqtt_receive_sequence, first_sequence)
        self.assertEqual(
            state[coordinator_module._FIELD_OBSERVATIONS_KEY]["online"],
            instance.mqtt_receive_sequence,
        )

    def test_receive_timestamp_is_aware_utc(self):
        before = datetime.now(timezone.utc)
        instance = self.coordinator()
        self.assertTrue(self.send(instance))
        received = self.mqtt_state(instance)["last_received_at"]
        after = datetime.now(timezone.utc)
        self.assertEqual(received.tzinfo, timezone.utc)
        self.assertLessEqual(before, received)
        self.assertLessEqual(received, after)

    def test_source_sequence_rejects_equal_and_older_updates(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(instance, payload={"online": False, "seq": 10})
        )
        self.assertFalse(
            self.send(instance, payload={"online": True, "seq": 10})
        )
        self.assertFalse(
            self.send(instance, payload={"online": True, "seq": 9})
        )
        self.assertTrue(
            self.send(instance, payload={"online": True, "seq": 11})
        )
        self.assertTrue(self.mqtt_state(instance)["online"])

    def test_source_timestamp_rejects_stale_updates(self):
        instance = self.coordinator()
        newer = "2026-08-02T10:00:00+00:00"
        older = "2026-08-02T09:59:59+00:00"
        self.assertTrue(
            self.send(
                instance,
                payload={"rssi": -70, "source_timestamp": newer},
            )
        )
        self.assertFalse(
            self.send(
                instance,
                payload={"rssi": -60, "source_timestamp": older},
            )
        )
        self.assertEqual(self.mqtt_state(instance)["rssi"], -70)

    def test_newer_metadata_with_same_value_is_not_a_duplicate(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(instance, payload={"online": True, "seq": 1})
        )
        self.assertTrue(
            self.send(instance, payload={"online": True, "seq": 2})
        )
        self.assertEqual(len(instance.updated_data), 2)
        self.assertEqual(self.mqtt_state(instance)["source_sequence"], 2)

    def test_incomparable_update_is_rejected_after_ordered_state(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(instance, payload={"online": False, "seq": 5})
        )
        self.assertFalse(self.send(instance, payload={"online": True}))
        state = self.mqtt_state(instance)
        self.assertFalse(state["online"])
        self.assertEqual(state["source_sequence"], 5)
        self.assertEqual(
            state["_ordering"]["online"]["source_sequence"],
            5,
        )

    def test_ordering_is_scoped_by_state_category(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                device_type="solenoid",
                device_id="device-switch",
                payload={"rssi": -80, "seq": 10},
            )
        )
        self.assertTrue(
            self.send(
                instance,
                device_type="solenoid",
                device_id="device-switch",
                message_type="s",
                payload={"state": True, "seq": 2},
            )
        )

    def test_state_schema_does_not_grow_history(self):
        instance = self.coordinator()
        for sequence in range(1, 51):
            self.assertTrue(
                self.send(
                    instance,
                    payload={"rssi": -50 - (sequence % 20), "seq": sequence},
                )
            )
        state = self.mqtt_state(instance)
        self.assertLessEqual(len(state), 6)
        self.assertNotIn("history", state)
        self.assertNotIn("messages", state)

    def test_invalid_ordering_metadata_rejects_entire_message(self):
        values = (-1, 2**63, True, "not-a-number", 1.5)
        for value in values:
            with self.subTest(value=value):
                instance = self.coordinator()
                self.assertFalse(
                    self.send(
                        instance,
                        payload={"online": True, "seq": value},
                    )
                )
        instance = self.coordinator()
        self.assertFalse(
            self.send(
                instance,
                payload={
                    "online": True,
                    "source_timestamp": "2026-08-02T10:00:00",
                },
            )
        )

    def test_rest_refresh_preserves_non_reconciled_same_type_state(self):
        instance = self.coordinator(
            api=FakeApi({"solenoid": [{"deviceId": "device-switch"}]})
        )
        self.assertTrue(
            self.send(
                instance,
                device_type="solenoid",
                device_id="device-switch",
                message_type="s",
                payload={"state": True},
            )
        )
        refreshed = _run_immediate(instance._async_update_data())
        state = refreshed["devices"]["solenoid"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertTrue(state["state"])

    def test_hub_data_and_identity_use_last_sanitized_values(self):
        instance = self.coordinator()
        instance.data["hub"] = deepcopy(instance.api.hub)
        self.assertEqual(instance.hub_data, instance.api.hub)
        self.assertEqual(instance.hub_id, FABRICATED_HUB_ID)

        instance.data["hub"] = None
        self.assertEqual(instance.hub_data, {})
        self.assertEqual(instance.hub_id, "hub-expected")

    def test_hub_failure_preserves_last_values(self):
        api = FakeApi()
        api.hub_error = True
        instance = self.coordinator(api=api)
        previous_hub = deepcopy(api.hub)
        instance.data["hub"] = previous_hub

        refreshed = _run_immediate(instance._async_update_data())

        self.assertEqual(refreshed["hub"], previous_hub)
        self.assertIn("hub", refreshed["errors"])

    def test_raw_health_response_is_not_retained(self):
        api = FakeApi()
        marker = "fabricated-private-health-payload"
        api.health = {"status": "ok", "diagnostics": {"marker": marker}}
        instance = self.coordinator(api=api)

        refreshed = _run_immediate(instance._async_update_data())

        self.assertEqual(refreshed["health"], {"reachable": True})
        self.assertNotIn(marker, repr(refreshed))

    def test_refresh_generations_require_successful_relevant_responses(self):
        api = FakeApi(
            {
                "trigger": [
                    {
                        "id": "trigger-fabricated",
                        "gritLockEnabled": True,
                        "gritLockState": True,
                    }
                ]
            }
        )
        instance = self.coordinator(api=api)
        self.assertEqual(instance.refresh_sequence, 0)
        self.assertEqual(instance.hub_update_sequence, 0)
        self.assertEqual(instance.gritlock_update_sequence, 0)

        first = _run_immediate(instance._async_update_data())
        instance.data = first

        self.assertEqual(instance.refresh_sequence, 1)
        self.assertEqual(instance.hub_update_sequence, 1)
        self.assertEqual(instance.gritlock_update_sequence, 1)
        self.assertEqual(api.hub_calls, 1)

        api.hub_error = True
        api.collection_errors.add("trigger")
        second = _run_immediate(instance._async_update_data())

        self.assertEqual(instance.refresh_sequence, 2)
        self.assertEqual(instance.hub_update_sequence, 1)
        self.assertEqual(instance.gritlock_update_sequence, 1)
        self.assertEqual(api.hub_calls, 2)
        self.assertEqual(second["hub"], first["hub"])
        self.assertIn("hub", second["errors"])
        self.assertIn("trigger", second["errors"])

    def test_gritlock_state_requires_unanimous_participating_triggers(self):
        cases = (
            ([], None),
            ([{"gritLockEnabled": False}], None),
            (
                [
                    {"gritLockEnabled": True, "gritLockState": True},
                    {"gritLockEnabled": True, "gritLockState": True},
                ],
                True,
            ),
            (
                [
                    {"gritLockEnabled": True, "gritLockState": False},
                    {"gritLockEnabled": True, "gritLockState": False},
                ],
                False,
            ),
            (
                [
                    {"gritLockEnabled": True, "gritLockState": True},
                    {"gritLockEnabled": True, "gritLockState": False},
                ],
                None,
            ),
            ([{"gritLockEnabled": True}], None),
            (
                [
                    {
                        "gritLockEnabled": False,
                        "gritLockState": False,
                    },
                    {
                        "gritLockEnabled": True,
                        "gritLockState": True,
                    },
                ],
                True,
            ),
        )
        for triggers, expected in cases:
            with self.subTest(triggers=triggers):
                devices = _device_map()
                devices["trigger"] = triggers
                instance = self.coordinator(devices=devices)
                self.assertIs(instance.gritlock_state, expected)

    def test_gritlock_mqtt_consensus_uses_only_exact_participating_gl(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": "trigger-one"},
            {"id": "trigger-two"},
        ]
        instance = self.coordinator(devices=devices)

        self.assertTrue(
            self.send(
                instance,
                device_type="trigger",
                device_id="trigger-one",
                message_type="gl",
                payload={"gte": 1, "gls": 1},
            )
        )
        self.assertTrue(
            self.send(
                instance,
                device_type="trigger",
                device_id="trigger-two",
                message_type="gl",
                payload={"gte": 0, "gls": 0},
            )
        )
        generation = instance._gritlock_active_generation
        self.assertIsNotNone(generation)
        self.assertTrue(
            instance._settle_gritlock_generation(
                generation.generation_id,
                force=True,
            )
        )
        self.assertTrue(instance.gritlock_state)
        self.assertEqual(
            instance.gritlock_participating_trigger_ids,
            frozenset({"trigger-one"}),
        )

        self.assertFalse(
            self.send(
                instance,
                device_type="trigger",
                device_id="trigger-two",
                message_type="gl-d",
                payload={"gte": 1, "gls": 0},
            )
        )
        self.assertIsNone(instance._gritlock_active_generation)
        self.assertTrue(instance.gritlock_state)

        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                self.send(
                    instance,
                    device_type="trigger",
                    device_id=trigger_id,
                    message_type="gl",
                    payload={"gte": 1, "gls": 0},
                )
            )
        generation = instance._gritlock_active_generation
        self.assertIsNotNone(generation)
        self.assertTrue(
            instance._settle_gritlock_generation(
                generation.generation_id,
                force=True,
            )
        )
        self.assertFalse(instance.gritlock_state)

    def test_gritlock_malformed_fields_are_rejected(self):
        values = (
            {"gte": "1", "gls": 1},
            {"gte": 1, "gls": "0"},
            {"gte": 2, "gls": 1},
            {"gte": 1, "gls": -1},
            {"gte": True},
            {"gls": False},
        )
        for payload in values:
            with self.subTest(payload=payload):
                devices = _device_map()
                devices["trigger"] = [{"id": "trigger-one"}]
                instance = self.coordinator(devices=devices)
                self.assertFalse(
                    self.send(
                        instance,
                        device_type="trigger",
                        device_id="trigger-one",
                        message_type="gl",
                        payload=payload,
                    )
                )
                self.assertIsNone(instance.gritlock_state)
                self.assertIsNone(instance._gritlock_active_generation)

    def test_gritlock_rejection_log_is_generic(self):
        devices = _device_map()
        devices["trigger"] = [{"id": "trigger-private-test"}]
        instance = self.coordinator(devices=devices)
        payload_marker = "fabricated-private-gritlock-value"

        with self.assertLogs(
            coordinator_module._LOGGER.name,
            level=logging.DEBUG,
        ) as captured:
            self.assertFalse(
                self.send(
                    instance,
                    device_type="trigger",
                    device_id="trigger-private-test",
                    message_type="gl",
                    payload={"gte": payload_marker, "gls": 1},
                )
            )

        combined = "\n".join(captured.output)
        self.assertIn("message rejected", combined)
        for sensitive in (
            "hub-expected",
            "trigger-private-test",
            payload_marker,
        ):
            self.assertNotIn(sensitive, combined)


    def test_gritlock_observation_memory_is_bounded(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": f"trigger-{index}"}
            for index in range(
                coordinator_module._MAX_GRITLOCK_OBSERVATIONS + 1
            )
        ]
        instance = self.coordinator(devices=devices)

        for index in range(coordinator_module._MAX_GRITLOCK_OBSERVATIONS):
            self.assertTrue(
                self.send(
                    instance,
                    device_type="trigger",
                    device_id=f"trigger-{index}",
                    message_type="gl",
                    payload={"gte": 1, "gls": 1},
                )
            )
        self.assertFalse(
            self.send(
                instance,
                device_type="trigger",
                device_id=(
                    f"trigger-{coordinator_module._MAX_GRITLOCK_OBSERVATIONS}"
                ),
                message_type="gl",
                payload={"gte": 1, "gls": 1},
            )
        )
        self.assertEqual(
            len(instance._gritlock_active_generation.observations),
            coordinator_module._MAX_GRITLOCK_OBSERVATIONS,
        )


    def test_gritlock_generation_results_are_bounded(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True}
        ]
        instance = self.coordinator(devices=devices)
        instance.set_mqtt_connected(True)

        for index in range(
            coordinator_module._MAX_GRITLOCK_GENERATION_RESULTS + 3
        ):
            self.assertTrue(
                self.send(
                    instance,
                    device_type="trigger",
                    device_id="trigger-one",
                    message_type="gl",
                    payload={"gte": 1, "gls": index % 2},
                )
            )
            generation = instance._gritlock_active_generation
            self.assertTrue(
                instance._settle_gritlock_generation(
                    generation.generation_id,
                    force=True,
                )
            )

        self.assertLessEqual(
            len(instance._gritlock_generation_results),
            coordinator_module._MAX_GRITLOCK_GENERATION_RESULTS,
        )
        self.assertIsNone(instance._gritlock_active_generation)

    def test_gritlock_mqtt_evidence_supersedes_rest_only_after_settle(self):
        devices = _device_map()
        devices["trigger"] = [
            {
                "id": "trigger-one",
                "gritLockEnabled": True,
                "gritLockState": False,
            }
        ]
        instance = self.coordinator(devices=devices)
        self.assertFalse(instance.gritlock_state)

        self.assertTrue(
            self.send(
                instance,
                device_type="trigger",
                device_id="trigger-one",
                message_type="gl",
                payload={"gte": True, "gls": True},
            )
        )
        self.assertFalse(instance.gritlock_state)
        generation = instance._gritlock_active_generation
        self.assertIsNotNone(generation)
        self.assertTrue(
            instance._settle_gritlock_generation(
                generation.generation_id,
                force=True,
            )
        )
        self.assertTrue(instance.gritlock_state)
        listener_updates = instance.listener_updates

        instance.set_mqtt_connected(True)
        instance.set_mqtt_connected(False)
        self.assertFalse(instance.gritlock_state)
        self.assertGreaterEqual(instance.listener_updates, listener_updates)

    def test_rest_refresh_re_sanitizes_preserved_state(self):
        devices = _device_map()
        devices["gate"][0][coordinator_module.MQTT_STATE_KEY] = {
            "position": 25,
            "last_message_type": "position",
            "last_received_at": datetime.now(timezone.utc),
            "raw_payload": {"private": "never-retain"},
            "unexpected": "never-retain",
            "_ordering": {"unbounded-category": {"source_sequence": 3}},
        }
        instance = self.coordinator(
            devices=devices,
            api=FakeApi({"gate": [{"id": "device-gate"}]}),
        )
        refreshed = _run_immediate(instance._async_update_data())
        state = refreshed["devices"]["gate"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertEqual(state["position"], 25)
        self.assertNotIn("last_message_type", state)
        self.assertNotIn("raw_payload", state)
        self.assertNotIn("unexpected", state)
        self.assertNotIn("_ordering", state)

    def test_rest_refresh_retains_order_marker_and_rejects_stale_mqtt(self):
        api = FakeApi(
            {"gate": [{"id": "device-gate", "open": True, "position": 100}]}
        )
        instance = self.coordinator(api=api)
        self.assertTrue(
            self.send(instance, payload={"position": 20, "open": False, "seq": 10})
        )

        refreshed = _run_immediate(instance._async_update_data())
        instance.data = refreshed
        state = self.mqtt_state(instance)
        self.assertEqual(state["position"], 20)
        self.assertFalse(state["open"])
        self.assertEqual(state["_ordering"]["gate"]["source_sequence"], 10)
        self.assertFalse(
            self.send(instance, payload={"position": 10, "open": False, "seq": 9})
        )
        self.assertFalse(self.mqtt_state(instance)["open"])
        self.assertEqual(self.mqtt_state(instance)["position"], 20)
        self.assertTrue(
            self.send(instance, payload={"position": 90, "open": True, "seq": 11})
        )
        self.assertEqual(self.mqtt_state(instance)["position"], 90)

    def test_rest_refresh_never_transfers_across_device_type(self):
        instance = self.coordinator(
            api=FakeApi({"solenoid": [{"id": "device-gate"}]})
        )
        self.assertTrue(self.send(instance, payload={"online": True}))
        refreshed = _run_immediate(instance._async_update_data())
        self.assertNotIn(
            coordinator_module.MQTT_STATE_KEY,
            refreshed["devices"]["solenoid"][0],
        )

    def test_rest_refresh_skips_ambiguous_identity(self):
        devices = _device_map()
        devices["gate"].append(
            {
                "deviceId": "device-gate",
                coordinator_module.MQTT_STATE_KEY: {"online": False},
            }
        )
        devices["gate"][0][coordinator_module.MQTT_STATE_KEY] = {
            "online": True
        }
        instance = self.coordinator(
            devices=devices,
            api=FakeApi({"gate": [{"id": "device-gate"}]}),
        )
        refreshed = _run_immediate(instance._async_update_data())
        self.assertNotIn(
            coordinator_module.MQTT_STATE_KEY,
            refreshed["devices"]["gate"][0],
        )

    def test_rest_refresh_drops_removed_device_state(self):
        instance = self.coordinator(api=FakeApi({"gate": []}))
        self.assertTrue(self.send(instance, payload={"online": True}))
        refreshed = _run_immediate(instance._async_update_data())
        self.assertEqual(refreshed["devices"]["gate"], [])
        self.assertNotIn("mqtt", refreshed)

    def test_additional_message_type_components_are_accepted_not_retained(self):
        instance = self.coordinator()
        private_suffix = "diagnostic/person-specific-value"
        self.assertTrue(
            self.send(
                instance,
                message_type=f"status/{private_suffix}",
                payload={"online": True},
            )
        )
        state = self.mqtt_state(instance)
        self.assertTrue(state["online"])
        self.assertNotIn("last_message_type", state)
        self.assertNotIn(private_suffix, repr(state))

    def test_rejection_logs_do_not_disclose_message_details(self):
        instance = self.coordinator()
        broker = "broker-private.example"
        username = "fabricated-user"
        password = "fabricated-password"
        complete_topic = "grit/private-hub/gate/private-device/status"
        hub_id = "hub-expected"
        device_id = "device-gate"
        payload_value = "fabricated-payload-secret"
        with self.assertLogs(
            coordinator_module._LOGGER.name, level=logging.DEBUG
        ) as captured:
            instance.handle_mqtt_message(
                hub_id,
                "gate",
                device_id,
                complete_topic,
                {
                    "unknown": payload_value,
                    "broker": broker,
                    "username": username,
                    "password": password,
                },
            )
        combined = "\n".join(captured.output)
        for sensitive in (
            broker,
            username,
            password,
            complete_topic,
            hub_id,
            device_id,
            payload_value,
        ):
            self.assertNotIn(sensitive, combined)
        self.assertIn("message rejected", combined)


class CoordinatorReconciliationTests(unittest.IsolatedAsyncioTestCase):
    """Exercise reconciliation with fake REST/MQTT inputs only."""

    def setUp(self):
        connect_patch = mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_ex_patch = mock.patch.object(
            socket.socket,
            "connect_ex",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connection_patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_patch.start()
        connect_ex_patch.start()
        connection_patch.start()
        self.addCleanup(connect_patch.stop)
        self.addCleanup(connect_ex_patch.stop)
        self.addCleanup(connection_patch.stop)

    def coordinator(self, api, devices=None):
        instance = coordinator_module.GritHubCoordinator(
            object(),
            api,
            30,
            expected_mqtt_hub_id="hub-expected",
        )
        instance.data = {
            "devices": deepcopy(devices or _device_map()),
            "hub": None,
            "health": None,
            "errors": {},
        }
        return instance

    async def wait_until_idle(self, instance):
        async def wait_loop():
            await asyncio.sleep(0)
            for _attempt in range(100):
                if instance._reconciliation_task is None:
                    return
                await asyncio.sleep(0)
            self.fail("reconciliation did not become idle")

        await asyncio.wait_for(wait_loop(), timeout=1)

    async def test_startup_rest_does_not_invent_live_gate_or_rfid_state(self):
        api = FakeApi(
            {
                "gate": [
                    {
                        "id": "device-gate",
                        "gateClosed": 50,
                        "gateOpen": 70,
                    }
                ],
                "rfid": [
                    {
                        "id": "device-rfid",
                        "lockout": False,
                        "onlineStatus": True,
                    }
                ],
            }
        )
        instance = self.coordinator(api)

        refreshed = await instance._async_update_data()

        self.assertNotIn(coordinator_module.MQTT_STATE_KEY, refreshed["devices"]["gate"][0])
        self.assertNotIn(coordinator_module.MQTT_STATE_KEY, refreshed["devices"]["rfid"][0])
        self.assertEqual(api.telemetry_calls, [])

    async def test_repeated_rest_refresh_preserves_live_mqtt_state(self):
        api = FakeApi(
            {
                "gate": [
                    {
                        "id": "device-gate",
                        "position": 10,
                        "open": False,
                    }
                ],
                "rfid": [{"id": "device-rfid", "state": False}],
            }
        )
        instance = self.coordinator(api)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"position": 90, "open": True, "seq": 4},
            )
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "s",
                {"state": True, "seq": 4},
            )
        )

        for _ in range(2):
            refreshed = await instance._async_update_data()
            instance.data = refreshed
        gate = refreshed["devices"]["gate"][0]
        rfid = refreshed["devices"]["rfid"][0]

        self.assertEqual(gate["position"], 10)
        self.assertFalse(gate["open"])
        self.assertFalse(rfid["state"])
        gate_state = gate[coordinator_module.MQTT_STATE_KEY]
        rfid_state = rfid[coordinator_module.MQTT_STATE_KEY]
        self.assertEqual(gate_state["position"], 90)
        self.assertTrue(gate_state["open"])
        self.assertFalse(rfid_state["locked"])
        self.assertEqual(
            gate_state["_ordering"]["gate"]["source_sequence"],
            4,
        )
        self.assertEqual(
            rfid_state["_ordering"]["state"]["source_sequence"],
            4,
        )

    async def test_missing_and_failed_rest_refresh_preserve_mqtt_state(self):
        api = FakeApi(
            {
                "gate": [{"id": "device-gate", "name": "Test gate"}],
                "rfid": [{"id": "device-rfid", "state": False}],
            }
        )
        instance = self.coordinator(api)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"position": 90, "open": True},
            )
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True},
            )
        )

        refreshed = await instance._async_update_data()
        instance.data = refreshed
        api.collection_errors.update({"gate", "rfid"})
        failed_refresh = await instance._async_update_data()

        gate_state = failed_refresh["devices"]["gate"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        rfid_state = failed_refresh["devices"]["rfid"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertEqual(gate_state["position"], 90)
        self.assertTrue(gate_state["open"])
        self.assertFalse(rfid_state["locked"])
        self.assertIn("gate", failed_refresh["errors"])
        self.assertIn("rfid", failed_refresh["errors"])

    async def test_successful_rest_omission_preserves_mqtt_devices(self):
        api = FakeApi({"gate": [], "rfid": []})
        instance = self.coordinator(api)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"position": 90, "open": True},
            )
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True},
            )
        )

        refreshed = await instance._async_update_data()

        self.assertEqual(len(refreshed["devices"]["gate"]), 1)
        self.assertEqual(len(refreshed["devices"]["rfid"]), 1)
        gate = refreshed["devices"]["gate"][0]
        rfid = refreshed["devices"]["rfid"][0]
        self.assertEqual(
            set(gate),
            {"id", coordinator_module.MQTT_STATE_KEY},
        )
        self.assertEqual(
            set(rfid),
            {"id", coordinator_module.MQTT_STATE_KEY},
        )
        self.assertTrue(gate[coordinator_module.MQTT_STATE_KEY]["open"])
        self.assertEqual(
            gate[coordinator_module.MQTT_STATE_KEY]["position"],
            90,
        )
        self.assertFalse(rfid[coordinator_module.MQTT_STATE_KEY]["locked"])

    async def test_targeted_reconciliation_preserves_last_mqtt_state(self):
        api = FakeApi()
        instance = self.coordinator(api)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"position": 85, "open": True},
            )
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True},
            )
        )
        instance.set_mqtt_connected(True)

        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)

        self.assertEqual(
            api.telemetry_calls,
            [("gate", "device-gate"), ("rfid", "device-rfid")],
        )
        gate_state = instance.data["devices"]["gate"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        rfid_state = instance.data["devices"]["rfid"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertEqual(gate_state["position"], 85)
        self.assertTrue(gate_state["open"])
        self.assertFalse(rfid_state["locked"])

    async def test_targeted_rfid_status_only_hydrates_and_confirms_state(self):
        api = FakeApi()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "rfid",
                "device-rfid",
                False,
                after_sequence=instance.mqtt_receive_sequence,
                timeout=0.2,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(api.telemetry_calls, [("rfid", "device-rfid")])
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "sts",
                {"s": 0, "sts": 1, "av": "test-version", "rssi": -60},
            )
        )

        self.assertTrue(await asyncio.wait_for(confirmation, timeout=1))
        state = instance.data["devices"]["rfid"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertFalse(state["locked"])
        self.assertTrue(state["online"])

    async def test_command_confirmation_rejects_stale_then_accepts_fresh_mqtt(self):
        api = FakeApi()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"open": True, "seq": 5},
            )
        )
        boundary = instance.mqtt_receive_sequence

        stale_confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "gate",
                "device-gate",
                True,
                after_sequence=boundary,
                timeout=0.02,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertFalse(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"open": True, "seq": 5},
            )
        )
        self.assertFalse(await stale_confirmation)

        boundary = instance.mqtt_receive_sequence
        fresh_confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "gate",
                "device-gate",
                True,
                after_sequence=boundary,
                timeout=0.1,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"open": True, "seq": 6},
            )
        )
        self.assertTrue(await asyncio.wait_for(fresh_confirmation, timeout=1))
        self.assertEqual(
            api.telemetry_calls,
            [("gate", "device-gate"), ("gate", "device-gate")],
        )

    async def test_duplicate_command_telemetry_requests_are_coalesced(self):
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        boundary = instance.mqtt_receive_sequence

        confirmations = [
            asyncio.create_task(
                instance.async_confirm_device_state(
                    "rfid",
                    "device-rfid",
                    True,
                    after_sequence=boundary,
                    timeout=0.2,
                )
            )
            for _ in range(2)
        ]
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertEqual(api.telemetry_calls, [("rfid", "device-rfid")])

        api.telemetry_release.set()
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": False},
            )
        )
        self.assertEqual(
            await asyncio.wait_for(asyncio.gather(*confirmations), timeout=1),
            [True, True],
        )
        self.assertEqual(api.telemetry_calls, [("rfid", "device-rfid")])

    async def test_one_waiter_timeout_does_not_cancel_shared_telemetry(self):
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        boundary = instance.mqtt_receive_sequence
        short = asyncio.create_task(
            instance.async_confirm_device_state(
                "gate",
                "device-gate",
                True,
                after_sequence=boundary,
                timeout=0.01,
            )
        )
        long = asyncio.create_task(
            instance.async_confirm_device_state(
                "gate",
                "device-gate",
                True,
                after_sequence=boundary,
                timeout=0.2,
            )
        )
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)
        self.assertFalse(await asyncio.wait_for(short, timeout=1))
        self.assertEqual(api.telemetry_calls, [("gate", "device-gate")])
        self.assertEqual(api.telemetry_active, 1)

        api.telemetry_release.set()
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "st",
                {"state": True},
            )
        )
        self.assertTrue(await asyncio.wait_for(long, timeout=1))
        await asyncio.sleep(0)
        self.assertEqual(api.telemetry_active, 0)
        self.assertEqual(instance._telemetry_request_tasks, {})

    async def test_disconnect_ends_command_confirmation_without_clearing_state(self):
        api = FakeApi()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True},
            )
        )
        boundary = instance.mqtt_receive_sequence
        confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "rfid",
                "device-rfid",
                False,
                after_sequence=boundary,
                timeout=0.2,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertTrue(instance.set_mqtt_connected(False))

        self.assertFalse(await asyncio.wait_for(confirmation, timeout=1))
        self.assertFalse(
            instance.data["devices"]["rfid"][0][
                coordinator_module.MQTT_STATE_KEY
            ]["locked"]
        )
        self.assertEqual(instance._mqtt_state_waiters, set())

    async def test_disconnect_reconnect_invalidates_blocked_confirmation(self):
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        boundary = instance.mqtt_receive_sequence
        confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "gate",
                "device-gate",
                True,
                after_sequence=boundary,
                timeout=0.2,
            )
        )
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)

        self.assertTrue(instance.set_mqtt_connected(False))
        self.assertTrue(instance.set_mqtt_connected(True))
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "st",
                {"state": True},
            )
        )
        api.telemetry_release.set()

        self.assertFalse(await asyncio.wait_for(confirmation, timeout=1))
        self.assertEqual(api.telemetry_active, 0)
        self.assertEqual(instance._mqtt_state_waiters, set())

    async def test_stop_cancels_command_telemetry_without_background_work(self):
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)
        confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "gate",
                "device-gate",
                True,
                after_sequence=instance.mqtt_receive_sequence,
                timeout=0.2,
            )
        )
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)

        await asyncio.wait_for(
            instance.async_stop_state_reconciliation(),
            timeout=1,
        )
        confirmation_result = await asyncio.gather(
            confirmation,
            return_exceptions=True,
        )

        self.assertIsInstance(
            confirmation_result[0],
            asyncio.CancelledError,
        )
        self.assertEqual(api.telemetry_cancelled, 1)
        self.assertEqual(api.telemetry_active, 0)
        self.assertEqual(instance._telemetry_request_tasks, {})
        self.assertEqual(instance._mqtt_state_waiters, set())

    async def test_mqtt_received_during_rest_refresh_wins(self):
        class BlockingApi(FakeApi):
            def __init__(self):
                super().__init__(
                    {
                        "gate": [
                            {
                                "id": "device-gate",
                                "position": 20,
                                "open": False,
                            }
                        ],
                        "rfid": [{"id": "device-rfid", "state": False}],
                    }
                )
                self.refresh_entered = asyncio.Event()
                self.refresh_release = asyncio.Event()

            async def get_collection(self, device_type):
                if device_type == "rfid":
                    self.refresh_entered.set()
                    await self.refresh_release.wait()
                return await super().get_collection(device_type)

        api = BlockingApi()
        instance = self.coordinator(api)
        refresh_task = asyncio.create_task(instance._async_update_data())
        await asyncio.wait_for(api.refresh_entered.wait(), timeout=1)

        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "s",
                {"position": 92, "open": True, "seq": 8},
            )
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True, "seq": 8},
            )
        )
        instance.data["devices"]["gate"][0][
            coordinator_module.MQTT_STATE_KEY
        ]["last_received_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc)
        instance.data["devices"]["rfid"][0][
            coordinator_module.MQTT_STATE_KEY
        ]["last_received_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc)
        api.refresh_release.set()
        refreshed = await asyncio.wait_for(refresh_task, timeout=1)

        state = refreshed["devices"]["gate"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertEqual(state["position"], 92)
        self.assertTrue(state["open"])
        self.assertEqual(state["source_sequence"], 8)
        rfid_state = refreshed["devices"]["rfid"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertFalse(rfid_state["locked"])
        self.assertEqual(rfid_state["source_sequence"], 8)

    async def test_reconciliation_targets_only_unique_documented_ids(self):
        devices = _device_map()
        devices["gate"] = [
            {"id": "gate-one"},
            {"deviceId": "alias-is-not-documented-for-this-route"},
            {"id": "duplicate"},
            {"id": "duplicate"},
            {"id": "same-id", "deviceId": "ignored-alias"},
            {"id": "conflict-one", "deviceId": "conflict-two"},
            {"serialNumber": "serial-is-not-a-mesh-id"},
        ]
        devices["rfid"] = [{"id": "rfid-one"}]
        devices["solenoid"] = [{"id": "solenoid-one"}]
        api = FakeApi()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)

        self.assertEqual(
            api.telemetry_calls,
            [
                ("gate", "gate-one"),
                ("gate", "same-id"),
                ("gate", "conflict-one"),
                ("rfid", "rfid-one"),
            ],
        )

    async def test_reconciliation_enforces_concurrency_bound(self):
        devices = _device_map()
        devices["gate"] = [
            {"id": f"gate-{index}"} for index in range(6)
        ]
        devices["rfid"] = []
        api = FakeApi()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        self.assertTrue(instance.start_state_reconciliation())

        async def wait_for_four_started():
            for _attempt in range(100):
                if len(api.telemetry_calls) == 4:
                    return
                await asyncio.sleep(0)
            self.fail("four telemetry requests did not start")

        await asyncio.wait_for(wait_for_four_started(), timeout=1)
        self.assertEqual(api.telemetry_max_active, 4)
        self.assertEqual(len(api.telemetry_calls), 4)

        api.telemetry_release.set()
        await self.wait_until_idle(instance)
        self.assertEqual(len(api.telemetry_calls), 6)
        self.assertEqual(api.telemetry_max_active, 4)
        self.assertEqual(api.telemetry_active, 0)

    async def test_reconciliation_caps_target_count(self):
        devices = _device_map()
        devices["gate"] = [
            {"id": f"gate-{index}"} for index in range(70)
        ]
        devices["rfid"] = []
        api = FakeApi()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        with self.assertLogs(
            coordinator_module._LOGGER.name,
            level="WARNING",
        ) as logs:
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)

        self.assertEqual(
            len(api.telemetry_calls),
            coordinator_module._RECONCILIATION_MAX_TARGETS,
        )
        self.assertIn(
            "reconciliation was incomplete",
            "\n".join(logs.output),
        )

    async def test_reconciliation_pass_timeout_cancels_requests(self):
        devices = _device_map()
        devices["rfid"] = []
        api = FakeApi()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        with mock.patch.object(
            coordinator_module,
            "_RECONCILIATION_PASS_TIMEOUT",
            0.01,
        ), self.assertLogs(
            coordinator_module._LOGGER.name,
            level="WARNING",
        ) as logs:
            self.assertTrue(instance.start_state_reconciliation())
            task = instance._reconciliation_task
            self.assertIsNotNone(task)
            await asyncio.wait_for(task, timeout=1)

        self.assertEqual(api.telemetry_cancelled, 1)
        self.assertEqual(api.telemetry_active, 0)
        self.assertIn(
            "reconciliation was incomplete",
            "\n".join(logs.output),
        )

    async def test_unexpected_target_failure_does_not_orphan_sibling_request(self):
        api = FakeApi()
        api.telemetry_unexpected_errors.add(("gate", "device-gate"))
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)

        with self.assertLogs(
            coordinator_module._LOGGER.name,
            level="WARNING",
        ) as logs:
            self.assertTrue(instance.start_state_reconciliation())
            task = instance._reconciliation_task
            self.assertIsNotNone(task)

            async def wait_for_both_targets() -> None:
                for _ in range(100):
                    if len(api.telemetry_calls) == 2:
                        return
                    await asyncio.sleep(0)
                self.fail("both telemetry requests did not start")

            await asyncio.wait_for(wait_for_both_targets(), timeout=1)
            self.assertFalse(task.done())
            self.assertEqual(api.telemetry_active, 1)
            api.telemetry_release.set()
            await self.wait_until_idle(instance)

        combined = "\n".join(logs.output)
        self.assertIn("reconciliation was incomplete", combined)
        self.assertNotIn("fabricated unexpected telemetry failure", combined)
        self.assertNotIn("device-gate", combined)
        self.assertNotIn("device-rfid", combined)
        self.assertEqual(api.telemetry_active, 0)
        self.assertIsNone(instance._reconciliation_task)

    async def test_overlapping_requests_are_limited_to_one_followup(self):
        devices = _device_map()
        devices["rfid"] = []
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        self.assertTrue(instance.start_state_reconciliation())
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)
        for _request in range(10):
            self.assertFalse(instance.start_state_reconciliation())
        api.telemetry_release.set()
        await self.wait_until_idle(instance)

        self.assertEqual(api.telemetry_calls, [("gate", "device-gate")] * 2)
        self.assertIsNone(instance._reconciliation_task)

    async def test_disconnect_cancels_active_reconciliation(self):
        devices = _device_map()
        devices["rfid"] = []
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        self.assertTrue(instance.start_state_reconciliation())
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)
        self.assertTrue(instance.set_mqtt_connected(False))
        await self.wait_until_idle(instance)

        self.assertEqual(api.telemetry_cancelled, 1)
        self.assertEqual(api.telemetry_active, 0)
        self.assertEqual(api.telemetry_calls, [("gate", "device-gate")])
        self.assertIsNone(instance._reconciliation_task)

    async def test_stop_cancels_active_reconciliation_and_disables_restart(self):
        devices = _device_map()
        devices["rfid"] = []
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)

        self.assertTrue(instance.start_state_reconciliation())
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)
        await asyncio.wait_for(
            instance.async_stop_state_reconciliation(),
            timeout=1,
        )

        self.assertEqual(api.telemetry_cancelled, 1)
        self.assertEqual(api.telemetry_active, 0)
        self.assertFalse(instance.start_state_reconciliation())
        self.assertIsNone(instance._reconciliation_task)

    async def test_reconnect_during_cancellation_starts_replacement_pass(self):
        devices = _device_map()
        devices["rfid"] = []
        api = FakeApi()
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)
        self.assertTrue(instance.start_state_reconciliation())
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)

        self.assertTrue(instance.set_mqtt_connected(False))
        self.assertTrue(instance.set_mqtt_connected(True))
        self.assertFalse(instance.start_state_reconciliation())
        api.telemetry_release.set()
        await self.wait_until_idle(instance)

        self.assertEqual(
            api.telemetry_calls,
            [("gate", "device-gate"), ("gate", "device-gate")],
        )
        self.assertTrue(instance.mqtt_connected)

    async def test_failed_reconciliation_is_generic_and_does_not_repeat(self):
        api = FakeApi()
        api.telemetry_errors.add(("gate", "device-gate"))
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)

        with self.assertLogs(coordinator_module._LOGGER.name, level="WARNING") as logs:
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)
        calls_after_failure = list(api.telemetry_calls)
        for _attempt in range(5):
            await asyncio.sleep(0)

        combined = "\n".join(logs.output)
        self.assertIn("reconciliation was incomplete", combined)
        self.assertNotIn("device-gate", combined)
        self.assertNotIn("device-rfid", combined)
        self.assertEqual(api.telemetry_calls, calls_after_failure)

    async def test_gritlock_command_generations_publish_the_confirmed_state(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)

        for expected in (True, False):
            with self.subTest(expected=expected):
                generation_id = instance.begin_gritlock_generation(
                    instance.mqtt_receive_sequence
                )
                self.assertIsNotNone(generation_id)
                confirmation = asyncio.create_task(
                    instance.async_confirm_gritlock_state(
                        expected,
                        generation_id=generation_id,
                        timeout=0.2,
                    )
                )
                await asyncio.sleep(0)
                for trigger_id in ("trigger-one", "trigger-two"):
                    self.assertTrue(
                        instance.handle_mqtt_message(
                            "hub-expected",
                            "trigger",
                            trigger_id,
                            "gl",
                            {"gte": 1, "gls": expected},
                        )
                    )
                self.assertTrue(
                    instance._settle_gritlock_generation(
                        generation_id,
                        force=True,
                    )
                )
                self.assertTrue(
                    await asyncio.wait_for(confirmation, timeout=1)
                )
                self.assertIs(instance.gritlock_state, expected)

    async def test_gritlock_generation_never_reuses_previous_observations(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)

        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "gl",
                    {"gte": 1, "gls": 1},
                )
            )
        first = instance._gritlock_active_generation
        self.assertTrue(
            instance._settle_gritlock_generation(first.generation_id, force=True)
        )
        self.assertTrue(instance.gritlock_state)

        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "gl",
                {"gte": 1, "gls": 0},
            )
        )
        self.assertTrue(instance.gritlock_state)
        second = instance._gritlock_active_generation
        self.assertTrue(
            instance._settle_gritlock_generation(second.generation_id, force=True)
        )
        self.assertIsNone(instance.gritlock_state)

        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "gl",
                    {"gte": 1, "gls": 0},
                )
            )
        third = instance._gritlock_active_generation
        self.assertTrue(
            instance._settle_gritlock_generation(third.generation_id, force=True)
        )
        self.assertFalse(instance.gritlock_state)

    async def test_gritlock_contradiction_fails_command_and_publishes_unknown(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)
        generation_id = instance.begin_gritlock_generation(
            instance.mqtt_receive_sequence
        )
        confirmation = asyncio.create_task(
            instance.async_confirm_gritlock_state(
                True,
                generation_id=generation_id,
                timeout=0.2,
            )
        )
        await asyncio.sleep(0)
        for trigger_id, locked in (("trigger-one", True), ("trigger-two", False)):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "gl",
                    {"gte": 1, "gls": locked},
                )
            )
        self.assertTrue(
            instance._settle_gritlock_generation(generation_id, force=True)
        )
        self.assertFalse(await asyncio.wait_for(confirmation, timeout=1))
        self.assertIsNone(instance.gritlock_state)

    async def test_external_gritlock_burst_publishes_only_after_quiet_settle(self):
        devices = _device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)
        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "gl",
                    {"gte": 1, "gls": 1},
                )
            )
        settle_task = instance._gritlock_settle_task
        self.assertIsNotNone(settle_task)
        generation = instance._gritlock_active_generation
        self.assertTrue(
            instance._settle_gritlock_generation(
                generation.generation_id,
                force=True,
            )
        )
        await asyncio.gather(settle_task, return_exceptions=True)
        self.assertTrue(instance.gritlock_state)
        self.assertIsNone(instance._gritlock_active_generation)

    async def test_rest_refresh_updates_active_participation_not_settled_state(self):
        devices = _device_map()
        devices["trigger"] = [
            {
                "id": "trigger-one",
                "gritLockEnabled": True,
                "gritLockState": True,
            }
        ]
        api = FakeApi(
            {
                "trigger": [
                    {"id": "trigger-one", "gritLockEnabled": True},
                    {"id": "trigger-two", "gritLockEnabled": True},
                ]
            }
        )
        instance = self.coordinator(api, devices)
        instance.set_mqtt_connected(True)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "gl",
                {"gte": 1, "gls": 1},
            )
        )

        refreshed = await instance._async_update_data()
        generation = instance._gritlock_active_generation
        self.assertEqual(
            generation.rest_participants,
            frozenset({"trigger-one", "trigger-two"}),
        )
        self.assertTrue(
            instance._settle_gritlock_generation(
                generation.generation_id,
                force=True,
            )
        )
        instance.data = refreshed
        self.assertIsNone(instance.gritlock_state)

        api.collections["trigger"] = [
            {
                "id": "trigger-one",
                "gritLockEnabled": True,
                "gritLockState": False,
            }
        ]
        refreshed = await instance._async_update_data()
        instance.data = refreshed
        self.assertIsNone(instance.gritlock_state)

    async def test_gritlock_disconnect_discards_active_generation_and_falls_back(self):
        devices = _device_map()
        devices["trigger"] = [
            {
                "id": "trigger-one",
                "gritLockEnabled": True,
                "gritLockState": False,
            }
        ]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "gl",
                {"gte": 1, "gls": 1},
            )
        )
        settle_task = instance._gritlock_settle_task
        self.assertTrue(instance.set_mqtt_connected(False))
        if settle_task is not None:
            await asyncio.gather(settle_task, return_exceptions=True)
        self.assertIsNone(instance._gritlock_active_generation)
        self.assertIsNone(instance._gritlock_settled_generation)
        self.assertFalse(instance.gritlock_state)
        self.assertIsNone(instance._gritlock_settle_task)

    async def test_rfid_stale_match_and_fresh_contradiction_fail_confirmation(self):
        instance = self.coordinator(FakeApi())
        instance.set_mqtt_connected(True)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True},
            )
        )
        boundary = instance.mqtt_receive_sequence
        self.assertFalse(
            await instance.async_confirm_device_state(
                "rfid",
                "device-rfid",
                True,
                after_sequence=boundary,
                timeout=0.01,
            )
        )

        boundary = instance.mqtt_receive_sequence
        confirmation = asyncio.create_task(
            instance.async_confirm_device_state(
                "rfid",
                "device-rfid",
                True,
                after_sequence=boundary,
                timeout=0.1,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "rfid",
                "device-rfid",
                "st",
                {"state": True},
            )
        )
        self.assertFalse(await asyncio.wait_for(confirmation, timeout=1))
        self.assertEqual(instance._mqtt_state_waiters, set())

    async def test_gritlock_stop_and_cancellation_release_waiters(self):
        devices = _device_map()
        devices["trigger"] = [{"id": "trigger-one"}]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)

        generation_id = instance.begin_gritlock_generation(
            instance.mqtt_receive_sequence
        )
        stopped = asyncio.create_task(
            instance.async_confirm_gritlock_state(
                True,
                generation_id=generation_id,
                timeout=0.2,
            )
        )
        await asyncio.sleep(0)
        await instance.async_stop_state_reconciliation()
        self.assertFalse(await asyncio.wait_for(stopped, timeout=1))
        self.assertEqual(instance._mqtt_state_waiters, set())

        replacement = self.coordinator(FakeApi(), devices)
        replacement.set_mqtt_connected(True)
        generation_id = replacement.begin_gritlock_generation(
            replacement.mqtt_receive_sequence
        )
        cancelled = asyncio.create_task(
            replacement.async_confirm_gritlock_state(
                True,
                generation_id=generation_id,
                timeout=0.2,
            )
        )
        await asyncio.sleep(0)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        self.assertEqual(replacement._mqtt_state_waiters, set())

    async def test_mqtt_state_waiter_collection_is_bounded(self):
        devices = _device_map()
        devices["trigger"] = [{"id": "trigger-one"}]
        instance = self.coordinator(FakeApi(), devices)
        instance.set_mqtt_connected(True)
        loop = asyncio.get_running_loop()
        existing = {
            loop.create_future()
            for _ in range(coordinator_module._MAX_MQTT_STATE_WAITERS)
        }
        instance._mqtt_state_waiters.update(existing)

        try:
            self.assertFalse(
                await instance.async_confirm_gritlock_state(
                    True,
                    generation_id=instance.begin_gritlock_generation(
                        instance.mqtt_receive_sequence
                    ),
                    timeout=0.1,
                )
            )
            self.assertEqual(
                len(instance._mqtt_state_waiters),
                coordinator_module._MAX_MQTT_STATE_WAITERS,
            )
        finally:
            for waiter in existing:
                waiter.cancel()
            instance._mqtt_state_waiters.clear()

    async def test_normal_polling_does_not_request_mesh_telemetry(self):
        api = FakeApi(
            {
                "gate": [{"id": "device-gate"}],
                "rfid": [{"id": "device-rfid"}],
            }
        )
        instance = self.coordinator(api)
        instance.set_mqtt_connected(True)

        for _poll in range(2):
            refreshed = await instance._async_update_data()
            instance.data = refreshed
            await asyncio.sleep(0)

        self.assertEqual(api.telemetry_calls, [])
        self.assertIsNone(instance._reconciliation_task)
        await instance.async_stop_state_reconciliation()
        self.assertFalse(instance.start_state_reconciliation())

if __name__ == "__main__":
    unittest.main()

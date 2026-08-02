"""Network-free tests for coordinator MQTT state ingestion."""
from __future__ import annotations

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
        self.hub = {"id": "rest-hub"}

    async def health_check(self):
        return deepcopy(self.health)

    async def get_hub(self):
        return deepcopy(self.hub)

    async def get_collection(self, device_type):
        return deepcopy(self.collections.get(device_type, []))


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
        socket_patch = mock.patch.object(
            socket,
            "socket",
            side_effect=AssertionError("network socket creation is forbidden"),
        )
        connection_patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        socket_patch.start()
        connection_patch.start()
        self.addCleanup(socket_patch.stop)
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

    def test_switch_and_rfid_message_aliases_are_bounded(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                device_type="rfid",
                device_id="device-rfid",
                message_type="sts",
                payload={"s": "on"},
            )
        )
        self.assertTrue(self.mqtt_state(instance, "rfid")["state"])
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
                "last_message_type",
                "last_received_at",
                "source_sequence",
                "source_timestamp",
                "_ordering",
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

    def test_exact_duplicate_is_a_no_op(self):
        instance = self.coordinator()
        self.assertTrue(self.send(instance, payload={"online": True}))
        original_state = deepcopy(self.mqtt_state(instance))
        self.assertFalse(self.send(instance, payload={"online": True}))
        self.assertEqual(len(instance.updated_data), 1)
        self.assertEqual(self.mqtt_state(instance), original_state)

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

    def test_arrival_order_applies_when_source_metadata_is_absent(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(instance, payload={"online": False, "seq": 5})
        )
        self.assertTrue(self.send(instance, payload={"online": True}))
        state = self.mqtt_state(instance)
        self.assertTrue(state["online"])
        self.assertNotIn("source_sequence", state)
        self.assertNotIn("online", state.get("_ordering", {}))

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

    def test_rest_refresh_preserves_unique_same_type_state(self):
        instance = self.coordinator(
            api=FakeApi({"gate": [{"deviceId": "device-gate"}]})
        )
        self.assertTrue(self.send(instance, payload={"position": 90}))
        refreshed = _run_immediate(instance._async_update_data())
        state = refreshed["devices"]["gate"][0][
            coordinator_module.MQTT_STATE_KEY
        ]
        self.assertEqual(state["position"], 90)

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
        self.assertNotIn("raw_payload", state)
        self.assertNotIn("unexpected", state)
        self.assertNotIn("_ordering", state)

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

    def test_additional_message_type_components_are_preserved(self):
        instance = self.coordinator()
        self.assertTrue(
            self.send(
                instance,
                message_type="status/diagnostic/variant",
                payload={"online": True},
            )
        )
        self.assertEqual(
            self.mqtt_state(instance)["last_message_type"],
            "status/diagnostic/variant",
        )

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


if __name__ == "__main__":
    unittest.main()

"""Network-free startup hydration tests for gates and GRITLock."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import socket
import unittest
from unittest import mock

from tests import test_coordinator_mqtt as coordinator_tests
from tests import test_entities_mqtt as entity_tests


coordinator_module = coordinator_tests.coordinator_module
COVER_MODULE = entity_tests.COVER_MODULE
LOCK_MODULE = entity_tests.LOCK_MODULE


class StartupHydrationTests(unittest.IsolatedAsyncioTestCase):
    """Drive actual coordinator and entity code using fabricated responses."""

    def setUp(self) -> None:
        for name in ("connect", "connect_ex"):
            patcher = mock.patch.object(
                socket.socket,
                name,
                side_effect=AssertionError("network connection is forbidden"),
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        connection_patcher = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)

    def coordinator(self, devices):
        api = coordinator_tests.FakeApi()
        api.auto_telemetry = False
        instance = coordinator_module.GritHubCoordinator(
            object(),
            api,
            30,
            expected_mqtt_hub_id="hub-expected",
        )
        instance.data = {
            "devices": deepcopy(devices),
            "hub": None,
            "health": None,
            "errors": {},
        }
        instance.last_update_success = True
        self.addAsyncCleanup(instance.async_stop_state_reconciliation)
        return instance, api

    @staticmethod
    async def wait_until_idle(instance) -> None:
        for _pass in range(4):
            task = instance._reconciliation_task
            if task is None:
                return
            await asyncio.wait_for(asyncio.shield(task), timeout=1)
        raise AssertionError("startup reconciliation did not finish")

    @staticmethod
    async def wait_for_gritlock_startup(instance) -> None:
        task = instance._gritlock_startup_task
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=1)

    async def test_request_waits_for_readiness_and_gate_sts_hydrates(self):
        devices = coordinator_tests._device_map()
        devices["rfid"] = []
        instance, api = self.coordinator(devices)

        self.assertFalse(instance.start_state_reconciliation())
        self.assertEqual(api.telemetry_calls, [])

        def respond(device_type, device_id):
            session = instance._startup_hydration
            self.assertIsNotNone(session)
            self.assertTrue(instance.mqtt_connected)
            self.assertIn((device_type, device_id), session.requested_targets)
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "gate",
                    device_id,
                    "sts",
                    {"p": "0", "sts": 1},
                )
            )

        api.telemetry_hook = respond
        instance.set_mqtt_connected(True)
        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)

        gate = instance.data["devices"]["gate"][0]
        entity = COVER_MODULE.GritHubGateCover(instance, "gate", gate)
        self.assertEqual(api.telemetry_calls, [("gate", "device-gate")])
        self.assertEqual(entity.current_cover_position, 0)
        self.assertTrue(entity.is_closed)
        self.assertTrue(entity.available)

    async def test_multiple_gates_partially_hydrate_and_state_is_preserved(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = [{"id": "gate-one"}, {"id": "gate-two"}]
        devices["rfid"] = []
        instance, api = self.coordinator(devices)

        def respond(device_type, device_id):
            if device_type == "gate" and device_id == "gate-one":
                instance.handle_mqtt_message(
                    "hub-expected",
                    "gate",
                    device_id,
                    "tel",
                    {"p": "100", "sts": 1},
                )

        api.telemetry_hook = respond
        instance.set_mqtt_connected(True)
        with (
            mock.patch.object(
                coordinator_module,
                "_RECONCILIATION_RESPONSE_TIMEOUT",
                0.01,
            ),
            self.assertLogs(coordinator_module._LOGGER.name, "WARNING") as logs,
        ):
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)

        first = instance.data["devices"]["gate"][0]
        second = instance.data["devices"]["gate"][1]
        self.assertTrue(first[coordinator_module.MQTT_STATE_KEY]["open"])
        self.assertNotIn(coordinator_module.MQTT_STATE_KEY, second)
        combined = "\n".join(logs.output)
        self.assertEqual(combined.count("reconciliation was incomplete"), 1)
        for private_detail in ("gate-one", "gate-two", "grit/", "100"):
            self.assertNotIn(private_detail, combined)

        api.telemetry_hook = lambda *_args: None
        with mock.patch.object(
            coordinator_module,
            "_RECONCILIATION_RESPONSE_TIMEOUT",
            0.01,
        ):
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)
        self.assertTrue(
            instance.data["devices"]["gate"][0][
                coordinator_module.MQTT_STATE_KEY
            ]["open"]
        )

    async def test_req_tel_is_not_state_but_live_movement_topics_remain(self):
        devices = coordinator_tests._device_map()
        instance, _api = self.coordinator(devices)
        self.assertFalse(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "req-tel",
                {"p": "100"},
            )
        )
        self.assertNotIn(
            coordinator_module.MQTT_STATE_KEY,
            instance.data["devices"]["gate"][0],
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "mv",
                {"p": 65},
            )
        )
        self.assertFalse(
            instance.data["devices"]["gate"][0][
                coordinator_module.MQTT_STATE_KEY
            ]["open"]
        )
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "gate",
                "device-gate",
                "mv-d",
                {"p": 90, "s": 0},
            )
        )
        self.assertTrue(
            instance.data["devices"]["gate"][0][
                coordinator_module.MQTT_STATE_KEY
            ]["open"]
        )

    async def _hydrate_gritlock(self, locked: bool, topic: str):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False},
            {"id": "trigger-two", "gritLockEnabled": False},
        ]
        instance, api = self.coordinator(devices)

        def respond(device_type, device_id):
            instance.handle_mqtt_message(
                "hub-expected",
                device_type,
                device_id,
                topic,
                {"gls": int(locked), "sts": 1},
            )

        api.telemetry_hook = respond
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            instance.set_mqtt_connected(True)
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)
            await self.wait_for_gritlock_startup(instance)
        return instance, api

    async def _status_before_refresh_completes(self, locked):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        instance, api = self.coordinator(devices)
        api.telemetry_entered = asyncio.Event()
        api.telemetry_release = asyncio.Event()

        instance.set_mqtt_connected(True)
        startup_task = instance._gritlock_startup_task
        listener_updates = instance.listener_updates
        self.assertTrue(instance.start_state_reconciliation())
        await asyncio.wait_for(api.telemetry_entered.wait(), timeout=1)

        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "sts",
                    {"gls": int(locked), "sts": 1},
                )
            )

        entity = LOCK_MODULE.GritHubSystemLock(instance)
        self.assertIs(instance.gritlock_state, locked)
        self.assertIs(entity.is_locked, locked)
        self.assertTrue(entity.available)
        self.assertEqual(instance.listener_updates, listener_updates + 1)
        self.assertIsNone(instance._gritlock_startup_snapshot)
        self.assertEqual(api.telemetry_active, 2)

        api.telemetry_release.set()
        await self.wait_until_idle(instance)
        if startup_task is not None:
            await asyncio.wait_for(asyncio.shield(startup_task), timeout=1)
        self.assertIs(instance.gritlock_state, locked)
        return instance, api

    async def test_locked_status_before_refresh_completion_hydrates(self):
        await self._status_before_refresh_completes(True)

    async def test_unlocked_status_before_refresh_completion_hydrates(self):
        await self._status_before_refresh_completes(False)

    async def test_ready_status_before_individual_request_is_accepted(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        instance, api = self.coordinator(devices)
        instance.set_mqtt_connected(True)

        self.assertEqual(api.telemetry_calls, [])
        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "sts",
                    {"gls": 1},
                )
            )
        self.assertTrue(instance.gritlock_state)

        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)
        self.assertEqual(
            api.telemetry_calls,
            [
                ("trigger", "trigger-one"),
                ("trigger", "trigger-two"),
            ],
        )
        self.assertTrue(instance.gritlock_state)

    async def test_pre_readiness_status_is_rejected(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True}
        ]
        instance, _api = self.coordinator(devices)

        self.assertFalse(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "sts",
                {"gls": 1},
            )
        )
        self.assertIsNone(instance.gritlock_state)
        self.assertIsNone(instance._gritlock_startup_snapshot)

    async def test_tel_without_gls_cannot_replace_valid_status(self):
        instance, api = await self._status_before_refresh_completes(True)

        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "tel",
                {"sts": 1, "rssi": -40},
            )
        )
        self.assertTrue(instance.gritlock_state)
        self.assertIsNone(instance._gritlock_startup_snapshot)

        api.telemetry_errors.update(
            {
                ("trigger", "trigger-one"),
                ("trigger", "trigger-two"),
            }
        )
        with self.assertLogs(
            coordinator_module._LOGGER.name,
            "WARNING",
        ) as logs:
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)
        self.assertTrue(instance.gritlock_state)
        self.assertIn(
            "device state reconciliation was incomplete",
            "\n".join(logs.output),
        )

    async def test_gls_is_independent_of_stale_diagnostic_ordering(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True}
        ]
        instance, _api = self.coordinator(devices)

        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "sts",
                {"sts": 1, "sequence": 5},
            )
        )
        before_sequence = instance.mqtt_receive_sequence
        instance.set_mqtt_connected(True)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "sts",
                {"sts": 1, "gls": 1, "sequence": 5},
            )
        )

        self.assertEqual(
            instance.mqtt_receive_sequence,
            before_sequence + 1,
        )
        self.assertTrue(instance.gritlock_state)
        self.assertIsNone(instance._gritlock_startup_snapshot)

    async def test_invalid_gls_and_unrelated_status_are_ignored(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False},
            {"id": "trigger-two", "gritLockEnabled": False},
        ]
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            instance, _api = self.coordinator(devices)
            instance.set_mqtt_connected(True)
            for invalid in (None, "1", 2, -1, [], {}):
                self.assertFalse(
                    instance.handle_mqtt_message(
                        "hub-expected",
                        "trigger",
                        "trigger-one",
                        "sts",
                        {"gls": invalid},
                    )
                )
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "sts",
                    {"gls": 1},
                )
            )
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-two",
                    "tel",
                    {"sts": 1},
                )
            )
            snapshot = instance._gritlock_startup_snapshot
            self.assertIsNotNone(snapshot)
            self.assertEqual(
                {key: value[0] for key, value in snapshot.observations.items()},
                {"trigger-one": True},
            )
            await self.wait_for_gritlock_startup(instance)

        self.assertTrue(instance.gritlock_state)

    async def test_duplicate_status_replaces_only_same_trigger(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            instance, _api = self.coordinator(devices)
            instance.set_mqtt_connected(True)
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "sts",
                    {"gls": 1},
                )
            )
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "sts",
                    {"gls": 0},
                )
            )
            snapshot = instance._gritlock_startup_snapshot
            self.assertIsNotNone(snapshot)
            self.assertEqual(
                {key: value[0] for key, value in snapshot.observations.items()},
                {"trigger-one": False},
            )
            await self.wait_for_gritlock_startup(instance)

        self.assertFalse(instance.gritlock_state)

    async def test_rest_participants_ignore_nonparticipant_status(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
            {"id": "trigger-other", "gritLockEnabled": False},
        ]
        instance, _api = self.coordinator(devices)
        instance.set_mqtt_connected(True)

        self.assertFalse(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-other",
                "sts",
                {"gls": 0},
            )
        )
        for trigger_id in ("trigger-one", "trigger-two"):
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    trigger_id,
                    "sts",
                    {"gls": 1},
                )
            )
        self.assertTrue(instance.gritlock_state)

    async def test_missing_required_rest_participant_remains_unknown(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        with (
            mock.patch.object(
                coordinator_module,
                "_GRITLOCK_STARTUP_WINDOW",
                0.01,
            ),
            self.assertLogs(coordinator_module._LOGGER.name, "WARNING") as logs,
        ):
            instance, _api = self.coordinator(devices)
            instance.set_mqtt_connected(True)
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "sts",
                    {"gls": 1},
                )
            )
            await self.wait_for_gritlock_startup(instance)

        self.assertIsNone(instance.gritlock_state)
        self.assertFalse(LOCK_MODULE.GritHubSystemLock(instance).available)
        combined = "\n".join(logs.output)
        self.assertIn("startup state hydration was incomplete", combined)
        for private_detail in (
            "trigger-one",
            "trigger-two",
            "hub-expected",
            "grit/",
        ):
            self.assertNotIn(private_detail, combined)

    async def test_fallback_snapshot_is_bounded(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": f"trigger-{index}", "gritLockEnabled": False}
            for index in range(coordinator_module._MAX_GRITLOCK_OBSERVATIONS)
        ]
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            instance, _api = self.coordinator(devices)
            instance.set_mqtt_connected(True)
            for index in range(coordinator_module._MAX_GRITLOCK_OBSERVATIONS):
                self.assertTrue(
                    instance.handle_mqtt_message(
                        "hub-expected",
                        "trigger",
                        f"trigger-{index}",
                        "sts",
                        {"gls": 1},
                    )
                )
            snapshot = instance._gritlock_startup_snapshot
            self.assertIsNotNone(snapshot)
            self.assertEqual(
                len(snapshot.observations),
                coordinator_module._MAX_GRITLOCK_OBSERVATIONS,
            )
            await self.wait_for_gritlock_startup(instance)
        self.assertTrue(instance.gritlock_state)

        overflow_devices = deepcopy(devices)
        overflow_devices["trigger"].append(
            {"id": "trigger-overflow", "gritLockEnabled": False}
        )
        overflow_instance, _api = self.coordinator(overflow_devices)
        overflow_instance.set_mqtt_connected(True)
        snapshot = overflow_instance._gritlock_startup_snapshot
        self.assertIsNotNone(snapshot)
        self.assertFalse(snapshot.fallback_usable)
        self.assertEqual(snapshot.observations, {})
        self.assertFalse(
            overflow_instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-overflow",
                "sts",
                {"gls": 1},
            )
        )

    async def test_complete_startup_disagreement_invalidates_authority(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False},
            {"id": "trigger-two", "gritLockEnabled": False},
        ]
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            instance, _api = self.coordinator(devices)
            instance.set_mqtt_connected(True)
            instance._clear_gritlock_startup_snapshot()
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "gl",
                    {"gte": 0, "gls": 1},
                )
            )
            burst = instance._gritlock_live_burst
            self.assertTrue(
                instance._settle_gritlock_burst(burst, force=True)
            )
            self.assertIs(instance.gritlock_state, True)

            instance._begin_gritlock_startup_snapshot()
            for trigger_id, locked in (
                ("trigger-one", 1),
                ("trigger-two", 0),
            ):
                self.assertTrue(
                    instance.handle_mqtt_message(
                        "hub-expected",
                        "trigger",
                        trigger_id,
                        "sts",
                        {"gls": locked},
                    )
                )
            await self.wait_for_gritlock_startup(instance)

        self.assertIsNone(instance.gritlock_state)
        self.assertEqual(
            instance._gritlock_state_observation.source,
            coordinator_module._GRITLOCK_SOURCE_DISAGREEMENT,
        )
        self.assertFalse(LOCK_MODULE.GritHubSystemLock(instance).available)
    async def test_trigger_status_hydrates_exact_locked_and_unlocked_states(self):
        for locked, topic in ((True, "sts"), (False, "tel")):
            with self.subTest(locked=locked, topic=topic):
                instance, api = await self._hydrate_gritlock(locked, topic)
                entity = LOCK_MODULE.GritHubSystemLock(instance)
                self.assertIs(instance.gritlock_state, locked)
                self.assertIs(entity.is_locked, locked)
                self.assertTrue(entity.available)
                self.assertEqual(
                    api.telemetry_calls,
                    [
                        ("trigger", "trigger-one"),
                        ("trigger", "trigger-two"),
                    ],
                )

    async def test_multiple_gates_independently_hydrate(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = [{"id": "gate-one"}, {"id": "gate-two"}]
        devices["rfid"] = []
        instance, api = self.coordinator(devices)

        positions = {"gate-one": "0", "gate-two": "100"}

        def respond(device_type, device_id):
            if device_type == "gate":
                instance.handle_mqtt_message(
                    "hub-expected",
                    device_type,
                    device_id,
                    "sts",
                    {"p": positions[device_id], "sts": 1},
                )

        api.telemetry_hook = respond
        instance.set_mqtt_connected(True)
        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)

        states = {
            gate["id"]: gate[coordinator_module.MQTT_STATE_KEY]["open"]
            for gate in instance.data["devices"]["gate"]
        }
        self.assertEqual(states, {"gate-one": False, "gate-two": True})

    async def test_missing_gate_does_not_suppress_complete_gritlock_status(self):
        devices = coordinator_tests._device_map()
        devices["rfid"] = []
        devices["trigger"] = [{"id": "trigger-one"}]
        instance, api = self.coordinator(devices)

        def respond(device_type, device_id):
            if device_type == "trigger":
                instance.handle_mqtt_message(
                    "hub-expected",
                    device_type,
                    device_id,
                    "sts",
                    {"gls": 1, "sts": 1},
                )

        api.telemetry_hook = respond
        instance.set_mqtt_connected(True)
        with (
            mock.patch.object(
                coordinator_module,
                "_RECONCILIATION_RESPONSE_TIMEOUT",
                0.01,
            ),
            mock.patch.object(
                coordinator_module,
                "_GRITLOCK_STARTUP_QUIET_TIME",
                0.01,
            ),
            self.assertLogs(coordinator_module._LOGGER.name, "WARNING"),
        ):
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)
            await self.wait_for_gritlock_startup(instance)

        self.assertNotIn(
            coordinator_module.MQTT_STATE_KEY,
            instance.data["devices"]["gate"][0],
        )
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        self.assertTrue(instance.gritlock_state)
        self.assertTrue(entity.is_locked)
        self.assertTrue(entity.available)

    async def test_invalid_trigger_status_stays_unknown_and_unavailable(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [{"id": "trigger-one"}]
        instance, api = self.coordinator(devices)
        api.telemetry_hook = lambda device_type, device_id: (
            instance.handle_mqtt_message(
                "hub-expected",
                device_type,
                device_id,
                "sts",
                {"gls": 2, "sts": 1},
            )
        )
        with (
            mock.patch.object(
                coordinator_module,
                "_GRITLOCK_STARTUP_WINDOW",
                0.01,
            ),
            self.assertLogs(coordinator_module._LOGGER.name, "WARNING"),
        ):
            instance.set_mqtt_connected(True)
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)
            await self.wait_for_gritlock_startup(instance)

        entity = LOCK_MODULE.GritHubSystemLock(instance)
        self.assertIsNone(instance.gritlock_state)
        self.assertIsNone(entity.is_locked)
        self.assertFalse(entity.available)

    async def test_startup_snapshot_cannot_cross_command_boundary(self):
        devices = coordinator_tests._device_map()
        devices["gate"] = []
        devices["rfid"] = []
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            instance, _api = self.coordinator(devices)
            instance.set_mqtt_connected(True)
            connection = instance.mqtt_connection_generation
            boundary = instance.mqtt_receive_sequence
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "sts",
                    {"gls": 1},
                )
            )
            await self.wait_for_gritlock_startup(instance)

        self.assertIs(instance.gritlock_state, True)
        self.assertEqual(
            instance._gritlock_state_observation.source,
            coordinator_module._GRITLOCK_SOURCE_STARTUP,
        )
        self.assertFalse(
            await instance.async_wait_for_gritlock_state(
                True,
                after_connection_generation=connection,
                after_receive_sequence=boundary,
                timeout=0.01,
            )
        )
        self.assertIs(instance.gritlock_state, True)
    async def test_reconnect_rejects_prior_state_and_accepts_ready_status(self):
        instance, _api = await self._hydrate_gritlock(False, "sts")
        self.assertTrue(instance.set_mqtt_connected(False))
        self.assertIsNone(instance.gritlock_state)
        self.assertIsNone(instance._gritlock_startup_snapshot)

        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.01,
        ):
            self.assertTrue(instance.set_mqtt_connected(True))
            self.assertIsNone(instance.gritlock_state)
            self.assertTrue(
                instance.handle_mqtt_message(
                    "hub-expected",
                    "trigger",
                    "trigger-one",
                    "sts",
                    {"gls": 1},
                )
            )
            await self.wait_for_gritlock_startup(instance)

        self.assertTrue(instance.gritlock_state)

    async def test_unload_cancels_pending_response_wait_without_restart(self):
        devices = coordinator_tests._device_map()
        devices["rfid"] = []
        instance, api = self.coordinator(devices)
        request_completed = asyncio.Event()

        def no_response(_device_type, _device_id):
            request_completed.set()

        api.telemetry_hook = no_response
        instance.set_mqtt_connected(True)
        self.assertTrue(instance.start_state_reconciliation())
        await asyncio.wait_for(request_completed.wait(), timeout=1)
        self.assertIsNotNone(instance._startup_hydration)

        await asyncio.wait_for(
            instance.async_stop_state_reconciliation(),
            timeout=1,
        )

        self.assertIsNone(instance._startup_hydration)
        self.assertIsNone(instance._gritlock_startup_snapshot)
        self.assertIsNone(instance._gritlock_startup_task)
        self.assertIsNone(instance._reconciliation_task)
        self.assertEqual(instance._telemetry_request_tasks, {})
        self.assertFalse(instance.start_state_reconciliation())


if __name__ == "__main__":
    unittest.main()

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

    @staticmethod
    def coordinator(devices):
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
        return instance, api

    @staticmethod
    async def wait_until_idle(instance) -> None:
        for _pass in range(4):
            task = instance._reconciliation_task
            if task is None:
                return
            await asyncio.wait_for(asyncio.shield(task), timeout=1)
        raise AssertionError("startup reconciliation did not finish")

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
        instance.set_mqtt_connected(True)
        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)
        return instance, api

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
            self.assertLogs(coordinator_module._LOGGER.name, "WARNING"),
        ):
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)

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
        instance.set_mqtt_connected(True)
        with mock.patch.object(
            coordinator_module,
            "_RECONCILIATION_RESPONSE_TIMEOUT",
            0.01,
        ):
            self.assertTrue(instance.start_state_reconciliation())
            await self.wait_until_idle(instance)

        entity = LOCK_MODULE.GritHubSystemLock(instance)
        self.assertIsNone(instance.gritlock_state)
        self.assertIsNone(entity.is_locked)
        self.assertFalse(entity.available)

    async def test_startup_status_cannot_confirm_command_generation(self):
        instance, _api = await self._hydrate_gritlock(False, "sts")
        generation_id = instance.begin_gritlock_generation(
            instance.mqtt_receive_sequence
        )
        self.assertIsNotNone(generation_id)
        self.assertTrue(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "sts",
                {"gls": 1, "sts": 1},
            )
        )
        self.assertFalse(
            await instance.async_confirm_gritlock_state(
                True,
                generation_id=generation_id,
                timeout=0.01,
            )
        )
        self.assertFalse(instance.gritlock_state)
        self.assertTrue(instance.cancel_gritlock_generation(generation_id))

    async def test_reconnect_ignores_pre_request_status_and_hydrates_fresh(self):
        instance, api = await self._hydrate_gritlock(False, "sts")
        self.assertTrue(instance.set_mqtt_connected(False))
        self.assertIsNone(instance.gritlock_state)
        self.assertTrue(instance.set_mqtt_connected(True))
        self.assertFalse(
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-one",
                "sts",
                {"gls": 0},
            )
        )
        self.assertIsNone(instance.gritlock_state)

        api.telemetry_hook = lambda device_type, device_id: (
            instance.handle_mqtt_message(
                "hub-expected",
                device_type,
                device_id,
                "sts",
                {"gls": 1, "sts": 1},
            )
        )
        self.assertTrue(instance.start_state_reconciliation())
        await self.wait_until_idle(instance)
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
        self.assertIsNone(instance._reconciliation_task)
        self.assertEqual(instance._telemetry_request_tasks, {})
        self.assertFalse(instance.start_state_reconciliation())


if __name__ == "__main__":
    unittest.main()

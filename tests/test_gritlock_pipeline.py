"""Network-free end-to-end GRITLock state-pipeline tests."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import socket
from typing import Callable
import unittest
from unittest import mock

from tests import test_coordinator_mqtt as coordinator_tests
from tests import test_entities_mqtt as entity_tests


coordinator_module = coordinator_tests.coordinator_module
LOCK_MODULE = entity_tests.LOCK_MODULE


class PipelineApi(coordinator_tests.FakeApi):
    """Fake REST client whose command hook emits fabricated MQTT frames."""

    def __init__(self, collections=None) -> None:
        super().__init__(collections)
        self.gritlock_calls: list[bool] = []
        self.command_hook: Callable[[bool], None] | None = None
        self.command_error = False

    async def set_gritlock(self, locked: bool) -> None:
        self.gritlock_calls.append(locked)
        if self.command_error:
            raise RuntimeError("fabricated command failure")
        if self.command_hook is not None:
            self.command_hook(locked)


class GritlockPipelineTests(unittest.IsolatedAsyncioTestCase):
    """Exercise actual parser, coordinator, and entity code together."""

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

    def coordinator(
        self,
        devices: dict[str, list[dict]],
        api: PipelineApi | None = None,
    ):
        instance = coordinator_module.GritHubCoordinator(
            object(),
            api or PipelineApi(),
            30,
            expected_mqtt_hub_id="hub-expected",
        )
        instance.last_update_success = True
        instance.data = {
            "devices": deepcopy(devices),
            "hub": None,
            "health": None,
            "errors": {},
        }
        return instance

    @staticmethod
    def emit(
        instance,
        frames: tuple[tuple[str, int, int], ...],
    ) -> None:
        for trigger_id, gte, gls in frames:
            accepted = instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                trigger_id,
                "gl",
                {"gte": gte, "gls": gls},
            )
            if not accepted:
                raise AssertionError("fabricated GRITLock frame was rejected")

    async def settle(
        self,
        instance,
        frames: tuple[tuple[str, int, int], ...],
    ) -> None:
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_SETTLE_TIME",
            0.001,
        ):
            self.emit(instance, frames)
            task = instance._gritlock_settle_task
            self.assertIsNotNone(task)
            await asyncio.wait_for(task, timeout=1)

    async def test_startup_without_mqtt_authority_is_unknown_and_unavailable(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {
                "id": "trigger-one",
                "gritLockEnabled": True,
                "gritLockState": True,
            }
        ]
        instance = self.coordinator(devices)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)

        self.assertIsNone(instance.gritlock_state)
        self.assertIsNone(entity.is_locked)
        self.assertFalse(entity.available)

    async def test_dion_startup_manual_lock_and_unlock_command_pipeline(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False},
            {"id": "trigger-two", "gritLockEnabled": False},
            {"id": "trigger-three", "gritLockEnabled": False},
            {"id": "trigger-switch", "gritLockEnabled": False},
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_STARTUP_QUIET_TIME",
            0.001,
        ):
            instance.set_mqtt_connected(True)
            entity = LOCK_MODULE.GritHubSystemLock(instance)
            for trigger_id in (
                "trigger-one",
                "trigger-two",
                "trigger-three",
            ):
                self.assertTrue(
                    instance.handle_mqtt_message(
                        "hub-expected",
                        "trigger",
                        trigger_id,
                        "sts",
                        {"gls": 0},
                    )
                )
            instance.handle_mqtt_message(
                "hub-expected",
                "trigger",
                "trigger-switch",
                "sts",
                {"sts": 1},
            )
            startup_task = instance._gritlock_startup_task
            self.assertIsNotNone(startup_task)
            await asyncio.wait_for(startup_task, timeout=1)

        self.assertFalse(instance.gritlock_state)
        self.assertFalse(entity.is_locked)
        self.assertTrue(entity.available)
        self.assertEqual(
            instance._gritlock_state_observation.source,
            coordinator_module._GRITLOCK_SOURCE_STARTUP,
        )

        locked_frames = (
            ("trigger-one", 1, 1),
            ("trigger-two", 1, 1),
            ("trigger-three", 0, 0),
        )
        unlocked_frames = (
            ("trigger-one", 0, 0),
            ("trigger-two", 0, 0),
            ("trigger-three", 0, 0),
        )
        api.command_hook = lambda locked: self.emit(
            instance,
            locked_frames if locked else unlocked_frames,
        )
        listener_updates = instance.listener_updates
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_SETTLE_TIME",
            0.001,
        ):
            await entity.async_lock()
            self.assertTrue(instance.gritlock_state)
            self.assertTrue(entity.is_locked)
            await entity.async_unlock()

        self.assertEqual(api.gritlock_calls, [True, False])
        self.assertFalse(instance.gritlock_state)
        self.assertFalse(entity.is_locked)
        self.assertTrue(entity.available)
        self.assertGreater(instance.listener_updates, listener_updates)
        self.assertEqual(api.hub_calls, 0)

    async def test_jeff_six_trigger_lock_and_unlock_commands(self):
        trigger_ids = tuple(f"trigger-{index}" for index in range(6))
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": trigger_id, "gritLockEnabled": False}
            for trigger_id in trigger_ids
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)

        api.command_hook = lambda locked: self.emit(
            instance,
            tuple(
                (trigger_id, 0, int(locked))
                for trigger_id in trigger_ids
            ),
        )
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_SETTLE_TIME",
            0.001,
        ):
            await entity.async_lock()
            self.assertTrue(entity.is_locked)
            await entity.async_unlock()

        self.assertEqual(api.gritlock_calls, [True, False])
        self.assertFalse(instance.gritlock_state)
        self.assertFalse(entity.is_locked)
        self.assertTrue(entity.available)

    async def test_failed_command_preserves_prior_authoritative_unlocked_state(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": True},
            {"id": "trigger-two", "gritLockEnabled": True},
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        await self.settle(
            instance,
            (
                ("trigger-one", 1, 0),
                ("trigger-two", 1, 0),
            ),
        )
        self.assertFalse(entity.is_locked)

        with (
            mock.patch.object(LOCK_MODULE, "HUB_CONFIRM_TIMEOUT", 0.01),
            self.assertRaisesRegex(
                entity_tests.HomeAssistantError,
                "could not be confirmed",
            ),
        ):
            await entity.async_lock()

        self.assertEqual(api.gritlock_calls, [True])
        self.assertFalse(instance.gritlock_state)
        self.assertFalse(entity.is_locked)
        self.assertTrue(entity.available)

    async def test_noop_timeout_keeps_last_authoritative_state(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        await self.settle(instance, (("trigger-one", 0, 0),))

        with (
            mock.patch.object(LOCK_MODULE, "HUB_CONFIRM_TIMEOUT", 0.01),
            self.assertRaisesRegex(
                entity_tests.HomeAssistantError,
                "could not be confirmed",
            ),
        ):
            await entity.async_unlock()

        self.assertEqual(api.gritlock_calls, [False])
        self.assertFalse(instance.gritlock_state)
        self.assertFalse(entity.is_locked)
        self.assertTrue(entity.available)

    async def test_noop_with_fresh_matching_observation_confirms(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        await self.settle(instance, (("trigger-one", 0, 1),))
        self.assertIs(entity.is_locked, True)

        api.command_hook = lambda _locked: self.emit(
            instance,
            (("trigger-one", 0, 1),),
        )
        with mock.patch.object(
            coordinator_module,
            "_GRITLOCK_SETTLE_TIME",
            0.001,
        ):
            await entity.async_lock()

        self.assertEqual(api.gritlock_calls, [True])
        self.assertIs(entity.is_locked, True)

    async def test_fresh_opposite_observation_fails_and_is_displayed(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        await self.settle(instance, (("trigger-one", 0, 1),))

        api.command_hook = lambda _locked: self.emit(
            instance,
            (("trigger-one", 0, 0),),
        )
        with (
            mock.patch.object(
                coordinator_module,
                "_GRITLOCK_SETTLE_TIME",
                0.001,
            ),
            self.assertRaisesRegex(
                entity_tests.HomeAssistantError,
                "could not be confirmed",
            ),
        ):
            await entity.async_lock()

        self.assertEqual(api.gritlock_calls, [True])
        self.assertIs(entity.is_locked, False)
        self.assertTrue(entity.available)

    async def test_rest_failure_preserves_observed_state(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        await self.settle(instance, (("trigger-one", 0, 0),))
        observation = instance._gritlock_state_observation
        api.command_error = True

        with self.assertRaisesRegex(
            entity_tests.HomeAssistantError,
            "could not be confirmed",
        ):
            await entity.async_lock()

        self.assertEqual(api.gritlock_calls, [True])
        self.assertIs(instance._gritlock_state_observation, observation)
        self.assertIs(entity.is_locked, False)

    async def test_entity_command_cancellation_propagates(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        api = PipelineApi()
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        entity = LOCK_MODULE.GritHubSystemLock(instance)
        await self.settle(instance, (("trigger-one", 0, 0),))
        observation = instance._gritlock_state_observation

        command = asyncio.create_task(entity.async_lock())
        for _attempt in range(20):
            if instance._mqtt_state_waiters:
                break
            await asyncio.sleep(0)
        self.assertTrue(instance._mqtt_state_waiters)
        command.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await command

        self.assertEqual(api.gritlock_calls, [True])
        self.assertIs(instance._gritlock_state_observation, observation)
        self.assertEqual(instance._mqtt_state_waiters, set())
    async def test_rest_refresh_cannot_replace_settled_unlocked_state(self):
        devices = coordinator_tests._device_map()
        devices["trigger"] = [
            {"id": "trigger-one", "gritLockEnabled": False}
        ]
        api = PipelineApi(
            {
                "trigger": [
                    {
                        "id": "trigger-one",
                        "gritLockEnabled": True,
                        "gritLockState": True,
                    }
                ]
            }
        )
        instance = self.coordinator(devices, api)
        instance.set_mqtt_connected(True)
        await self.settle(instance, (("trigger-one", 0, 0),))
        self.assertFalse(instance.gritlock_state)

        instance.data = await instance._async_update_data()

        self.assertFalse(instance.gritlock_state)


if __name__ == "__main__":
    unittest.main()
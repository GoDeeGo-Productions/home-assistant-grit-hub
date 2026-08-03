"""Network-free tests for Home Assistant entities backed by sanitized MQTT state."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import IntFlag
import importlib.util
import logging
from pathlib import Path
import socket
import sys
import types
from typing import Any, Callable
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
ENTRY_ID = "entry-fabricated"
GATE_ID = "gate-fabricated"
SWITCH_ID = "switch-fabricated"
MQTT_STATE_KEY = "_grit_mqtt"
HUB_ID = "0123456789abcdef0123456789abcdef"
HUB_IP = "192.0.2.44"


class DeviceInfo(dict):
    """Small DeviceInfo stand-in."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(kwargs)


class CoordinatorEntity:
    """CoordinatorEntity stand-in with Home Assistant-like availability."""

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class CoverEntity:
    @property
    def is_opening(self):
        return None

    @property
    def is_closing(self):
        return None


class CoverEntityFeature(IntFlag):
    OPEN = 1
    CLOSE = 2


class SwitchEntity:
    pass


class SensorEntity:
    pass


class SensorDeviceClass:
    SIGNAL_STRENGTH = "signal_strength"
    TIMESTAMP = "timestamp"


class BinarySensorEntity:
    pass


class BinarySensorDeviceClass:
    CONNECTIVITY = "connectivity"


class ButtonEntity:
    pass


class NumberEntity:
    pass


class NumberMode:
    SLIDER = "slider"


class LockEntity:
    pass


class EntityCategory:
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class HomeAssistantError(Exception):
    pass


class GritHubApiError(Exception):
    pass


def obj_id(obj: dict[str, Any]) -> str | int | None:
    for key in ("id", "deviceId", "deviceID", "_id", "uuid", "key"):
        if obj.get(key) not in (None, ""):
            return obj[key]
    return None


def obj_name(obj: dict[str, Any], fallback: str) -> str:
    for key in (
        "name",
        "displayName",
        "label",
        "description",
        "serialNumber",
        "deviceName",
    ):
        if obj.get(key):
            return str(obj[key])
    ident = obj_id(obj)
    return f"{fallback} {ident}" if ident is not None else fallback


def bool_state(obj: dict[str, Any]) -> bool | None:
    for key in (
        "on",
        "onOff",
        "enabled",
        "active",
        "open",
        "locked",
        "state",
        "status",
        "isOn",
    ):
        if key not in obj:
            continue
        value = obj[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {
                "on",
                "open",
                "enabled",
                "active",
                "true",
                "1",
                "unlocked",
                "online",
            }:
                return True
            if lowered in {
                "off",
                "closed",
                "disabled",
                "inactive",
                "false",
                "0",
                "locked",
                "offline",
            }:
                return False
    return None


def _install_home_assistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")

    cover = types.ModuleType("homeassistant.components.cover")
    cover.CoverEntity = CoverEntity
    cover.CoverEntityFeature = CoverEntityFeature
    switch = types.ModuleType("homeassistant.components.switch")
    switch.SwitchEntity = SwitchEntity
    sensor = types.ModuleType("homeassistant.components.sensor")
    sensor.SensorEntity = SensorEntity
    sensor.SensorDeviceClass = SensorDeviceClass
    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    binary_sensor.BinarySensorEntity = BinarySensorEntity
    binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    button = types.ModuleType("homeassistant.components.button")
    button.ButtonEntity = ButtonEntity
    number = types.ModuleType("homeassistant.components.number")
    number.NumberEntity = NumberEntity
    number.NumberMode = NumberMode
    lock = types.ModuleType("homeassistant.components.lock")
    lock.LockEntity = LockEntity
    const = types.ModuleType("homeassistant.const")
    const.EntityCategory = EntityCategory
    const.PERCENTAGE = "%"
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = HomeAssistantError
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = DeviceInfo
    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    homeassistant.components = components
    homeassistant.helpers = helpers
    components.cover = cover
    components.switch = switch
    components.sensor = sensor
    components.binary_sensor = binary_sensor
    components.button = button
    components.number = number
    components.lock = lock
    helpers.device_registry = device_registry
    helpers.update_coordinator = update_coordinator

    for module in (
        homeassistant,
        components,
        helpers,
        cover,
        switch,
        sensor,
        binary_sensor,
        button,
        number,
        lock,
        const,
        exceptions,
        device_registry,
        update_coordinator,
    ):
        sys.modules[module.__name__] = module


def _load_modules() -> dict[str, types.ModuleType]:
    _install_home_assistant_stubs()
    package_name = "_grit_entity_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules[package_name] = package

    api_module = types.ModuleType(f"{package_name}.api")
    api_module.GritHubApiError = GritHubApiError
    api_module.bool_state = bool_state
    api_module.obj_id = obj_id
    api_module.obj_name = obj_name
    sys.modules[api_module.__name__] = api_module

    coordinator_module = types.ModuleType(f"{package_name}.coordinator")
    coordinator_module.MQTT_STATE_KEY = MQTT_STATE_KEY
    sys.modules[coordinator_module.__name__] = coordinator_module

    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", COMPONENT_ROOT / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)

    loaded: dict[str, types.ModuleType] = {"const": const_module}
    for name in (
        "entity",
        "cover",
        "switch",
        "sensor",
        "binary_sensor",
        "button",
        "number",
        "lock",
    ):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}", COMPONENT_ROOT / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        loaded[name] = module
    return loaded


MODULES = _load_modules()
ENTITY_MODULE = MODULES["entity"]
COVER_MODULE = MODULES["cover"]
SWITCH_MODULE = MODULES["switch"]
SENSOR_MODULE = MODULES["sensor"]
BINARY_SENSOR_MODULE = MODULES["binary_sensor"]
BUTTON_MODULE = MODULES["button"]
NUMBER_MODULE = MODULES["number"]
LOCK_MODULE = MODULES["lock"]
CONST_MODULE = MODULES["const"]


class FakeApi:
    """Physical-command tripwire; every command would fail the test."""

    def __init__(self) -> None:
        self.command_calls = 0
        self.hub_calls: list[tuple[Any, ...]] = []

    async def set_device_state(self, *_args: Any, **_kwargs: Any) -> None:
        self.command_calls += 1
        raise AssertionError("physical device command is forbidden")

    async def set_gritlock(self, locked: bool) -> None:
        self.hub_calls.append(("set_gritlock", locked))

    async def set_system_led_brightness(
        self,
        hub_id: str,
        brightness: int,
    ) -> None:
        self.hub_calls.append(("set_led", hub_id, brightness))

    async def restart_service(self) -> None:
        self.hub_calls.append(("restart_service",))

    async def reboot_hub(self) -> None:
        self.hub_calls.append(("reboot_hub",))


class FakeCoordinator:
    def __init__(self, devices: dict[str, list[dict[str, Any]]]) -> None:
        self.data = {
            "devices": devices,
            "hub": {
                "id": HUB_ID,
                "displayName": "Fabricated Hub",
                "hubVersion": "1.2.3-test",
                "ipAddressEthernet": HUB_IP,
                "connectedToInternet": True,
                "branch": "fabricated-branch",
                "systemLedBrightness": 42,
                "disableHubButtons": False,
            },
        }
        self.last_update_success = True
        self.mqtt_connected = True
        self.api = FakeApi()
        self.listener_updates = 0
        self.gritlock_state_value: bool | None = None
        self.gritlock_participating_trigger_ids = frozenset({"trigger-test"})
        self.refresh_hook: Callable[[], None] | None = None
        self.refresh_block: asyncio.Event | None = None
        self.refresh_calls = 0
        self.refresh_sequence = 1
        self.hub_update_sequence = 1
        self.gritlock_update_sequence = 1
        self.mqtt_receive_sequence = 0
        self.confirmation_hook: (
            Callable[[str, str, bool], bool] | None
        ) = None
        self.confirmation_block: asyncio.Event | None = None
        self.confirmation_calls: list[tuple[str, str, bool, int, float]] = []
        self.rfid_confirmation_hook: Callable[[str, bool], bool] | None = None
        self.rfid_confirmation_block: asyncio.Event | None = None
        self.rfid_confirmation_calls: list[tuple[str, bool, int, float]] = []
        self.gritlock_confirmation_hook: Callable[[bool], bool] | None = None
        self.gritlock_confirmation_block: asyncio.Event | None = None
        self.gritlock_confirmation_calls: list[tuple[bool, int, float]] = []
        self.gritlock_generation_sequence = 0
        self.gritlock_generation_calls: list[int] = []
        self.gritlock_cancel_calls: list[int] = []

    @property
    def hub_data(self) -> dict[str, Any]:
        hub = self.data.get("hub")
        return hub if isinstance(hub, dict) else {}

    @property
    def hub_id(self) -> str | None:
        value = self.hub_data.get("id")
        return value if isinstance(value, str) else None

    @property
    def gritlock_state(self) -> bool | None:
        return self.gritlock_state_value

    async def async_request_refresh(self) -> None:
        self.refresh_calls += 1
        self.refresh_sequence += 1
        if self.refresh_block is not None:
            await self.refresh_block.wait()
        if self.refresh_hook is None:
            raise AssertionError(
                "unexpected REST refresh in entity state test"
            )
        self.refresh_hook()


    async def async_confirm_device_state(
        self,
        device_type: str,
        device_id: Any,
        expected: bool,
        *,
        after_sequence: int,
        timeout: float,
    ) -> bool:
        self.confirmation_calls.append(
            (
                device_type,
                str(device_id),
                expected,
                after_sequence,
                timeout,
            )
        )
        if self.confirmation_block is not None:
            try:
                await asyncio.wait_for(
                    self.confirmation_block.wait(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return False
        if self.confirmation_hook is None:
            return False
        self.mqtt_receive_sequence += 1
        return self.confirmation_hook(
            device_type,
            str(device_id),
            expected,
        )

    def _rfid_record(self, device_id: Any) -> dict[str, Any] | None:
        matches = [
            device
            for device in self.data["devices"].get("rfid", [])
            if isinstance(device, dict)
            and str(device.get("id")).strip() == str(device_id).strip()
        ]
        return matches[0] if len(matches) == 1 else None

    def rfid_enabled(self, device_id: Any) -> bool | None:
        record = self._rfid_record(device_id)
        enabled = record.get("_grit_rfid_enabled") if record else None
        return enabled if isinstance(enabled, bool) else None

    def rfid_state_generation(self, device_id: Any) -> int:
        record = self._rfid_record(device_id)
        generation = (
            record.get("_grit_rfid_state_generation") if record else None
        )
        return generation if isinstance(generation, int) else 0

    async def async_confirm_rfid_state(
        self,
        device_id: Any,
        expected_enabled: bool,
        *,
        after_generation: int,
        timeout: float,
    ) -> bool:
        normalized_id = str(device_id)
        self.rfid_confirmation_calls.append(
            (normalized_id, expected_enabled, after_generation, timeout)
        )
        if self.rfid_confirmation_block is not None:
            try:
                await asyncio.wait_for(
                    self.rfid_confirmation_block.wait(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return False
        if self.rfid_confirmation_hook is None:
            return False
        return self.rfid_confirmation_hook(normalized_id, expected_enabled)
    def begin_gritlock_generation(self, after_sequence: int) -> int | None:
        if not self.mqtt_connected or after_sequence != self.mqtt_receive_sequence:
            return None
        self.gritlock_generation_sequence += 1
        self.gritlock_generation_calls.append(after_sequence)
        return self.gritlock_generation_sequence

    def cancel_gritlock_generation(self, generation_id: int) -> bool:
        self.gritlock_cancel_calls.append(generation_id)
        return True

    async def async_confirm_gritlock_state(
        self,
        expected: bool,
        *,
        generation_id: int,
        timeout: float,
    ) -> bool:
        self.gritlock_confirmation_calls.append(
            (expected, generation_id, timeout)
        )
        if self.gritlock_confirmation_block is not None:
            try:
                await asyncio.wait_for(
                    self.gritlock_confirmation_block.wait(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return False
        if self.gritlock_confirmation_hook is None:
            return False
        self.mqtt_receive_sequence += 1
        return self.gritlock_confirmation_hook(expected)

    def set_mqtt_connected(self, connected: bool) -> bool:

        if self.mqtt_connected == connected:
            return False
        self.mqtt_connected = connected
        self.listener_updates += 1
        return True


class FakeHass:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.data = {
            CONST_MODULE.DOMAIN: {
                ENTRY_ID: {"coordinator": coordinator},
            }
        }


class FakeEntry:
    entry_id = ENTRY_ID


class EntityMqttTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
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
        create_connection_patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_patch.start()
        connect_ex_patch.start()
        create_connection_patch.start()
        self.addCleanup(connect_patch.stop)
        self.addCleanup(connect_ex_patch.stop)
        self.addCleanup(create_connection_patch.stop)

        self.gate = {
            "id": GATE_ID,
            "name": "Fabricated Gate",
            "open": False,
            "position": 20,
        }
        self.switch_device = {
            "id": SWITCH_ID,
            "name": "Fabricated Switch",
            "state": "off",
        }
        devices = {
            device_type: [] for device_type in CONST_MODULE.DEVICE_TYPES
        }
        devices["gate"] = [self.gate]
        devices["solenoid"] = [self.switch_device]
        self.coordinator = FakeCoordinator(devices)
        self.hass = FakeHass(self.coordinator)
        self.entry = FakeEntry()

    def tearDown(self) -> None:
        self.assertEqual(self.coordinator.api.command_calls, 0)

    @staticmethod
    def run_setup(module: types.ModuleType, hass: FakeHass, entry: FakeEntry):
        calls: list[list[Any]] = []
        coroutine = module.async_setup_entry(
            hass,
            entry,
            lambda entities: calls.append(list(entities)),
        )
        try:
            coroutine.send(None)
        except StopIteration:
            pass
        else:
            coroutine.close()
            raise AssertionError("entity setup unexpectedly suspended")
        if len(calls) != 1:
            raise AssertionError("entity setup did not add entities exactly once")
        return calls[0]

    def gate_cover(self):
        return COVER_MODULE.GritHubGateCover(
            self.coordinator, "gate", self.gate
        )

    def device_switch(self):
        return SWITCH_MODULE.GritHubDeviceSwitch(
            self.coordinator, "solenoid", self.switch_device
        )

    def test_rfid_is_only_a_lock_and_system_gritlock_is_unique(self):
        rfid = {
            "id": "rfid-platform-test",
            "name": "Fabricated RFID reader",
        }
        self.coordinator.data["devices"]["rfid"] = [rfid]

        switches = self.run_setup(
            SWITCH_MODULE,
            self.hass,
            self.entry,
        )
        locks = self.run_setup(LOCK_MODULE, self.hass, self.entry)

        self.assertFalse(
            any(entity.device_type == "rfid" for entity in switches)
        )
        rfid_locks = [
            entity
            for entity in locks
            if isinstance(entity, LOCK_MODULE.GritHubRfidLock)
        ]
        system_locks = [
            entity
            for entity in locks
            if isinstance(entity, LOCK_MODULE.GritHubSystemLock)
        ]
        self.assertEqual(len(rfid_locks), 1)
        self.assertEqual(len(system_locks), 1)

    def test_duplicate_rfid_identifiers_create_no_lock_entities(self):
        self.coordinator.data["devices"]["rfid"] = [
            {"id": "duplicate-reader", "name": "Reader A"},
            {"id": "duplicate-reader", "name": "Reader B"},
            {"name": "Missing identity"},
        ]

        locks = self.run_setup(LOCK_MODULE, self.hass, self.entry)
        rfid_locks = [
            entity
            for entity in locks
            if isinstance(entity, LOCK_MODULE.GritHubRfidLock)
        ]

        self.assertEqual(rfid_locks, [])
        self.assertEqual(
            len(
                [
                    entity
                    for entity in locks
                    if isinstance(entity, LOCK_MODULE.GritHubSystemLock)
                ]
            ),
            1,
        )
    def test_mqtt_connectivity_sensor_tracks_broker_and_stays_available(self):
        sensor = BINARY_SENSOR_MODULE.GritHubMqttConnectionBinarySensor(
            self.coordinator, ENTRY_ID
        )
        self.coordinator.last_update_success = False
        self.coordinator.mqtt_connected = False
        self.assertTrue(sensor.available)
        self.assertFalse(sensor.is_on)
        self.coordinator.mqtt_connected = True
        self.assertTrue(sensor.available)
        self.assertTrue(sensor.is_on)
        self.assertTrue(sensor._attr_unique_id.endswith("_mqtt_connected"))

    def test_duplicate_connection_updates_do_not_recreate_entities(self):
        entities = self.run_setup(BINARY_SENSOR_MODULE, self.hass, self.entry)
        mqtt_sensor = next(
            entity
            for entity in entities
            if isinstance(
                entity,
                BINARY_SENSOR_MODULE.GritHubMqttConnectionBinarySensor,
            )
        )
        entity_ids = tuple(id(entity) for entity in entities)
        self.assertTrue(self.coordinator.set_mqtt_connected(False))
        self.assertFalse(mqtt_sensor.is_on)
        self.assertFalse(self.coordinator.set_mqtt_connected(False))
        self.assertTrue(self.coordinator.set_mqtt_connected(True))
        self.assertTrue(mqtt_sensor.is_on)
        self.assertEqual(tuple(id(entity) for entity in entities), entity_ids)

    def test_cover_uses_strict_mqtt_position_and_open_state(self):
        self.gate[MQTT_STATE_KEY] = {
            "position": 87.6,
            "open": True,
            "online": True,
        }
        cover = self.gate_cover()
        self.assertEqual(cover.current_cover_position, 88)
        self.assertFalse(cover.is_closed)
        self.gate[MQTT_STATE_KEY]["open"] = False
        self.assertTrue(cover.is_closed)
        self.gate[MQTT_STATE_KEY]["position"] = 101
        self.assertIsNone(cover.current_cover_position)

    def test_cover_ignores_unproven_rest_state_before_mqtt(self):
        cover = self.gate_cover()
        self.assertIsNone(cover.current_cover_position)
        self.assertIsNone(cover.is_closed)
        self.gate["state"] = False
        self.assertNotIn("state", cover.extra_state_attributes)
        self.gate[MQTT_STATE_KEY] = {"open": "open", "position": "80"}
        self.assertIsNone(cover.current_cover_position)
        self.assertIsNone(cover.is_closed)

    def test_cover_does_not_infer_movement(self):
        self.gate[MQTT_STATE_KEY] = {
            "position": 60,
            "open": True,
            "movement": "opening",
        }
        cover = self.gate_cover()
        self.assertIsNone(cover.is_opening)
        self.assertIsNone(cover.is_closing)

    def test_cover_availability_preserves_last_state(self):
        self.gate[MQTT_STATE_KEY] = {"position": 90, "open": True}
        cover = self.gate_cover()
        self.assertTrue(cover.available)
        self.coordinator.mqtt_connected = False
        self.assertFalse(cover.available)
        self.assertEqual(cover.current_cover_position, 90)
        self.assertFalse(cover.is_closed)
        self.coordinator.mqtt_connected = True
        self.assertTrue(cover.available)
        self.gate[MQTT_STATE_KEY]["online"] = False
        self.assertFalse(cover.available)
        self.gate[MQTT_STATE_KEY].pop("online")
        self.assertTrue(cover.available)
        self.coordinator.last_update_success = False
        self.assertFalse(cover.available)

    def test_switch_uses_only_strict_sanitized_boolean_state(self):
        switch = self.device_switch()
        self.assertFalse(switch.is_on)
        self.switch_device[MQTT_STATE_KEY] = {"state": True, "online": True}
        self.assertTrue(switch.is_on)
        self.switch_device[MQTT_STATE_KEY]["state"] = False
        self.assertFalse(switch.is_on)
        self.switch_device[MQTT_STATE_KEY]["state"] = "on"
        self.assertIsNone(switch.is_on)

    def test_rfid_lock_uses_only_individual_rest_enabled_state(self):
        rfid = {
            "id": "rfid-fabricated",
            "name": "Fabricated RFID reader",
            "lockout": False,
            "_grit_rfid_enabled": False,
            "_grit_rfid_state_generation": 1,
            MQTT_STATE_KEY: {"locked": False, "online": True},
        }
        self.coordinator.data["devices"]["rfid"].append(rfid)
        entity = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )

        self.assertTrue(entity.is_locked)
        self.assertNotIn("lockout", entity.extra_state_attributes)
        self.assertNotIn("state", entity.extra_state_attributes)

        rfid["lockout"] = True
        rfid[MQTT_STATE_KEY]["locked"] = True
        self.assertTrue(entity.is_locked)

        rfid["_grit_rfid_enabled"] = True
        self.assertFalse(entity.is_locked)
    def test_offline_rfid_is_unavailable_without_fabricating_state(self):
        rfid = {
            "id": "rfid-offline",
            "name": "Fabricated offline reader",
            "onlineStatus": False,
            "_grit_rfid_enabled": True,
            "_grit_rfid_state_generation": 1,
        }
        self.coordinator.data["devices"]["rfid"] = [rfid]
        entity = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )

        self.assertFalse(entity.available)
        self.assertFalse(entity.is_locked)
        rfid.pop("_grit_rfid_enabled")
        rfid.pop("_grit_rfid_state_generation")
        self.assertIsNone(entity.is_locked)
        self.assertFalse(entity.available)
    def test_unknown_gate_and_rfid_state_remain_unknown(self):
        gate = {"id": "gate-unknown", "name": "Unknown gate"}
        rfid = {"id": "rfid-unknown", "name": "Unknown RFID reader"}
        self.coordinator.data["devices"]["gate"] = [gate]
        self.coordinator.data["devices"]["rfid"] = [rfid]

        cover = COVER_MODULE.GritHubGateCover(
            self.coordinator,
            "gate",
            gate,
        )
        rfid_lock = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )

        self.assertIsNone(cover.current_cover_position)
        self.assertIsNone(cover.is_closed)
        self.assertIsNone(rfid_lock.is_locked)

    def test_mocked_gate_and_rfid_commands_require_fresh_confirmed_state(self):
        rfid = {
            "id": "rfid-fabricated",
            "name": "Fabricated RFID reader",
        }
        self.coordinator.data["devices"]["rfid"].append(rfid)
        cover = self.gate_cover()
        rfid_lock = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )
        command = mock.AsyncMock()

        def confirm_mqtt(
            device_type: str,
            _device_id: str,
            expected: bool,
        ) -> bool:
            self.assertEqual(device_type, "gate")
            self.gate[MQTT_STATE_KEY] = {
                "open": expected,
                "position": 100 if expected else 0,
            }
            return True

        def confirm_rfid(_device_id: str, expected_enabled: bool) -> bool:
            rfid["_grit_rfid_enabled"] = expected_enabled
            rfid["_grit_rfid_state_generation"] = (
                rfid.get("_grit_rfid_state_generation", 0) + 1
            )
            return True

        self.coordinator.confirmation_hook = confirm_mqtt
        self.coordinator.rfid_confirmation_hook = confirm_rfid
        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ):
            self.loop.run_until_complete(cover.async_open_cover())
            command.assert_awaited_once_with("gate", GATE_ID, True)
            self.assertFalse(cover.is_closed)
            self.assertEqual(cover.current_cover_position, 100)

            command.reset_mock()
            self.loop.run_until_complete(rfid_lock.async_unlock())
            command.assert_awaited_once_with(
                "rfid",
                "rfid-fabricated",
                True,
            )
            self.assertFalse(rfid_lock.is_locked)

            command.reset_mock()
            self.loop.run_until_complete(rfid_lock.async_lock())
            command.assert_awaited_once_with(
                "rfid",
                "rfid-fabricated",
                False,
            )
            self.assertTrue(rfid_lock.is_locked)

        self.assertEqual(self.coordinator.refresh_calls, 0)
        self.assertEqual(
            [call[:4] for call in self.coordinator.confirmation_calls],
            [("gate", GATE_ID, True, 0)],
        )
        self.assertEqual(
            self.coordinator.rfid_confirmation_calls,
            [
                (
                    "rfid-fabricated",
                    True,
                    0,
                    LOCK_MODULE.DEVICE_CONFIRM_TIMEOUT,
                ),
                (
                    "rfid-fabricated",
                    False,
                    1,
                    LOCK_MODULE.DEVICE_CONFIRM_TIMEOUT,
                ),
            ],
        )
    def test_rfid_captures_rest_generation_before_command(self):
        rfid = {
            "id": "rfid-boundary-test",
            "name": "Fabricated RFID reader",
        }
        self.coordinator.data["devices"]["rfid"] = [rfid]
        entity = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )

        async def command_with_interleaved_rest(*_args: Any) -> None:
            rfid["_grit_rfid_enabled"] = False
            rfid["_grit_rfid_state_generation"] = 1

        def confirm(_device_id: str, expected_enabled: bool) -> bool:
            rfid["_grit_rfid_enabled"] = expected_enabled
            rfid["_grit_rfid_state_generation"] = 2
            return True

        self.coordinator.rfid_confirmation_hook = confirm
        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            side_effect=command_with_interleaved_rest,
        ):
            self.loop.run_until_complete(entity.async_unlock())

        self.assertEqual(
            self.coordinator.rfid_confirmation_calls,
            [
                (
                    "rfid-boundary-test",
                    True,
                    0,
                    LOCK_MODULE.DEVICE_CONFIRM_TIMEOUT,
                )
            ],
        )
        self.assertFalse(entity.is_locked)
    def test_gate_and_rfid_commands_fail_when_state_is_unconfirmed(self):
        rfid = {
            "id": "rfid-fabricated",
            "name": "Fabricated RFID reader",
            "state": False,
        }
        self.coordinator.data["devices"]["rfid"].append(rfid)
        cover = self.gate_cover()
        rfid_lock = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )
        command = mock.AsyncMock()

        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ):
            with self.assertRaisesRegex(
                HomeAssistantError,
                "Gate state could not be confirmed",
            ):
                self.loop.run_until_complete(cover.async_open_cover())
            self.assertIsNone(cover.is_closed)

            command.reset_mock()
            with self.assertRaisesRegex(
                HomeAssistantError,
                "RFID state could not be confirmed",
            ):
                self.loop.run_until_complete(rfid_lock.async_unlock())
            self.assertIsNone(rfid_lock.is_locked)

            command.reset_mock()
            with self.assertRaisesRegex(
                HomeAssistantError,
                "Gate state could not be confirmed",
            ):
                self.loop.run_until_complete(cover.async_open_cover())
            command.assert_awaited_once_with("gate", GATE_ID, True)

    def test_rfid_command_uses_rest_confirmation_without_mqtt(self):
        rfid = {
            "id": "rfid-fabricated",
            "name": "Fabricated RFID reader",
        }
        self.coordinator.data["devices"]["rfid"].append(rfid)
        self.coordinator.mqtt_connected = False
        cover = self.gate_cover()
        rfid_lock = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )
        command = mock.AsyncMock()

        def confirm_rfid(_device_id: str, expected_enabled: bool) -> bool:
            rfid["_grit_rfid_enabled"] = expected_enabled
            rfid["_grit_rfid_state_generation"] = 1
            return True

        self.coordinator.rfid_confirmation_hook = confirm_rfid
        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ):
            with self.assertRaisesRegex(
                HomeAssistantError,
                "Gate state could not be confirmed",
            ):
                self.loop.run_until_complete(cover.async_open_cover())
            self.loop.run_until_complete(rfid_lock.async_unlock())

        command.assert_awaited_once_with(
            "rfid",
            "rfid-fabricated",
            True,
        )
        self.assertEqual(self.coordinator.confirmation_calls, [])
        self.assertEqual(
            self.coordinator.rfid_confirmation_calls,
            [
                (
                    "rfid-fabricated",
                    True,
                    0,
                    LOCK_MODULE.DEVICE_CONFIRM_TIMEOUT,
                )
            ],
        )
        self.assertFalse(rfid_lock.is_locked)
    def test_mqtt_observed_during_command_cannot_confirm_gate(self):
        cover = self.gate_cover()

        async def command_with_interleaved_mqtt(*_args: Any) -> None:
            self.coordinator.mqtt_receive_sequence += 1
            self.gate[MQTT_STATE_KEY] = {
                "open": True,
                "position": 100,
            }

        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            side_effect=command_with_interleaved_mqtt,
        ):
            with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
                self.loop.run_until_complete(cover.async_open_cover())

        self.assertEqual(
            self.coordinator.confirmation_calls,
            [("gate", GATE_ID, True, 1, COVER_MODULE.DEVICE_CONFIRM_TIMEOUT)],
        )

    def test_non_rfid_stale_mqtt_cannot_confirm_rest_command(self):
        switch = self.device_switch()
        self.switch_device[MQTT_STATE_KEY] = {"state": True}
        command = mock.AsyncMock()

        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ):
            self.coordinator.refresh_hook = lambda: None
            with self.assertRaisesRegex(
                HomeAssistantError,
                "Device state could not be confirmed",
            ):
                self.loop.run_until_complete(switch.async_turn_on())

        command.assert_awaited_once_with("solenoid", SWITCH_ID, True)

    def test_matching_stale_state_cannot_confirm_command(self):
        self.gate[MQTT_STATE_KEY] = {"open": False, "position": 20}
        cover = self.gate_cover()
        switch = self.device_switch()
        command = mock.AsyncMock()
        no_refresh = mock.AsyncMock()

        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ), mock.patch.object(
            self.coordinator,
            "async_request_refresh",
            no_refresh,
        ):
            with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
                self.loop.run_until_complete(cover.async_close_cover())
            with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
                self.loop.run_until_complete(switch.async_turn_off())

        no_refresh.assert_awaited_once_with()
        self.assertTrue(cover.is_closed)
        self.assertEqual(cover.current_cover_position, 20)

    def test_gate_command_is_not_optimistic_while_confirmation_is_pending(self):
        self.gate[MQTT_STATE_KEY] = {"open": False, "position": 20}
        cover = self.gate_cover()
        command = mock.AsyncMock()
        self.coordinator.confirmation_block = asyncio.Event()

        def confirm_gate(_type: str, _ident: str, expected: bool) -> bool:
            self.gate[MQTT_STATE_KEY] = {
                "open": expected,
                "position": 100,
            }
            return True

        self.coordinator.confirmation_hook = confirm_gate
        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ):
            task = self.loop.create_task(cover.async_open_cover())
            self.loop.run_until_complete(asyncio.sleep(0))
            self.assertFalse(task.done())
            self.assertTrue(cover.is_closed)
            self.assertEqual(cover.current_cover_position, 20)

            self.coordinator.confirmation_block.set()
            self.loop.run_until_complete(task)

        self.assertFalse(cover.is_closed)
        self.assertEqual(cover.current_cover_position, 100)

    def test_gate_and_rfid_confirmation_timeout_is_generic(self):
        rfid = {
            "id": "rfid-fabricated",
            "name": "Fabricated RFID reader",
            "state": False,
        }
        self.coordinator.data["devices"]["rfid"].append(rfid)
        cover = self.gate_cover()
        rfid_lock = LOCK_MODULE.GritHubRfidLock(
            self.coordinator,
            "rfid",
            rfid,
        )
        command = mock.AsyncMock()
        private_detail = "fabricated-private-command-detail"

        with mock.patch.object(
            self.coordinator.api,
            "set_device_state",
            command,
        ):
            self.coordinator.confirmation_block = asyncio.Event()
            with mock.patch.object(
                COVER_MODULE,
                "DEVICE_CONFIRM_TIMEOUT",
                0.01,
            ), self.assertRaises(HomeAssistantError) as gate_error:
                self.loop.run_until_complete(cover.async_open_cover())
            self.assertEqual(
                str(gate_error.exception),
                "Gate state could not be confirmed",
            )

            self.coordinator.confirmation_block = None
            command.side_effect = RuntimeError(
                private_detail
            )
            with self.assertRaises(HomeAssistantError) as rfid_error:
                self.loop.run_until_complete(rfid_lock.async_unlock())
            self.assertEqual(
                str(rfid_error.exception),
                "RFID state could not be confirmed",
            )
            self.assertNotIn(private_detail, str(rfid_error.exception))

    def test_switch_uses_conservative_availability(self):
        self.switch_device[MQTT_STATE_KEY] = {"state": True}
        switch = self.device_switch()
        self.assertTrue(switch.available)
        self.coordinator.mqtt_connected = False
        self.assertFalse(switch.available)
        self.assertTrue(switch.is_on)
        self.coordinator.mqtt_connected = True
        self.switch_device[MQTT_STATE_KEY]["online"] = False
        self.assertFalse(switch.available)
        self.switch_device[MQTT_STATE_KEY].pop("online")
        self.assertTrue(switch.available)
        self.coordinator.last_update_success = False
        self.assertFalse(switch.available)

    def test_per_device_online_binary_sensor(self):
        sensor = BINARY_SENSOR_MODULE.GritHubDeviceMqttOnlineBinarySensor(
            self.coordinator,
            ENTRY_ID,
            "gate",
            self.gate,
        )
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.is_on)
        self.gate[MQTT_STATE_KEY] = {"online": False}
        self.assertTrue(sensor.available)
        self.assertFalse(sensor.is_on)
        self.gate[MQTT_STATE_KEY]["online"] = True
        self.assertTrue(sensor.is_on)
        self.assertTrue(sensor._attr_unique_id.endswith("_mqtt_online"))

    def test_rssi_firmware_and_timestamp_diagnostics(self):
        received_at = datetime(2026, 8, 3, 1, 2, 3, tzinfo=timezone.utc)
        self.gate[MQTT_STATE_KEY] = {
            "rssi": -64,
            "firmware_version": "v1.2.3",
            "last_received_at": received_at,
        }
        rssi = SENSOR_MODULE.GritHubMqttRssiSensor(
            self.coordinator, ENTRY_ID, "gate", self.gate
        )
        firmware = SENSOR_MODULE.GritHubMqttFirmwareSensor(
            self.coordinator, ENTRY_ID, "gate", self.gate
        )
        last_received = SENSOR_MODULE.GritHubMqttLastReceivedSensor(
            self.coordinator, ENTRY_ID, "gate", self.gate
        )
        self.assertEqual(rssi.native_value, -64)
        self.assertEqual(rssi._attr_native_unit_of_measurement, "dBm")
        self.assertTrue(rssi.available)
        self.assertEqual(firmware.native_value, "v1.2.3")
        self.assertTrue(firmware.available)
        self.assertIs(last_received.native_value, received_at)
        self.assertIsNotNone(last_received.native_value.utcoffset())
        self.assertTrue(last_received.available)

    def test_missing_or_wrong_diagnostic_values_are_unavailable(self):
        rssi = SENSOR_MODULE.GritHubMqttRssiSensor(
            self.coordinator, ENTRY_ID, "gate", self.gate
        )
        firmware = SENSOR_MODULE.GritHubMqttFirmwareSensor(
            self.coordinator, ENTRY_ID, "gate", self.gate
        )
        last_received = SENSOR_MODULE.GritHubMqttLastReceivedSensor(
            self.coordinator, ENTRY_ID, "gate", self.gate
        )
        for entity in (rssi, firmware, last_received):
            self.assertFalse(entity.available)
            self.assertIsNone(entity.native_value)

        self.gate[MQTT_STATE_KEY] = {
            "rssi": True,
            "firmware_version": 123,
            "last_received_at": datetime(2026, 8, 3, 1, 2, 3),
        }
        for entity in (rssi, firmware, last_received):
            self.assertFalse(entity.available)
            self.assertIsNone(entity.native_value)

    def test_diagnostics_are_created_once_with_stable_non_topic_ids(self):
        sensor_entities = self.run_setup(SENSOR_MODULE, self.hass, self.entry)
        binary_entities = self.run_setup(
            BINARY_SENSOR_MODULE, self.hass, self.entry
        )
        diagnostic_ids = [
            entity._attr_unique_id
            for entity in sensor_entities + binary_entities
            if "_mqtt_" in entity._attr_unique_id
        ]
        self.assertEqual(len(diagnostic_ids), 9)
        self.assertEqual(len(diagnostic_ids), len(set(diagnostic_ids)))
        for unique_id in diagnostic_ids:
            self.assertIn(ENTRY_ID, unique_id)
            self.assertNotIn("grit/", unique_id)

    def test_hub_device_identity_and_metadata_are_stable(self):
        entity = SENSOR_MODULE.GritHubIpAddressSensor(self.coordinator)
        original = entity.device_info
        self.assertEqual(
            original["identifiers"],
            {(CONST_MODULE.DOMAIN, "hub")},
        )
        self.assertEqual(original["name"], "Fabricated Hub")
        self.assertEqual(original["sw_version"], "1.2.3-test")

        self.coordinator.data["hub"]["id"] = (
            "fedcba9876543210fedcba9876543210"
        )
        self.coordinator.data["hub"]["displayName"] = "Renamed Hub"
        self.coordinator.data["hub"]["hubVersion"] = "2.0-test"
        updated = entity.device_info
        self.assertEqual(updated["identifiers"], original["identifiers"])
        self.assertEqual(updated["name"], "Renamed Hub")
        self.assertEqual(updated["sw_version"], "2.0-test")

    def test_core_hub_diagnostics_use_only_sanitized_fields(self):
        internet = (
            BINARY_SENSOR_MODULE.GritHubInternetConnectivityBinarySensor(
                self.coordinator
            )
        )
        buttons = (
            BINARY_SENSOR_MODULE.GritHubPhysicalButtonsDisabledBinarySensor(
                self.coordinator
            )
        )
        ip_sensor = SENSOR_MODULE.GritHubIpAddressSensor(self.coordinator)
        version = SENSOR_MODULE.GritHubSoftwareVersionSensor(
            self.coordinator
        )
        branch = SENSOR_MODULE.GritHubSoftwareBranchSensor(self.coordinator)

        self.assertTrue(internet.is_on)
        self.assertFalse(buttons.is_on)
        self.assertEqual(ip_sensor.native_value, HUB_IP)
        self.assertEqual(version.native_value, "1.2.3-test")
        self.assertEqual(branch.native_value, "fabricated-branch")

        sensitive = "fabricated-sensitive-hub-value"
        self.coordinator.data["hub"].update(
            {
                "wifiPassword": sensitive,
                "rawResponse": {"value": sensitive},
            }
        )
        exposed = repr(
            [
                internet.is_on,
                buttons.is_on,
                ip_sensor.native_value,
                version.native_value,
                branch.native_value,
                ip_sensor.device_info,
            ]
        )
        for excluded in (
            sensitive,
            CONST_MODULE.DEFAULT_MQTT_USERNAME,
            CONST_MODULE.DEFAULT_MQTT_PASSWORD,
        ):
            self.assertNotIn(excluded, exposed)
        self.assertNotIn(
            CONST_MODULE.DEFAULT_MQTT_USERNAME,
            repr(self.coordinator.data),
        )
        for entity in (internet, buttons, ip_sensor, version, branch):
            self.assertFalse(hasattr(entity, "extra_state_attributes"))

    def test_led_brightness_is_bounded_and_requires_new_hub_response(self):
        entity = NUMBER_MODULE.GritHubSystemLedBrightnessNumber(
            self.coordinator
        )
        self.assertEqual(entity.native_value, 42)
        self.assertEqual(entity._attr_native_min_value, 0)
        self.assertEqual(entity._attr_native_max_value, 100)
        self.assertEqual(entity._attr_native_step, 1)
        self.assertEqual(entity._attr_entity_category, EntityCategory.CONFIG)
        self.assertTrue(entity.available)

        def confirm_brightness() -> None:
            self.coordinator.data["hub"]["systemLedBrightness"] = 55
            self.coordinator.hub_update_sequence = (
                self.coordinator.refresh_sequence
            )

        self.coordinator.refresh_hook = confirm_brightness
        self.loop.run_until_complete(entity.async_set_native_value(55))
        self.assertEqual(
            self.coordinator.api.hub_calls,
            [("set_led", HUB_ID, 55)],
        )
        self.assertEqual(self.coordinator.refresh_calls, 1)
        self.assertEqual(entity.native_value, 55)

        for invalid in (-1, 101, 1.5, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(HomeAssistantError):
                    self.loop.run_until_complete(
                        entity.async_set_native_value(invalid)
                    )
        self.assertEqual(len(self.coordinator.api.hub_calls), 1)

        self.coordinator.refresh_hook = lambda: None
        with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
            self.loop.run_until_complete(entity.async_set_native_value(55))
        self.assertEqual(entity.native_value, 55)

        self.coordinator.refresh_block = asyncio.Event()
        with mock.patch.object(NUMBER_MODULE, "HUB_CONFIRM_TIMEOUT", 0.01):
            with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
                self.loop.run_until_complete(
                    entity.async_set_native_value(56)
                )
        self.coordinator.refresh_block = None
        self.assertEqual(entity.native_value, 55)

    def test_gritlock_state_and_post_command_confirmation(self):
        entity = LOCK_MODULE.GritHubSystemLock(self.coordinator)
        self.assertEqual(
            entity._attr_unique_id,
            "grit_hub_system_gritlock",
        )
        for value in (True, False, None):
            with self.subTest(value=value):
                self.coordinator.gritlock_state_value = value
                self.assertIs(entity.is_locked, value)
                self.assertTrue(entity.available)

        self.coordinator.gritlock_state_value = None
        with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
            self.loop.run_until_complete(entity.async_lock())
        self.assertIsNone(entity.is_locked)
        self.assertEqual(
            self.coordinator.api.hub_calls[-1],
            ("set_gritlock", True),
        )

        def confirm(expected: bool) -> bool:
            self.coordinator.gritlock_state_value = expected
            return True

        self.coordinator.gritlock_confirmation_hook = confirm
        self.loop.run_until_complete(entity.async_lock())
        self.assertTrue(entity.is_locked)
        self.loop.run_until_complete(entity.async_unlock())
        self.assertFalse(entity.is_locked)

        self.coordinator.gritlock_confirmation_block = asyncio.Event()
        with mock.patch.object(LOCK_MODULE, "HUB_CONFIRM_TIMEOUT", 0.01):
            with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
                self.loop.run_until_complete(entity.async_lock())
        self.coordinator.gritlock_confirmation_block = None

        self.assertEqual(
            self.coordinator.api.hub_calls[-4:],
            [
                ("set_gritlock", True),
                ("set_gritlock", True),
                ("set_gritlock", False),
                ("set_gritlock", True),
            ],
        )
        self.assertEqual(self.coordinator.refresh_calls, 0)
        self.assertEqual(
            self.coordinator.gritlock_confirmation_calls,
            [
                (True, 1, LOCK_MODULE.HUB_CONFIRM_TIMEOUT),
                (True, 2, LOCK_MODULE.HUB_CONFIRM_TIMEOUT),
                (False, 3, LOCK_MODULE.HUB_CONFIRM_TIMEOUT),
                (True, 4, 0.01),
            ],
        )

    def test_gritlock_does_not_command_without_mqtt(self):
        entity = LOCK_MODULE.GritHubSystemLock(self.coordinator)
        self.coordinator.mqtt_connected = False
        before = list(self.coordinator.api.hub_calls)

        with self.assertRaisesRegex(HomeAssistantError, "confirmed"):
            self.loop.run_until_complete(entity.async_lock())

        self.assertFalse(entity.available)
        self.assertEqual(self.coordinator.api.hub_calls, before)

    def test_restart_and_reboot_buttons_use_only_explicit_fake_methods(self):
        restart = BUTTON_MODULE.GritHubRestartServiceButton(
            self.coordinator
        )
        reboot = BUTTON_MODULE.GritHubRebootHubButton(self.coordinator)
        self.assertFalse(reboot._attr_entity_registry_enabled_default)

        self.loop.run_until_complete(restart.async_press())
        self.loop.run_until_complete(reboot.async_press())

        self.assertEqual(
            self.coordinator.api.hub_calls,
            [("restart_service",), ("reboot_hub",)],
        )
        self.assertEqual(self.coordinator.refresh_calls, 0)

    def test_exposed_state_and_attributes_contain_no_raw_mqtt_values(self):
        topic = "grit/private-hub/gate/private-device/status"
        payload = "fabricated-private-payload"
        hub_id = "private-hub"
        device_id = "private-device"
        broker = "broker.private.invalid"
        self.gate[MQTT_STATE_KEY] = {
            "position": 75,
            "open": True,
            "online": True,
            "rssi": -70,
            "firmware_version": "v2",
            "last_received_at": datetime.now(timezone.utc),
            "topic": topic,
            "raw_payload": payload,
            "hub_id": hub_id,
            "device_id": device_id,
        }
        entities = [
            self.gate_cover(),
            BINARY_SENSOR_MODULE.GritHubMqttConnectionBinarySensor(
                self.coordinator, ENTRY_ID
            ),
            BINARY_SENSOR_MODULE.GritHubDeviceMqttOnlineBinarySensor(
                self.coordinator, ENTRY_ID, "gate", self.gate
            ),
            SENSOR_MODULE.GritHubMqttRssiSensor(
                self.coordinator, ENTRY_ID, "gate", self.gate
            ),
            SENSOR_MODULE.GritHubMqttFirmwareSensor(
                self.coordinator, ENTRY_ID, "gate", self.gate
            ),
            SENSOR_MODULE.GritHubMqttLastReceivedSensor(
                self.coordinator, ENTRY_ID, "gate", self.gate
            ),
        ]
        with self.assertNoLogs(level=logging.DEBUG):
            exposed = []
            for entity in entities:
                exposed.extend(
                    (
                        getattr(entity, "_attr_name", None),
                        getattr(entity, "native_value", None),
                        getattr(entity, "is_on", None),
                        getattr(entity, "is_closed", None),
                        getattr(entity, "extra_state_attributes", None),
                    )
                )
        serialized = repr(exposed)
        for private_value in (
            topic,
            payload,
            hub_id,
            device_id,
            broker,
        ):
            self.assertNotIn(private_value, serialized)


if __name__ == "__main__":
    unittest.main()

"""Network-free tests for Home Assistant entities backed by sanitized MQTT state."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import IntFlag
import importlib.util
import logging
from pathlib import Path
import socket
import sys
import types
from typing import Any
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
ENTRY_ID = "entry-fabricated"
GATE_ID = "gate-fabricated"
SWITCH_ID = "switch-fabricated"
MQTT_STATE_KEY = "_grit_mqtt"


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


class EntityCategory:
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
    const = types.ModuleType("homeassistant.const")
    const.EntityCategory = EntityCategory
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
    for name in ("entity", "cover", "switch", "sensor", "binary_sensor"):
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
CONST_MODULE = MODULES["const"]


class FakeApi:
    """Physical-command tripwire; every command would fail the test."""

    def __init__(self) -> None:
        self.command_calls = 0

    async def set_device_state(self, *_args: Any, **_kwargs: Any) -> None:
        self.command_calls += 1
        raise AssertionError("physical device command is forbidden")


class FakeCoordinator:
    def __init__(self, devices: dict[str, list[dict[str, Any]]]) -> None:
        self.data = {"devices": devices}
        self.last_update_success = True
        self.mqtt_connected = True
        self.api = FakeApi()
        self.listener_updates = 0

    async def async_request_refresh(self) -> None:
        raise AssertionError("REST refresh is forbidden in entity state tests")

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

    def test_cover_rest_fallback_precedes_first_mqtt_state(self):
        cover = self.gate_cover()
        self.assertEqual(cover.current_cover_position, 20)
        self.assertTrue(cover.is_closed)
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
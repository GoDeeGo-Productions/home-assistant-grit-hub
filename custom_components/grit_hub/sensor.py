"""Sensors for GRIT Hub."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .api import obj_id, obj_name
from .const import DOMAIN, SENSOR_DEVICE_TYPES
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [GritHubStatusSensor(coordinator), GritHubDeviceCountSensor(coordinator)]
    for dev_type in SENSOR_DEVICE_TYPES:
        for dev in coordinator.data.get("devices", {}).get(dev_type, []):
            if obj_id(dev) is not None:
                entities.append(GritHubGenericDeviceSensor(coordinator, dev_type, dev))
    async_add_entities(entities)


class GritHubStatusSensor(GritHubEntity, SensorEntity):
    _attr_name = "Status"
    _attr_unique_id = "grit_hub_status"
    _attr_icon = "mdi:hubspot"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return "online" if self.coordinator.last_update_success else "offline"


class GritHubDeviceCountSensor(GritHubEntity, SensorEntity):
    _attr_name = "Device Count"
    _attr_unique_id = "grit_hub_device_count"
    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return sum(len(v) for v in self.coordinator.data.get("devices", {}).values())


class GritHubGenericDeviceSensor(GritHubEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_{device_type}_{ident}_status"
        self._attr_name = f"{obj_name(device, device_type.title())} Status"

    @property
    def native_value(self):
        attributes = self.diagnostic_attributes
        return attributes.get("status") or attributes.get("state") or attributes.get("mode") or "unknown"

    @property
    def extra_state_attributes(self):
        return self.diagnostic_attributes

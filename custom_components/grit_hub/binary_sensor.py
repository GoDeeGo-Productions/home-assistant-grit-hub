"""Binary sensors for GRIT Hub."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([GritHubOnlineBinarySensor(coordinator)])


class GritHubOnlineBinarySensor(GritHubEntity, BinarySensorEntity):
    _attr_name = "Online"
    _attr_unique_id = "grit_hub_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success

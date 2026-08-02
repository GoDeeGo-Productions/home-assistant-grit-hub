"""Switches for GRIT Hub controllable devices."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError, bool_state, obj_id, obj_name
from .const import DOMAIN, SWITCH_DEVICE_TYPES
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    for dev_type in SWITCH_DEVICE_TYPES:
        for dev in coordinator.data.get("devices", {}).get(dev_type, []):
            if obj_id(dev) is not None:
                entities.append(GritHubDeviceSwitch(coordinator, dev_type, dev))
    async_add_entities(entities)


class GritHubDeviceSwitch(GritHubEntity, SwitchEntity):
    def __init__(self, coordinator, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_{device_type}_{ident}"
        self._attr_name = obj_name(device, device_type.title())
        self._attr_icon = "mdi:lock" if device_type == "rfid" else "mdi:electric-switch"

    @property
    def available(self):
        return self.live_available

    @property
    def is_on(self):
        mqtt_state = self.mqtt_state
        if "state" in mqtt_state:
            state = mqtt_state["state"]
            return state if isinstance(state, bool) else None
        return bool_state(self.current_device)

    @property
    def extra_state_attributes(self):
        return self.diagnostic_attributes

    async def async_turn_on(self, **kwargs):
        try:
            await self.coordinator.api.set_device_state(self.device_type, self._device_id, True)
            await self.coordinator.async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs):
        try:
            await self.coordinator.api.set_device_state(self.device_type, self._device_id, False)
            await self.coordinator.async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

"""Gate covers for GRIT Hub."""
from __future__ import annotations

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError, bool_state, obj_id, obj_name
from .const import COVER_DEVICE_TYPES, DOMAIN
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    for dev_type in COVER_DEVICE_TYPES:
        for dev in coordinator.data.get("devices", {}).get(dev_type, []):
            if obj_id(dev) is not None:
                entities.append(GritHubGateCover(coordinator, dev_type, dev))
    async_add_entities(entities)


class GritHubGateCover(GritHubEntity, CoverEntity):
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    _attr_device_class = "gate"

    def __init__(self, coordinator, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_{device_type}_{ident}"
        self._attr_name = obj_name(device, "Gate")

    @property
    def is_closed(self):
        state = bool_state(self.current_device)
        if state is None:
            return None
        return not state

    @property
    def extra_state_attributes(self):
        return self.diagnostic_attributes

    async def async_open_cover(self, **kwargs):
        try:
            await self.coordinator.api.set_device_state(self.device_type, self._device_id, True)
            await self.coordinator.async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_close_cover(self, **kwargs):
        try:
            await self.coordinator.api.set_device_state(self.device_type, self._device_id, False)
            await self.coordinator.async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

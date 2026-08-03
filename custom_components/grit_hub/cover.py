"""Gate covers for GRIT Hub."""
from __future__ import annotations

import asyncio
import math

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError, bool_state, obj_id, obj_name
from .const import (
    COVER_DEVICE_TYPES,
    DEVICE_CONFIRM_TIMEOUT,
    DOMAIN,
)
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    for dev_type in COVER_DEVICE_TYPES:
        for dev in coordinator.data.get("devices", {}).get(dev_type, []):
            if obj_id(dev) is not None:
                entities.append(GritHubGateCover(coordinator, dev_type, dev))
    async_add_entities(entities)


def _bounded_position(value):
    """Return a Home Assistant cover position without coercing text or bools."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return round(value)


class GritHubGateCover(GritHubEntity, CoverEntity):
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    _attr_device_class = "gate"

    def __init__(self, coordinator, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_{device_type}_{ident}"
        self._attr_name = obj_name(device, "Gate")

    @property
    def available(self):
        return self.live_available

    @property
    def current_cover_position(self):
        mqtt_state = self.mqtt_state
        if "position" in mqtt_state:
            return _bounded_position(mqtt_state["position"])
        return _bounded_position(self.current_device.get("position"))

    @property
    def is_closed(self):
        mqtt_state = self.mqtt_state
        if "open" in mqtt_state:
            open_state = mqtt_state["open"]
            if not isinstance(open_state, bool):
                return None
            return not open_state

        state = bool_state(self.current_device)
        if state is None:
            return None
        return not state

    @property
    def extra_state_attributes(self):
        return self.diagnostic_attributes

    async def async_open_cover(self, **kwargs):
        await self._async_set_open(True)

    async def async_close_cover(self, **kwargs):
        await self._async_set_open(False)

    def _observed_open(self) -> bool | None:
        observed = self.current_device_observation
        if observed is None:
            return None
        mqtt_state = self.mqtt_state
        if "open" in mqtt_state:
            state = mqtt_state["open"]
            return state if isinstance(state, bool) else None
        return bool_state(observed)

    async def _async_set_open(self, open_state: bool) -> None:
        try:
            await self.coordinator.api.set_device_state(
                self.device_type,
                self._device_id,
                open_state,
            )
            confirmation_generation = self.coordinator.refresh_sequence
            await asyncio.wait_for(
                self.coordinator.async_request_refresh(),
                timeout=DEVICE_CONFIRM_TIMEOUT,
            )
        except (GritHubApiError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(
                "Gate state could not be confirmed"
            ) from err
        if (
            not self.coordinator.last_update_success
            or self.coordinator.refresh_sequence <= confirmation_generation
            or self._observed_open() is not open_state
        ):
            raise HomeAssistantError("Gate state could not be confirmed")

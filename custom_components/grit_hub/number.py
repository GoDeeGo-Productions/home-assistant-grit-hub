"""Number entities for GRIT Hub."""
from __future__ import annotations

import asyncio

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError
from .const import DOMAIN, HUB_CONFIRM_TIMEOUT
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([GritHubSystemLedBrightnessNumber(coordinator)])


class GritHubSystemLedBrightnessNumber(GritHubEntity, NumberEntity):
    """Documented system LED brightness with confirmed REST state."""

    _attr_name = "System LED Brightness"
    _attr_unique_id = "grit_hub_system_led_brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> int | None:
        value = self.hub_data.get("systemLedBrightness")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value <= 100 else None

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.hub_id is not None
            and self.native_value is not None
        )

    async def async_set_native_value(self, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 100
            or int(value) != value
        ):
            raise HomeAssistantError("System LED brightness is invalid")
        hub_id = self.coordinator.hub_id
        if hub_id is None:
            raise HomeAssistantError("Hub identity is unavailable")
        brightness = int(value)
        confirmation_after = self.coordinator.refresh_sequence
        try:
            await self.coordinator.api.set_system_led_brightness(
                hub_id,
                brightness,
            )
            await asyncio.wait_for(
                self.coordinator.async_request_refresh(),
                timeout=HUB_CONFIRM_TIMEOUT,
            )
        except (GritHubApiError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(
                "System LED brightness could not be confirmed"
            ) from err
        if (
            self.coordinator.hub_update_sequence <= confirmation_after
            or self.native_value != brightness
        ):
            raise HomeAssistantError(
                "System LED brightness could not be confirmed"
            )

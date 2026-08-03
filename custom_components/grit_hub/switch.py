"""Switches for GRIT Hub controllable devices."""
from __future__ import annotations

import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError, bool_state, obj_id, obj_name
from .const import (
    DEVICE_CONFIRM_TIMEOUT,
    DOMAIN,
    SWITCH_DEVICE_TYPES,
)
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
        if self.device_type == "rfid":
            return None
        return bool_state(self.current_device)

    @property
    def extra_state_attributes(self):
        attributes = self.diagnostic_attributes
        if self.device_type == "rfid":
            attributes.pop("state", None)
        return attributes

    async def async_turn_on(self, **kwargs):
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs):
        await self._async_set_state(False)

    def _observed_state(self) -> bool | None:
        observed = self.current_device_observation
        if observed is None:
            return None
        return bool_state(observed)

    async def _async_set_state(self, state: bool) -> None:
        if self.device_type == "rfid":
            if not self.coordinator.mqtt_connected:
                raise HomeAssistantError(
                    "Device state could not be confirmed"
                )
            try:
                await self.coordinator.api.set_device_state(
                    self.device_type,
                    self._device_id,
                    state,
                )
                confirmation_boundary = self.coordinator.mqtt_receive_sequence
                confirmed = await self.coordinator.async_confirm_device_state(
                    self.device_type,
                    self._device_id,
                    state,
                    after_sequence=confirmation_boundary,
                    timeout=DEVICE_CONFIRM_TIMEOUT,
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:
                raise HomeAssistantError(
                    "Device state could not be confirmed"
                ) from err
            if not confirmed:
                raise HomeAssistantError(
                    "Device state could not be confirmed"
                )
            return

        try:
            await self.coordinator.api.set_device_state(
                self.device_type,
                self._device_id,
                state,
            )
            confirmation_generation = self.coordinator.refresh_sequence
            await asyncio.wait_for(
                self.coordinator.async_request_refresh(),
                timeout=DEVICE_CONFIRM_TIMEOUT,
            )
        except (GritHubApiError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(
                "Device state could not be confirmed"
            ) from err
        if (
            not self.coordinator.last_update_success
            or self.coordinator.refresh_sequence <= confirmation_generation
            or self._observed_state() is not state
        ):
            raise HomeAssistantError("Device state could not be confirmed")

"""Lock entities for GRIT Hub."""
from __future__ import annotations

import asyncio

from homeassistant.components.lock import LockEntity
from homeassistant.exceptions import HomeAssistantError

from .api import obj_id, obj_name
from .const import DEVICE_CONFIRM_TIMEOUT, DOMAIN, HUB_CONFIRM_TIMEOUT
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [GritHubSystemLock(coordinator)]
    for device in coordinator.data.get("devices", {}).get("rfid", []):
        if obj_id(device) is not None:
            entities.append(
                GritHubRfidLock(coordinator, "rfid", device)
            )
    async_add_entities(entities)


class GritHubSystemLock(GritHubEntity, LockEntity):
    """System state derived only from participating trigger observations."""

    _attr_name = "GRITLock"
    _attr_unique_id = "grit_hub_system_gritlock"
    _attr_icon = "mdi:shield-lock"

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.mqtt_connected
        )

    @property
    def is_locked(self) -> bool | None:
        return self.coordinator.gritlock_state

    async def async_lock(self, **kwargs) -> None:
        await self._async_set_gritlock(True)

    async def async_unlock(self, **kwargs) -> None:
        await self._async_set_gritlock(False)

    async def _async_set_gritlock(self, locked: bool) -> None:
        if not self.coordinator.mqtt_connected:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            )
        confirmation_boundary = self.coordinator.mqtt_receive_sequence
        generation_id = self.coordinator.begin_gritlock_generation(
            confirmation_boundary
        )
        if generation_id is None:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            )
        try:
            await self.coordinator.api.set_gritlock(locked)
            confirmed = await self.coordinator.async_confirm_gritlock_state(
                locked,
                generation_id=generation_id,
                timeout=HUB_CONFIRM_TIMEOUT,
            )
        except asyncio.CancelledError:
            self.coordinator.cancel_gritlock_generation(generation_id)
            raise
        except Exception as err:
            self.coordinator.cancel_gritlock_generation(generation_id)
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            ) from err
        if not confirmed:
            self.coordinator.cancel_gritlock_generation(generation_id)
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            )


class GritHubRfidLock(GritHubEntity, LockEntity):
    """RFID reader lock state confirmed only by authoritative MQTT state."""

    _attr_icon = "mdi:card-account-details"

    def __init__(self, coordinator, device_type, device) -> None:
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_rfid_{ident}"
        self._attr_name = obj_name(device, "RFID reader")

    @property
    def available(self) -> bool:
        return self.live_available

    @property
    def is_locked(self) -> bool | None:
        locked = self.mqtt_state.get("locked")
        if isinstance(locked, bool):
            return locked
        provisional = self.current_device.get("lockout")
        return provisional if isinstance(provisional, bool) else None

    @property
    def extra_state_attributes(self):
        attributes = self.diagnostic_attributes
        attributes.pop("state", None)
        return attributes

    async def async_lock(self, **kwargs) -> None:
        await self._async_set_enabled(False)

    async def async_unlock(self, **kwargs) -> None:
        await self._async_set_enabled(True)

    async def _async_set_enabled(self, enabled: bool) -> None:
        if not self.coordinator.mqtt_connected:
            raise HomeAssistantError(
                "RFID state could not be confirmed"
            )
        expected_locked = not enabled
        confirmation_boundary = self.coordinator.mqtt_receive_sequence
        try:
            await self.coordinator.api.set_device_state(
                "rfid",
                self._device_id,
                enabled,
            )
            confirmed = await self.coordinator.async_confirm_device_state(
                "rfid",
                self._device_id,
                expected_locked,
                after_sequence=confirmation_boundary,
                timeout=DEVICE_CONFIRM_TIMEOUT,
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                "RFID state could not be confirmed"
            ) from err
        if not confirmed:
            raise HomeAssistantError(
                "RFID state could not be confirmed"
            )

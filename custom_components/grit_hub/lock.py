"""Lock entities for GRIT Hub."""
from __future__ import annotations

import asyncio
from collections import Counter

from homeassistant.components.lock import LockEntity
from homeassistant.exceptions import HomeAssistantError

from .api import obj_id, obj_name
from .const import DEVICE_CONFIRM_TIMEOUT, DOMAIN, HUB_CONFIRM_TIMEOUT
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [GritHubSystemLock(coordinator)]
    readers = coordinator.data.get("devices", {}).get("rfid", [])
    identifiers = [
        str(device.get("id")).strip()
        if isinstance(device, dict)
        and not isinstance(device.get("id"), bool)
        and isinstance(device.get("id"), (str, int))
        else None
        for device in readers
    ]
    counts = Counter(
        identifier
        for identifier in identifiers
        if identifier and len(identifier) <= 128 and identifier.isprintable()
    )
    for device, identifier in zip(readers, identifiers):
        if identifier and counts[identifier] == 1:
            entities.append(GritHubRfidLock(coordinator, "rfid", device))
    async_add_entities(entities)


class GritHubSystemLock(GritHubEntity, LockEntity):
    """System state derived only from participating trigger observations."""

    _attr_name = "GRITLock"
    _attr_unique_id = "grit_hub_system_gritlock"
    _attr_icon = "mdi:shield-lock"

    @property
    def available(self) -> bool:
        state = self.coordinator.gritlock_state
        return (
            self.coordinator.last_update_success
            and self.coordinator.mqtt_connected
            and isinstance(state, bool)
        )

    @property
    def is_locked(self) -> bool | None:
        state = self.coordinator.gritlock_state
        return state if isinstance(state, bool) else None

    async def async_lock(self, **kwargs) -> None:
        await self._async_set_gritlock(True)

    async def async_unlock(self, **kwargs) -> None:
        await self._async_set_gritlock(False)

    async def _async_set_gritlock(self, locked: bool) -> None:
        if not self.coordinator.mqtt_connected:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            )
        connection_generation = (
            self.coordinator.mqtt_connection_generation
        )
        confirmation_boundary = self.coordinator.mqtt_receive_sequence
        try:
            await self.coordinator.api.set_gritlock(locked)
            confirmed = await self.coordinator.async_wait_for_gritlock_state(
                locked,
                after_connection_generation=connection_generation,
                after_receive_sequence=confirmation_boundary,
                timeout=HUB_CONFIRM_TIMEOUT,
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            ) from err
        if not confirmed:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            )


class GritHubRfidLock(GritHubEntity, LockEntity):
    """RFID reader lock state from its individual REST response."""

    _attr_icon = "mdi:card-account-details"

    def __init__(self, coordinator, device_type, device) -> None:
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_rfid_{ident}"
        self._attr_name = obj_name(device, "RFID reader")

    @property
    def available(self) -> bool:
        online = self.current_device.get("onlineStatus")
        return self.coordinator.last_update_success and online is not False

    @property
    def is_locked(self) -> bool | None:
        enabled = self.coordinator.rfid_enabled(self._device_id)
        return not enabled if isinstance(enabled, bool) else None

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
        confirmation_boundary = self.coordinator.rfid_state_generation(
            self._device_id
        )
        try:
            await self.coordinator.api.set_device_state(
                "rfid",
                self._device_id,
                enabled,
            )
            confirmed = await self.coordinator.async_confirm_rfid_state(
                self._device_id,
                enabled,
                after_generation=confirmation_boundary,
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

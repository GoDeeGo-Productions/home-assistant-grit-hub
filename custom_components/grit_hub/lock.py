"""System-wide GRITLock entity for GRIT Hub."""
from __future__ import annotations

import asyncio

from homeassistant.components.lock import LockEntity
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError
from .const import DOMAIN, HUB_CONFIRM_TIMEOUT
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([GritHubSystemLock(coordinator)])


class GritHubSystemLock(GritHubEntity, LockEntity):
    """System state derived only from participating trigger observations."""

    _attr_name = "GRITLock"
    _attr_unique_id = "grit_hub_system_gritlock"
    _attr_icon = "mdi:shield-lock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._awaiting_confirmation = False
        self._confirmation_after_refresh: int | None = None

    @property
    def is_locked(self) -> bool | None:
        if self._awaiting_confirmation:
            if (
                self._confirmation_after_refresh is None
                or self.coordinator.gritlock_update_sequence
                <= self._confirmation_after_refresh
            ):
                return None
            self._awaiting_confirmation = False
            self._confirmation_after_refresh = None
        return self.coordinator.gritlock_state

    async def async_lock(self, **kwargs) -> None:
        await self._async_set_gritlock(True)

    async def async_unlock(self, **kwargs) -> None:
        await self._async_set_gritlock(False)

    async def _async_set_gritlock(self, locked: bool) -> None:
        self._awaiting_confirmation = True
        self._confirmation_after_refresh = self.coordinator.refresh_sequence
        try:
            await self.coordinator.api.set_gritlock(locked)
            self._confirmation_after_refresh = (
                self.coordinator.refresh_sequence
            )
            await asyncio.wait_for(
                self.coordinator.async_request_refresh(),
                timeout=HUB_CONFIRM_TIMEOUT,
            )
        except (GritHubApiError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            ) from err

        if self.is_locked is not locked:
            raise HomeAssistantError(
                "GRITLock state could not be confirmed"
            )

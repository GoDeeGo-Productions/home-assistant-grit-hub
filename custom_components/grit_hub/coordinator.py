"""Data update coordinator for GRIT Hub."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GritHubApiClient, GritHubApiError
from .const import DEVICE_TYPES, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GritHubCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches hub and device collection data."""

    def __init__(self, hass, api: GritHubApiClient, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"devices": {}, "hub": None, "health": None, "errors": {}}
        try:
            data["health"] = await self.api.health_check()
        except GritHubApiError as err:
            raise UpdateFailed(str(err)) from err

        try:
            data["hub"] = await self.api.get_hub()
        except GritHubApiError as err:
            data["errors"]["hub"] = str(err)

        for dev_type in DEVICE_TYPES:
            try:
                data["devices"][dev_type] = await self.api.get_collection(dev_type)
            except GritHubApiError as err:
                data["devices"][dev_type] = []
                data["errors"][dev_type] = str(err)
        return data

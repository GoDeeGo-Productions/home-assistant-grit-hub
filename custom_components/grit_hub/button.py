"""Buttons for GRIT Hub."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiError, obj_id, obj_name
from .const import DEVICE_TYPES, DOMAIN
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [
        GritHubRefreshAllButton(coordinator),
        GritHubRestartServiceButton(coordinator),
        GritHubRebootHubButton(coordinator),
    ]
    for dev_type in DEVICE_TYPES:
        for dev in coordinator.data.get("devices", {}).get(dev_type, []):
            if obj_id(dev) is not None:
                entities.append(GritHubRefreshDeviceButton(coordinator, dev_type, dev))
                entities.append(GritHubLocateDeviceButton(coordinator, dev_type, dev))
    async_add_entities(entities)


class GritHubRefreshAllButton(GritHubEntity, ButtonEntity):
    _attr_name = "Refresh All"
    _attr_unique_id = "grit_hub_refresh_all"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class GritHubRestartServiceButton(GritHubEntity, ButtonEntity):
    _attr_name = "Restart GRIT Service"
    _attr_unique_id = "grit_hub_restart_service"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.restart_service()
        except GritHubApiError as err:
            raise HomeAssistantError(
                "GRIT service restart failed"
            ) from err


class GritHubRebootHubButton(GritHubEntity, ButtonEntity):
    _attr_name = "Reboot Hub"
    _attr_unique_id = "grit_hub_reboot"
    _attr_icon = "mdi:power-cycle"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.reboot_hub()
        except GritHubApiError as err:
            raise HomeAssistantError("GRIT Hub reboot failed") from err


class GritHubRefreshDeviceButton(GritHubEntity, ButtonEntity):
    _attr_icon = "mdi:refresh-circle"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_{device_type}_{ident}_refresh"
        self._attr_name = f"{obj_name(device, device_type.title())} Refresh"

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.refresh_device(self.device_type, self._device_id)
            await self.coordinator.async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err


class GritHubLocateDeviceButton(GritHubEntity, ButtonEntity):
    _attr_icon = "mdi:map-marker-radius"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = f"grit_hub_{device_type}_{ident}_locate"
        self._attr_name = f"{obj_name(device, device_type.title())} Locate"

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.locate_device(self.device_type, self._device_id)
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

"""GRIT Hub integration."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .api import GritHubApiClient, GritHubApiError
from .const import (
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import GritHubCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_DEVICE_COMMAND = "device_command"
SERVICE_REFRESH_DEVICE = "refresh_device"
SERVICE_LOCATE_DEVICE = "locate_device"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GRIT Hub from a config entry."""
    api = GritHubApiClient(
        hass,
        entry.data[CONF_BASE_URL],
        entry.data[CONF_TOKEN],
        entry.data.get(CONF_VERIFY_SSL, True),
    )
    coordinator = GritHubCoordinator(
        hass,
        api,
        entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"api": api, "coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _first_api(hass: HomeAssistant) -> GritHubApiClient:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No GRIT Hub instance is configured")
    return next(iter(entries.values()))["api"]


def _first_coordinator(hass: HomeAssistant) -> GritHubCoordinator:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No GRIT Hub instance is configured")
    return next(iter(entries.values()))["coordinator"]


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_DEVICE_COMMAND):
        return

    async def device_command(call: ServiceCall) -> None:
        api = _first_api(hass)
        try:
            await api.call_command(
                call.data["device_type"],
                call.data["device_id"],
                call.data["command_name"],
                call.data["action"],
                call.data.get("remote_type", "api"),
            )
            await _first_coordinator(hass).async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def refresh_device(call: ServiceCall) -> None:
        api = _first_api(hass)
        try:
            await api.refresh_device(call.data["device_type"], call.data["device_id"])
            await _first_coordinator(hass).async_request_refresh()
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def locate_device(call: ServiceCall) -> None:
        api = _first_api(hass)
        try:
            await api.locate_device(call.data["device_type"], call.data["device_id"])
        except GritHubApiError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_DEVICE_COMMAND,
        device_command,
        schema=vol.Schema({
            vol.Required("device_type"): str,
            vol.Required("device_id"): vol.Any(str, int),
            vol.Required("command_name"): str,
            vol.Required("action"): str,
            vol.Optional("remote_type", default="api"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_DEVICE,
        refresh_device,
        schema=vol.Schema({vol.Required("device_type"): str, vol.Required("device_id"): vol.Any(str, int)}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOCATE_DEVICE,
        locate_device,
        schema=vol.Schema({vol.Required("device_type"): str, vol.Required("device_id"): vol.Any(str, int)}),
    )

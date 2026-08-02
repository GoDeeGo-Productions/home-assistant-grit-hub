"""Config flow for GRIT Hub."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api import GritHubApiClient, GritHubApiError
from .const import CONF_BASE_URL, CONF_SCAN_INTERVAL, CONF_TOKEN, CONF_VERIFY_SSL, DEFAULT_SCAN_INTERVAL, DOMAIN


class GritHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            await self.async_set_unique_id(base_url)
            self._abort_if_unique_id_configured()
            api = GritHubApiClient(self.hass, base_url, user_input[CONF_TOKEN], user_input[CONF_VERIFY_SSL])
            try:
                await api.health_check()
            except GritHubApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="GRIT Hub", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_BASE_URL): str,
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_VERIFY_SSL, default=True): bool,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=10, max=3600)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GritHubOptionsFlow(config_entry)


class GritHubOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=10, max=3600))
            }),
        )

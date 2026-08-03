"""Config flow for GRIT Hub."""
from __future__ import annotations

import asyncio
from functools import partial
import threading
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import GritHubApiClient, GritHubApiError
from .auth import InvalidBearerToken, validate_bearer_token
from .const import (
    CONF_BASE_URL,
    CONF_MQTT_HOST,
    CONF_MQTT_HUB_ID,
    CONF_MQTT_KEEPALIVE,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_MQTT_USE_TLS,
    CONF_MQTT_VERIFY_TLS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_VERIFY_SSL,
    DEFAULT_MQTT_KEEPALIVE,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_MQTT_HOST_LENGTH,
    MAX_MQTT_HUB_ID_LENGTH,
    MAX_MQTT_USERNAME_LENGTH,
    MQTT_DISCOVERY_TIMEOUT,
)
from .discovery import (
    extract_rest_mqtt_discovery,
    passive_mqtt_discover,
)

_MAX_BASE_URL_LENGTH = 2048
_MAX_MQTT_PASSWORD_LENGTH = 4096
_CONF_SHOW_ADVANCED = "show_advanced"
_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class _InputError(ValueError):
    """Local form validation error without user-provided values."""

    def __init__(self, field: str, code: str) -> None:
        super().__init__(code)
        self.field = field
        self.code = code


def _text(
    data: dict[str, Any],
    field: str,
    maximum: int,
    code: str,
    *,
    topic_component: bool = False,
) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise _InputError(field, code)
    value = value.strip()
    if (
        not value
        or len(value) > maximum
        or not value.isprintable()
        or (topic_component and any(char in value for char in "/+#"))
    ):
        raise _InputError(field, code)
    return value


def _integer(
    data: dict[str, Any],
    field: str,
    default: int,
    minimum: int,
    maximum: int,
    code: str,
) -> int:
    value = data.get(field, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _InputError(field, code)
    return value


def _boolean(
    data: dict[str, Any],
    field: str,
    default: bool,
    code: str,
) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise _InputError(field, code)
    return value


def _token(
    data: dict[str, Any],
    field: str,
    code: str,
    existing: dict[str, Any] | None,
) -> str:
    value = data.get(field)
    if value is not None and not (
        isinstance(value, str) and not value.strip()
    ):
        try:
            return validate_bearer_token(value)
        except InvalidBearerToken:
            raise _InputError(field, code)
    if existing is not None:
        stored = existing.get(field)
        try:
            return validate_bearer_token(stored)
        except InvalidBearerToken:
            pass
    raise _InputError(field, code)


def _username(data: dict[str, Any]) -> str | None:
    value = data.get(CONF_MQTT_USERNAME)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _InputError(CONF_MQTT_USERNAME, "invalid_mqtt_username")
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_MQTT_USERNAME_LENGTH or not value.isprintable():
        raise _InputError(CONF_MQTT_USERNAME, "invalid_mqtt_username")
    return value


def _password(data: dict[str, Any]) -> str | None:
    value = data.get(CONF_MQTT_PASSWORD)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _MAX_MQTT_PASSWORD_LENGTH:
        raise _InputError(CONF_MQTT_PASSWORD, "invalid_mqtt_password")
    return value if value.strip() else None


def _normalize_api_config(
    data: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the small initial REST form without MQTT assumptions."""
    base_url = _text(
        data, CONF_BASE_URL, _MAX_BASE_URL_LENGTH, "invalid_base_url"
    ).rstrip("/")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
    except ValueError as err:
        raise _InputError(CONF_BASE_URL, "invalid_base_url") from err
    if (
        not base_url
        or parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _InputError(CONF_BASE_URL, "invalid_base_url")
    return {
        CONF_BASE_URL: base_url,
        CONF_TOKEN: _token(data, CONF_TOKEN, "invalid_token", existing),
        CONF_VERIFY_SSL: _boolean(
            data, CONF_VERIFY_SSL, True, "invalid_verify_ssl"
        ),
    }


def _normalize_config(
    data: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize the complete stored configuration."""
    normalized = _normalize_api_config(data, existing=existing)
    normalized[CONF_SCAN_INTERVAL] = _integer(
        data,
        CONF_SCAN_INTERVAL,
        DEFAULT_SCAN_INTERVAL,
        10,
        3600,
        "invalid_scan_interval",
    )

    mqtt_host = _text(
        data,
        CONF_MQTT_HOST,
        MAX_MQTT_HOST_LENGTH,
        "invalid_mqtt_host",
    )
    if (
        any(char.isspace() for char in mqtt_host)
        or any(char in mqtt_host for char in "/\\")
    ):
        raise _InputError(CONF_MQTT_HOST, "invalid_mqtt_host")
    normalized[CONF_MQTT_HOST] = mqtt_host
    normalized[CONF_MQTT_PORT] = _integer(
        data,
        CONF_MQTT_PORT,
        DEFAULT_MQTT_PORT,
        1,
        65535,
        "invalid_mqtt_port",
    )

    mqtt_hub_id = _text(
        data,
        CONF_MQTT_HUB_ID,
        MAX_MQTT_HUB_ID_LENGTH,
        "invalid_mqtt_hub_id",
        topic_component=True,
    )
    if any(char.isspace() for char in mqtt_hub_id):
        raise _InputError(CONF_MQTT_HUB_ID, "invalid_mqtt_hub_id")
    normalized[CONF_MQTT_HUB_ID] = mqtt_hub_id

    stored_username = _username(existing) if existing is not None else None
    if existing is not None and CONF_MQTT_USERNAME not in data:
        username = stored_username
    else:
        username = _username(data)
    supplied_password = _password(data)
    if username is None and supplied_password is not None:
        raise _InputError(
            CONF_MQTT_PASSWORD, "mqtt_password_requires_username"
        )
    if username is None:
        password = None
    elif supplied_password is not None:
        password = supplied_password
    elif existing is not None and username == stored_username:
        stored = existing.get(CONF_MQTT_PASSWORD)
        password = stored if isinstance(stored, str) else None
    else:
        password = None
    normalized[CONF_MQTT_USERNAME] = username
    normalized[CONF_MQTT_PASSWORD] = password

    use_tls = _boolean(
        data, CONF_MQTT_USE_TLS, False, "invalid_mqtt_tls"
    )
    verify_tls = _boolean(
        data, CONF_MQTT_VERIFY_TLS, True, "invalid_mqtt_tls"
    )
    normalized[CONF_MQTT_USE_TLS] = use_tls
    normalized[CONF_MQTT_VERIFY_TLS] = verify_tls if use_tls else True
    normalized[CONF_MQTT_KEEPALIVE] = _integer(
        data,
        CONF_MQTT_KEEPALIVE,
        DEFAULT_MQTT_KEEPALIVE,
        1,
        65535,
        "invalid_mqtt_keepalive",
    )
    return normalized


def _api_schema(
    defaults: dict[str, Any] | None = None,
    *,
    reconfigure: bool = False,
) -> dict[Any, Any]:
    defaults = defaults or {}
    base_url = (
        vol.Required(CONF_BASE_URL, default=defaults[CONF_BASE_URL])
        if reconfigure
        else vol.Required(CONF_BASE_URL)
    )
    token = (
        vol.Optional(CONF_TOKEN)
        if reconfigure
        else vol.Required(CONF_TOKEN)
    )
    return {
        base_url: str,
        token: _PASSWORD_SELECTOR,
        vol.Required(
            CONF_VERIFY_SSL,
            default=defaults.get(CONF_VERIFY_SSL, True),
        ): bool,
    }


def _advanced_schema_fields(
    defaults: dict[str, Any] | None = None,
    *,
    redact_username: bool = False,
) -> dict[Any, Any]:
    defaults = defaults or {}
    username = (
        vol.Optional(CONF_MQTT_USERNAME)
        if redact_username
        else vol.Optional(
            CONF_MQTT_USERNAME,
            default=defaults.get(CONF_MQTT_USERNAME) or "",
        )
    )
    return {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ): int,
        vol.Required(
            CONF_MQTT_HOST,
            default=defaults.get(CONF_MQTT_HOST, ""),
        ): str,
        vol.Required(
            CONF_MQTT_PORT,
            default=defaults.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT),
        ): int,
        vol.Required(
            CONF_MQTT_HUB_ID,
            default=defaults.get(CONF_MQTT_HUB_ID, ""),
        ): str,
        username: str,
        vol.Optional(CONF_MQTT_PASSWORD): _PASSWORD_SELECTOR,
        vol.Optional(
            CONF_MQTT_USE_TLS,
            default=defaults.get(CONF_MQTT_USE_TLS, False),
        ): bool,
        vol.Optional(
            CONF_MQTT_VERIFY_TLS,
            default=defaults.get(CONF_MQTT_VERIFY_TLS, True),
        ): bool,
        vol.Optional(
            CONF_MQTT_KEEPALIVE,
            default=defaults.get(
                CONF_MQTT_KEEPALIVE, DEFAULT_MQTT_KEEPALIVE
            ),
        ): int,
    }


def _config_schema(
    defaults: dict[str, Any] | None = None,
    *,
    reconfigure: bool = False,
) -> vol.Schema:
    fields = _api_schema(defaults, reconfigure=reconfigure)
    fields.update(
        _advanced_schema_fields(defaults, redact_username=reconfigure)
    )
    return vol.Schema(fields)


def _api_failure_code(error: Exception) -> str:
    """Map only a proven HTTP authentication rejection specially."""
    if (
        isinstance(error, GritHubApiError)
        and getattr(error, "http_status", None) == 401
    ):
        return "invalid_auth"
    return "cannot_connect"

def _valid_authenticated_hub(value: Any) -> bool:
    """Require a non-empty sanitized object from the authenticated route."""
    return isinstance(value, dict) and bool(value)


class GritHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure GRIT REST and discover bounded MQTT settings."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._pending_api: dict[str, Any] | None = None
        self._advanced_defaults: dict[str, Any] = {}

    async def _async_discover_installation(
        self,
        api_config: dict[str, Any],
        hub: dict[str, Any] | None,
    ):
        rest = extract_rest_mqtt_discovery([hub])

        defaults: dict[str, Any] = {
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_MQTT_HOST: rest.host or "",
            CONF_MQTT_PORT: DEFAULT_MQTT_PORT,
            CONF_MQTT_HUB_ID: rest.hub_id or "",
            CONF_MQTT_USERNAME: None,
            CONF_MQTT_PASSWORD: None,
            CONF_MQTT_USE_TLS: False,
            CONF_MQTT_VERIFY_TLS: True,
            CONF_MQTT_KEEPALIVE: DEFAULT_MQTT_KEEPALIVE,
        }

        probe = None
        if rest.host is not None and rest.hub_id is not None:
            cancel_event = threading.Event()
            try:
                probe = await self.hass.async_add_executor_job(
                    partial(
                        passive_mqtt_discover,
                        rest.host,
                        DEFAULT_MQTT_PORT,
                        timeout=MQTT_DISCOVERY_TIMEOUT,
                        expected_hub_id=rest.hub_id,
                        username=DEFAULT_MQTT_USERNAME,
                        password=DEFAULT_MQTT_PASSWORD,
                        use_tls=False,
                        verify_tls=True,
                        keepalive=DEFAULT_MQTT_KEEPALIVE,
                        cancel_event=cancel_event,
                    )
                )
            except asyncio.CancelledError:
                cancel_event.set()
                raise
            except Exception:
                probe = None

        self._pending_api = api_config
        self._advanced_defaults = defaults
        if probe is not None and probe.connected:
            return await self.async_step_confirm()
        return await self.async_step_advanced()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._pending_api = None
            self._advanced_defaults = {}
            try:
                normalized = _normalize_api_config(user_input)
            except _InputError as err:
                errors[err.field] = err.code
            else:
                await self.async_set_unique_id(normalized[CONF_BASE_URL])
                self._abort_if_unique_id_configured()
                api = GritHubApiClient(
                    self.hass,
                    normalized[CONF_BASE_URL],
                    normalized[CONF_TOKEN],
                    normalized[CONF_VERIFY_SSL],
                )
                try:
                    hub = await api.get_hub()
                    if not _valid_authenticated_hub(hub):
                        raise GritHubApiError(
                            "Authenticated hub response is invalid"
                        )
                except asyncio.CancelledError:
                    raise
                except GritHubApiError as err:
                    errors["base"] = _api_failure_code(err)
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    return await self._async_discover_installation(
                        normalized,
                        hub,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(_api_schema()),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        if self._pending_api is None:
            return await self.async_step_user()
        if user_input is not None:
            if user_input.get(_CONF_SHOW_ADVANCED) is True:
                return await self.async_step_advanced()
            combined = {**self._pending_api, **self._advanced_defaults}
            normalized = _normalize_config(combined)
            return self.async_create_entry(title="GRIT Hub", data=normalized)

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Optional(_CONF_SHOW_ADVANCED, default=False): bool}
            ),
            description_placeholders={
                "mqtt_host": self._advanced_defaults[CONF_MQTT_HOST],
                "mqtt_hub_id": self._advanced_defaults[CONF_MQTT_HUB_ID],
            },
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ):
        if self._pending_api is None:
            return await self.async_step_user()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                normalized = _normalize_config(
                    {**self._pending_api, **user_input}
                )
            except _InputError as err:
                errors[err.field] = err.code
            else:
                return self.async_create_entry(
                    title="GRIT Hub",
                    data=normalized,
                )
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                _advanced_schema_fields(self._advanced_defaults)
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ):
        entry = self._get_reconfigure_entry()
        defaults = dict(entry.data)
        defaults[CONF_SCAN_INTERVAL] = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                normalized = _normalize_config(
                    user_input, existing=entry.data
                )
            except _InputError as err:
                errors[err.field] = err.code
            else:
                api = GritHubApiClient(
                    self.hass,
                    normalized[CONF_BASE_URL],
                    normalized[CONF_TOKEN],
                    normalized[CONF_VERIFY_SSL],
                )
                try:
                    hub = await api.get_hub()
                    if not _valid_authenticated_hub(hub):
                        raise GritHubApiError(
                            "Authenticated hub response is invalid"
                        )
                except asyncio.CancelledError:
                    raise
                except GritHubApiError as err:
                    errors["base"] = _api_failure_code(err)
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=normalized,
                        options_updates={
                            CONF_SCAN_INTERVAL: normalized[CONF_SCAN_INTERVAL]
                        },
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_config_schema(defaults, reconfigure=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GritHubOptionsFlow(config_entry)


class GritHubOptionsFlow(config_entries.OptionsFlow):
    """Configure polling options."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(
                        int,
                        vol.Range(min=10, max=3600),
                    )
                }
            ),
        )

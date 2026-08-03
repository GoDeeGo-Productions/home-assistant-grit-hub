"""GRIT Hub integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Mapping, NoReturn

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)

from .api import GritHubApiClient, GritHubApiError
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
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_MQTT_HOST_LENGTH,
    MAX_MQTT_HUB_ID_LENGTH,
    MAX_MQTT_USERNAME_LENGTH,
    MQTT_READY_TIMEOUT,
    PLATFORMS,
)
from .coordinator import GritHubCoordinator
from .mqtt_live import GritLiveMqtt

_LOGGER = logging.getLogger(__name__)

SERVICE_DEVICE_COMMAND = "device_command"
SERVICE_REFRESH_DEVICE = "refresh_device"
SERVICE_LOCATE_DEVICE = "locate_device"

_MQTT_CONFIG_ERROR = (
    "MQTT configuration is invalid; reconfigure this GRIT Hub entry"
)
_MQTT_NOT_READY_ERROR = "MQTT connection is not ready"


@dataclass(frozen=True, slots=True)
class _MqttSettings:
    """Validated MQTT settings retained only for client construction."""

    host: str
    port: int
    hub_id: str
    username: str | None
    password: str | None
    use_tls: bool
    verify_tls: bool
    keepalive: int


@dataclass(slots=True)
class GritHubRuntimeData:
    """Runtime objects for one config entry."""

    api: GritHubApiClient
    coordinator: GritHubCoordinator
    mqtt: GritLiveMqtt
    active: bool = True
    unloading: bool = False
    mqtt_stopped: bool = False
    ready_future: asyncio.Future[bool] | None = None


def _invalid_mqtt_config() -> ConfigEntryError:
    return ConfigEntryError(_MQTT_CONFIG_ERROR)


def _required_mqtt_text(
    data: Mapping[str, Any],
    key: str,
    maximum: int,
    *,
    topic_component: bool = False,
) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise _invalid_mqtt_config()
    value = value.strip()
    if (
        not value
        or len(value) > maximum
        or not value.isprintable()
        or any(char.isspace() for char in value)
        or (topic_component and any(char in value for char in "/+#"))
    ):
        raise _invalid_mqtt_config()
    return value


def _required_mqtt_integer(
    data: Mapping[str, Any],
    key: str,
) -> int:
    value = data.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 65535
    ):
        raise _invalid_mqtt_config()
    return value


def _required_mqtt_boolean(
    data: Mapping[str, Any],
    key: str,
) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise _invalid_mqtt_config()
    return value


def _validate_mqtt_settings(
    data: Mapping[str, Any],
) -> _MqttSettings:
    """Validate stored MQTT values before any API or MQTT network work."""
    host = _required_mqtt_text(
        data,
        CONF_MQTT_HOST,
        MAX_MQTT_HOST_LENGTH,
    )
    if any(char in host for char in "/\\"):
        raise _invalid_mqtt_config()
    hub_id = _required_mqtt_text(
        data,
        CONF_MQTT_HUB_ID,
        MAX_MQTT_HUB_ID_LENGTH,
        topic_component=True,
    )
    port = _required_mqtt_integer(data, CONF_MQTT_PORT)
    keepalive = _required_mqtt_integer(data, CONF_MQTT_KEEPALIVE)
    use_tls = _required_mqtt_boolean(data, CONF_MQTT_USE_TLS)
    verify_tls = _required_mqtt_boolean(data, CONF_MQTT_VERIFY_TLS)

    username_value = data.get(CONF_MQTT_USERNAME)
    if username_value is None:
        username = None
    elif not isinstance(username_value, str):
        raise _invalid_mqtt_config()
    else:
        username = username_value.strip() or None
        if username is not None and (
            len(username) > MAX_MQTT_USERNAME_LENGTH
            or not username.isprintable()
        ):
            raise _invalid_mqtt_config()

    password_value = data.get(CONF_MQTT_PASSWORD)
    if password_value is None:
        password = None
    elif not isinstance(password_value, str) or len(password_value) > 4096:
        raise _invalid_mqtt_config()
    else:
        password = password_value if password_value.strip() else None
    if password is not None and username is None:
        raise _invalid_mqtt_config()
    if username is None and password is None:
        username = DEFAULT_MQTT_USERNAME
        password = DEFAULT_MQTT_PASSWORD

    return _MqttSettings(
        host=host,
        port=port,
        hub_id=hub_id,
        username=username,
        password=password,
        use_tls=use_tls,
        verify_tls=verify_tls,
        keepalive=keepalive,
    )


def _apply_mqtt_message(
    runtime: GritHubRuntimeData,
    hub_id: str,
    device_type: str,
    device_id: str,
    message_type: str,
    payload: dict[str, Any],
) -> None:
    """Apply a scheduled MQTT message only while this runtime is active."""
    if (
        not runtime.active
        or runtime.unloading
        or not runtime.coordinator.mqtt_connected
    ):
        return
    runtime.coordinator.handle_mqtt_message(
        hub_id,
        device_type,
        device_id,
        message_type,
        payload,
    )


def _apply_mqtt_connection_state(
    runtime: GritHubRuntimeData,
    connected: bool,
) -> None:
    """Apply a scheduled broker state and complete initial readiness."""
    if not runtime.active or runtime.unloading:
        return
    changed = runtime.coordinator.set_mqtt_connected(connected)
    if connected and changed:
        runtime.coordinator.start_state_reconciliation()
    ready_future = runtime.ready_future
    if ready_future is not None and not ready_future.done():
        ready_future.set_result(connected)


def _remove_compatibility_storage(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: GritHubRuntimeData,
) -> None:
    entries = hass.data.get(DOMAIN)
    if not isinstance(entries, dict):
        return
    stored = entries.get(entry.entry_id)
    if (
        isinstance(stored, dict)
        and stored.get("coordinator") is runtime.coordinator
    ):
        entries.pop(entry.entry_id, None)


def _clear_runtime_data(
    entry: ConfigEntry,
    runtime: GritHubRuntimeData,
) -> None:
    if getattr(entry, "runtime_data", None) is runtime:
        entry.runtime_data = None


async def _stop_runtime(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: GritHubRuntimeData,
    *,
    unloading: bool,
) -> None:
    """Deactivate callbacks, stop MQTT off-loop, and clear stored references."""
    runtime.active = False
    runtime.unloading = unloading
    ready_future = runtime.ready_future
    runtime.ready_future = None
    if ready_future is not None and not ready_future.done():
        ready_future.cancel()

    try:
        await runtime.coordinator.async_stop_state_reconciliation()
    finally:
        try:
            if not runtime.mqtt_stopped:
                runtime.mqtt_stopped = True
                await hass.async_add_executor_job(runtime.mqtt.stop)
        finally:
            _remove_compatibility_storage(hass, entry, runtime)
            _clear_runtime_data(entry, runtime)


async def _unload_partial_platforms(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Best-effort rollback after platform forwarding has begun."""
    try:
        unloaded = await hass.config_entries.async_unload_platforms(
            entry,
            PLATFORMS,
        )
    except Exception:
        _LOGGER.warning("GRIT platform rollback failed")
    else:
        if not unloaded:
            _LOGGER.warning("GRIT platform rollback was incomplete")


async def _raise_mqtt_not_ready(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: GritHubRuntimeData,
) -> NoReturn:
    await _stop_runtime(
        hass,
        entry,
        runtime,
        unloading=False,
    )
    raise ConfigEntryNotReady(_MQTT_NOT_READY_ERROR) from None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up GRIT REST discovery, then prove MQTT readiness."""
    existing_runtime = getattr(entry, "runtime_data", None)
    if (
        isinstance(existing_runtime, GritHubRuntimeData)
        and existing_runtime.active
        and not existing_runtime.unloading
    ):
        return True

    settings = _validate_mqtt_settings(entry.data)

    api = GritHubApiClient(
        hass,
        entry.data[CONF_BASE_URL],
        entry.data[CONF_TOKEN],
        entry.data.get(CONF_VERIFY_SSL, True),
    )
    coordinator = GritHubCoordinator(
        hass,
        api,
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ),
        expected_mqtt_hub_id=settings.hub_id,
    )
    await coordinator.async_config_entry_first_refresh()

    runtime: GritHubRuntimeData

    def mqtt_message_callback(
        hub_id: str,
        device_type: str,
        device_id: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        hass.loop.call_soon_threadsafe(
            _apply_mqtt_message,
            runtime,
            hub_id,
            device_type,
            device_id,
            message_type,
            payload,
        )

    def mqtt_connection_state_callback(connected: bool) -> None:
        hass.loop.call_soon_threadsafe(
            _apply_mqtt_connection_state,
            runtime,
            connected,
        )

    mqtt = GritLiveMqtt(
        settings.host,
        settings.port,
        mqtt_message_callback,
        username=settings.username,
        password=settings.password,
        keepalive=settings.keepalive,
        use_tls=settings.use_tls,
        verify_tls=settings.verify_tls,
        connection_state_callback=mqtt_connection_state_callback,
    )
    runtime = GritHubRuntimeData(
        api=api,
        coordinator=coordinator,
        mqtt=mqtt,
        ready_future=hass.loop.create_future(),
    )

    try:
        started = await hass.async_add_executor_job(mqtt.start)
    except asyncio.CancelledError:
        await _stop_runtime(
            hass,
            entry,
            runtime,
            unloading=False,
        )
        raise
    except Exception:
        await _raise_mqtt_not_ready(hass, entry, runtime)
    if not started:
        await _raise_mqtt_not_ready(hass, entry, runtime)

    try:
        ready = await asyncio.wait_for(
            asyncio.shield(runtime.ready_future),
            timeout=MQTT_READY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await _raise_mqtt_not_ready(hass, entry, runtime)
    except asyncio.CancelledError:
        await _stop_runtime(
            hass,
            entry,
            runtime,
            unloading=False,
        )
        raise
    if not ready or not coordinator.mqtt_connected:
        await _raise_mqtt_not_ready(hass, entry, runtime)
    runtime.ready_future = None

    forwarding_started = False
    try:
        entry.runtime_data = runtime
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "coordinator": coordinator
        }
        forwarding_started = True
        await hass.config_entries.async_forward_entry_setups(
            entry,
            PLATFORMS,
        )
        _register_services(hass)
    except asyncio.CancelledError:
        try:
            if forwarding_started:
                await _unload_partial_platforms(hass, entry)
        finally:
            await _stop_runtime(
                hass,
                entry,
                runtime,
                unloading=False,
            )
        raise
    except Exception:
        try:
            if forwarding_started:
                await _unload_partial_platforms(hass, entry)
        finally:
            await _stop_runtime(
                hass,
                entry,
                runtime,
                unloading=False,
            )
        raise

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload platforms before deactivating and stopping MQTT."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if not unload_ok:
        return False

    runtime = getattr(entry, "runtime_data", None)
    if isinstance(runtime, GritHubRuntimeData):
        await _stop_runtime(
            hass,
            entry,
            runtime,
            unloading=True,
        )
    else:
        entries = hass.data.get(DOMAIN)
        if isinstance(entries, dict):
            entries.pop(entry.entry_id, None)
    return True


def _first_api(hass: HomeAssistant) -> GritHubApiClient:
    return _first_coordinator(hass).api


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

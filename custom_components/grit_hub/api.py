"""Async client for the GRIT Hub API."""
from __future__ import annotations

import asyncio
import math
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import bearer_authorization_value, validate_bearer_token
from .const import REST_DISCOVERY_TIMEOUT
from .hub import normalize_hub_id, sanitize_hub_data


class GritHubApiError(Exception):
    """Raised when the GRIT Hub API returns a safe, bounded error."""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class GritHubApiClient:
    """Small, defensive async API client for GRIT Hub."""

    def __init__(self, hass, base_url: str, token: str, verify_ssl: bool = True) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.token = validate_bearer_token(token)
        self.verify_ssl = verify_ssl
        self.session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": bearer_authorization_value(self.token),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 20,
    ) -> Any:
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self.base_url}{path}"
        endpoint = endpoint_identifier(path)
        try:
            async with self.session.request(
                method.upper(),
                url,
                headers=self.headers,
                json=json,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 400:
                    raise GritHubApiError(
                        f"{method.upper()} {endpoint} failed: HTTP {resp.status}",
                        http_status=resp.status,
                    )
                text = await resp.text()
                if not text:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype.lower():
                    return await resp.json(content_type=None)
                return text
        except asyncio.TimeoutError as err:
            raise GritHubApiError(f"{method.upper()} {endpoint} timed out") from err
        except aiohttp.ClientError as err:
            raise GritHubApiError(
                f"{method.upper()} {endpoint} failed due to a client error"
            ) from err

    async def health_check(self) -> Any:
        # Prefer API health check, then fall back to root.
        try:
            return await self.request("GET", "/health-check", timeout=10)
        except GritHubApiError:
            return await self.request("GET", "/", timeout=10)

    async def get_hub(self) -> dict[str, Any] | None:
        """Read the documented current-hub response and sanitize it."""
        data = await self.request(
            "GET",
            "/api/hub",
            timeout=REST_DISCOVERY_TIMEOUT,
        )
        return sanitize_hub_data(data)

    async def set_gritlock(self, locked: bool) -> Any:
        """Set system-wide GRITLock through the bounded lockout route."""
        if not isinstance(locked, bool):
            raise GritHubApiError("GRITLock state is invalid")
        return await self.request(
            "PUT",
            "/api/hub/lockout",
            json={"state": locked},
            timeout=REST_DISCOVERY_TIMEOUT,
        )

    async def set_system_led_brightness(
        self,
        hub_id: str,
        brightness: int,
    ) -> Any:
        """Update only the documented system LED brightness setting."""
        normalized_hub_id = normalize_hub_id(hub_id)
        if normalized_hub_id is None:
            raise GritHubApiError("Hub identifier is invalid")
        if (
            isinstance(brightness, bool)
            or not isinstance(brightness, int)
            or not 0 <= brightness <= 100
        ):
            raise GritHubApiError("System LED brightness is invalid")
        return await self.request(
            "PUT",
            f"/api/hub/{quote(normalized_hub_id)}/settings",
            json={"systemLedBrightness": brightness},
            timeout=REST_DISCOVERY_TIMEOUT,
        )

    async def restart_service(self) -> Any:
        """Restart the GRIT service without accepting arbitrary input."""
        return await self.request(
            "PUT",
            "/api/hub/restart",
            timeout=REST_DISCOVERY_TIMEOUT,
        )

    async def reboot_hub(self) -> Any:
        """Reboot the hub without accepting arbitrary input."""
        return await self.request(
            "PUT",
            "/api/hub/reboot",
            timeout=REST_DISCOVERY_TIMEOUT,
        )

    async def get_collection(self, device_type: str) -> list[dict[str, Any]]:
        data = await self.request("GET", f"/api/{quote(device_type)}")
        items = normalise_list(data)
        sanitized = [
            sanitize_device_data(item, device_type=device_type)
            for item in items
        ]
        return [item for item in sanitized if item]

    async def get_rfid_device(self, device_id: str) -> dict[str, Any]:
        """Read and strictly sanitize one RFID reader detail response."""
        if not isinstance(device_id, str):
            raise GritHubApiError("RFID device identifier is invalid")
        normalized_id = device_id.strip()
        if (
            not normalized_id
            or normalized_id in {".", ".."}
            or len(normalized_id) > 128
            or not normalized_id.isprintable()
        ):
            raise GritHubApiError("RFID device identifier is invalid")
        data = await self.request(
            "GET",
            f"/api/rfid/{quote(normalized_id, safe='')}",
            timeout=REST_DISCOVERY_TIMEOUT,
        )
        return sanitize_rfid_device_data(data)

    async def get_collector_device(self, device_id: str) -> dict[str, Any]:
        """Read and strictly sanitize one collector detail response."""
        if not isinstance(device_id, str):
            raise GritHubApiError("Collector device identifier is invalid")
        normalized_id = device_id.strip()
        if (
            not normalized_id
            or normalized_id in {".", ".."}
            or len(normalized_id) > 128
            or not normalized_id.isprintable()
        ):
            raise GritHubApiError("Collector device identifier is invalid")
        data = await self.request(
            "GET",
            f"/api/collector/{quote(normalized_id, safe='')}",
            timeout=REST_DISCOVERY_TIMEOUT,
        )
        return sanitize_collector_device_data(data)

    async def request_device_telemetry(
        self,
        device_type: str,
        device_id: str,
    ) -> None:
        """Request current telemetry for one gate or RFID reader."""
        if device_type not in {"gate", "rfid"}:
            raise GritHubApiError("Telemetry device type is invalid")
        if not isinstance(device_id, str):
            raise GritHubApiError("Telemetry device identifier is invalid")
        normalized_id = device_id.strip()
        if (
            not normalized_id
            or normalized_id in {".", ".."}
            or len(normalized_id) > 128
            or not normalized_id.isprintable()
        ):
            raise GritHubApiError("Telemetry device identifier is invalid")
        response = await self.request(
            "POST",
            "/api/device/mesh-telemetry/refresh/"
            f"{quote(device_type, safe='')}/{quote(normalized_id, safe='')}",
            timeout=REST_DISCOVERY_TIMEOUT,
        )
        if not isinstance(response, dict) or response.get("success") is not True:
            raise GritHubApiError("Telemetry refresh request failed")

    async def set_device_state(self, device_type: str, device_id: str | int, on: bool) -> Any:
        value = "true" if on else "false"
        # Most controllable GRIT devices use state/{onOff}. Some endpoints use
        # a semantic open boolean; the caller maps that for covers.
        return await self.request("PUT", f"/api/{quote(device_type)}/{quote(str(device_id))}/state/{value}")

    async def call_command(
        self,
        device_type: str,
        device_id: str | int,
        command_name: str,
        action: str,
        remote_type: str = "api",
    ) -> Any:
        return await self.request(
            "PUT",
            f"/api/command/{quote(device_type)}/{quote(str(device_id))}/{quote(command_name)}/{quote(action)}/{quote(remote_type)}",
        )

    async def refresh_device(self, device_type: str, device_id: str | int) -> Any:
        return await self.request("GET", f"/api/device/refresh/{quote(device_type)}/{quote(str(device_id))}")

    async def locate_device(self, device_type: str, device_id: str | int) -> Any:
        return await self.request("GET", f"/api/device/locate/{quote(device_type)}/{quote(str(device_id))}")


def endpoint_identifier(path: str) -> str:
    """Return a bounded endpoint label without query values or object IDs."""
    segments = [segment for segment in path.split("?", 1)[0].split("/") if segment]
    if not segments:
        return "/"
    visible_count = 2 if segments[0].lower() == "api" else 1
    visible = segments[:visible_count]
    suffix = "/*" if len(segments) > len(visible) else ""
    return f"/{'/'.join(visible)}{suffix}"


_DEVICE_IDENTIFIER_FIELDS = (
    "id",
    "deviceId",
    "deviceID",
    "_id",
    "uuid",
    "key",
    "serialNumber",
    "serial",
    "deviceIdentifier",
)
_DEVICE_NAME_FIELDS = ("name", "displayName", "label", "description", "deviceName")
_DEVICE_STATE_FIELDS = (
    "status",
    "state",
    "mode",
    "on",
    "onOff",
    "enabled",
    "active",
    "open",
    "locked",
    "isOn",
)
_DEVICE_BOOLEAN_FIELDS = ("gritLockEnabled", "gritLockState")
_MAX_DEVICE_TEXT_LENGTH = 128


def _bounded_device_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or len(value) > _MAX_DEVICE_TEXT_LENGTH
        or not value.isprintable()
    ):
        return None
    return value


def sanitize_device_data(
    value: Any,
    *,
    device_type: str | None = None,
) -> dict[str, Any]:
    """Retain only bounded fields required by existing entities and commands."""
    if not isinstance(value, dict):
        return {}

    sanitized: dict[str, Any] = {}
    for field in _DEVICE_IDENTIFIER_FIELDS:
        raw = value.get(field)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            sanitized[field] = raw
            continue
        text = _bounded_device_text(raw)
        if text is not None:
            sanitized[field] = text

    for field in _DEVICE_NAME_FIELDS:
        text = _bounded_device_text(value.get(field))
        if text is not None:
            sanitized[field] = text

    for field in _DEVICE_STATE_FIELDS:
        if device_type in {"rfid", "collector"} and field == "state":
            continue
        raw = value.get(field)
        if isinstance(raw, bool) or isinstance(raw, int):
            sanitized[field] = raw
        elif isinstance(raw, float) and math.isfinite(raw):
            sanitized[field] = raw
        else:
            text = _bounded_device_text(raw)
            if text is not None:
                sanitized[field] = text

    for field in _DEVICE_BOOLEAN_FIELDS:
        raw = value.get(field)
        if isinstance(raw, bool):
            sanitized[field] = raw

    return sanitized


def sanitize_rfid_device_data(value: Any) -> dict[str, Any]:
    """Retain only fields required from one RFID detail response."""
    if not isinstance(value, dict):
        return {}

    sanitized: dict[str, Any] = {}
    identifier = value.get("id")
    if isinstance(identifier, int) and not isinstance(identifier, bool):
        sanitized["id"] = identifier
    else:
        text_id = _bounded_device_text(identifier)
        if text_id is not None:
            sanitized["id"] = text_id

    state = value.get("state")
    if isinstance(state, bool):
        sanitized["state"] = state

    online = value.get("onlineStatus")
    if isinstance(online, bool):
        sanitized["onlineStatus"] = online

    for field in ("name", "displayName", "version"):
        text = _bounded_device_text(value.get(field))
        if text is not None:
            sanitized[field] = text

    return sanitized


def sanitize_collector_device_data(value: Any) -> dict[str, Any]:
    """Retain only strict fields required from one collector detail response."""
    if not isinstance(value, dict):
        return {}

    sanitized: dict[str, Any] = {}
    identifier = value.get("id")
    if isinstance(identifier, int) and not isinstance(identifier, bool):
        sanitized["id"] = identifier
    else:
        text_id = _bounded_device_text(identifier)
        if text_id is not None:
            sanitized["id"] = text_id

    for field in (
        "state",
        "stateChanging",
        "stateChangingTo",
        "onlineStatus",
        "isOnline",
    ):
        field_value = value.get(field)
        if isinstance(field_value, bool):
            sanitized[field] = field_value

    for field in ("name", "displayName", "version"):
        text = _bounded_device_text(value.get(field))
        if text is not None:
            sanitized[field] = text

    return sanitized


def normalise_list(data: Any) -> list[dict[str, Any]]:
    """Convert common API list shapes into a list of dictionaries."""
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "data", "results", "devices", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def obj_id(obj: dict[str, Any]) -> str | int | None:
    for key in ("id", "deviceId", "deviceID", "_id", "uuid", "key"):
        if obj.get(key) not in (None, ""):
            return obj[key]
    return None


def obj_name(obj: dict[str, Any], fallback: str) -> str:
    for key in ("name", "displayName", "label", "description", "serialNumber", "deviceName"):
        if obj.get(key):
            return str(obj[key])
    ident = obj_id(obj)
    return f"{fallback} {ident}" if ident is not None else fallback


def bool_state(obj: dict[str, Any]) -> bool | None:
    for key in ("on", "onOff", "enabled", "active", "open", "locked", "state", "status", "isOn"):
        if key in obj:
            value = obj[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"on", "open", "enabled", "active", "true", "1", "unlocked", "online"}:
                    return True
                if lowered in {"off", "closed", "disabled", "inactive", "false", "0", "locked", "offline"}:
                    return False
    return None

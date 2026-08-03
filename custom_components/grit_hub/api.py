"""Async client for the GRIT Hub API."""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import REST_DISCOVERY_TIMEOUT
from .hub import normalize_hub_id, sanitize_hub_data


class GritHubApiError(Exception):
    """Raised when the GRIT Hub API returns an error."""


class GritHubApiClient:
    """Small, defensive async API client for GRIT Hub."""

    def __init__(self, hass, base_url: str, token: str, verify_ssl: bool = True) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_ssl = verify_ssl
        self.session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
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
                text = await resp.text()
                if resp.status >= 400:
                    raise GritHubApiError(
                        f"{method.upper()} {endpoint} failed: HTTP {resp.status}"
                    )
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
            "/api/hub/1",
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
        return normalise_list(data)

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

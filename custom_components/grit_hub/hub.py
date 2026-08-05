"""Sanitized hub data and system-wide GRITLock state helpers."""
from __future__ import annotations

from ipaddress import ip_address
import re
from typing import Any

_HUB_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{32}$")
_MAX_HUB_TEXT_LENGTH = 128


def normalize_hub_id(value: Any) -> str | None:
    """Return a documented 32-character hexadecimal hub identifier."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _HUB_ID_PATTERN.fullmatch(value) else None


def normalize_ethernet_ip(value: Any) -> str | None:
    """Return a canonical IP address without accepting hostnames."""
    if not isinstance(value, str):
        return None
    try:
        return str(ip_address(value.strip()))
    except ValueError:
        return None


def _bounded_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or len(value) > _MAX_HUB_TEXT_LENGTH
        or not value.isprintable()
    ):
        return None
    return value


def sanitize_hub_data(value: Any) -> dict[str, Any] | None:
    """Retain only the documented v0.1.0 hub fields."""
    if not isinstance(value, dict):
        return None

    sanitized: dict[str, Any] = {}
    hub_id = normalize_hub_id(value.get("id"))
    if hub_id is not None:
        sanitized["id"] = hub_id

    for field in ("displayName", "name", "hubVersion", "branch"):
        text = _bounded_text(value.get(field))
        if text is not None:
            sanitized[field] = text

    ethernet_ip = normalize_ethernet_ip(value.get("ipAddressEthernet"))
    if ethernet_ip is not None:
        sanitized["ipAddressEthernet"] = ethernet_ip

    for field in ("connectedToInternet", "disableHubButtons"):
        field_value = value.get(field)
        if isinstance(field_value, bool):
            sanitized[field] = field_value

    brightness = value.get("systemLedBrightness")
    if (
        not isinstance(brightness, bool)
        and isinstance(brightness, int)
        and 0 <= brightness <= 100
    ):
        sanitized["systemLedBrightness"] = brightness

    if "automaticGritLockTime" in value:
        lock_time = value.get("automaticGritLockTime")
        if lock_time is None:
            sanitized["automaticGritLockTime"] = None
        else:
            text = _bounded_text(lock_time)
            if text is not None:
                sanitized["automaticGritLockTime"] = text

    return sanitized

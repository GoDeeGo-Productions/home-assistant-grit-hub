"""Data update coordinator for GRIT Hub."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Any, Callable

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GritHubApiClient, GritHubApiError
from .const import DEVICE_TYPES, DOMAIN, SWITCH_DEVICE_TYPES

_LOGGER = logging.getLogger(__name__)
MQTT_STATE_KEY = "_grit_mqtt"

_IDENTIFIER_KEYS = (
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
_MAX_IDENTIFIER_LENGTH = 128
_MAX_MESSAGE_TYPE_LENGTH = 128
_MAX_FIRMWARE_LENGTH = 128
_MAX_SOURCE_SEQUENCE = (1 << 63) - 1
_ORDERING_CATEGORIES = ("gate", "state", "online", "rssi", "firmware")
_FIELD_CATEGORIES = {
    "position": "gate",
    "open": "gate",
    "state": "state",
    "online": "online",
    "rssi": "rssi",
    "firmware_version": "firmware",
}
_STATE_FIELDS = tuple(_FIELD_CATEGORIES)
_INVALID = object()


def _bounded_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > maximum or not value.isprintable():
        return None
    return value


def _normalize_identifier(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return _bounded_text(str(value), _MAX_IDENTIFIER_LENGTH)


def _normalize_message_type(value: Any) -> str | None:
    return _bounded_text(value, _MAX_MESSAGE_TYPE_LENGTH)


def _strict_bool(value: Any) -> bool | object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "on", "open", "1"}:
            return True
        if normalized in {"false", "off", "closed", "0"}:
            return False
    return _INVALID


def _bounded_number(value: Any, minimum: float, maximum: float) -> int | float | object:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _INVALID
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return _INVALID
    if not finite or not minimum <= value <= maximum:
        return _INVALID
    return value


def _firmware(value: Any) -> str | object:
    bounded = _bounded_text(value, _MAX_FIRMWARE_LENGTH)
    return bounded if bounded is not None else _INVALID


def _source_sequence(value: Any) -> int | object:
    if isinstance(value, bool):
        return _INVALID
    if isinstance(value, int):
        sequence = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        sequence = int(value)
    else:
        return _INVALID
    if not 0 <= sequence <= _MAX_SOURCE_SEQUENCE:
        return _INVALID
    return sequence


def _source_timestamp(value: Any) -> datetime | object:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and len(value) <= 64:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return _INVALID
    else:
        return _INVALID
    try:
        offset = parsed.utcoffset()
    except (OverflowError, TypeError, ValueError):
        return _INVALID
    if parsed.tzinfo is None or offset is None:
        return _INVALID
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return _INVALID


def _first_valid(
    payload: dict[str, Any],
    aliases: tuple[str, ...],
    converter: Callable[[Any], Any],
) -> Any:
    for key in aliases:
        if key not in payload:
            continue
        converted = converter(payload[key])
        if converted is not _INVALID:
            return converted
    return _INVALID


def _ordering_value(
    payload: dict[str, Any],
    aliases: tuple[str, ...],
    converter: Callable[[Any], Any],
) -> tuple[bool, Any]:
    for key in aliases:
        if key in payload:
            return True, converter(payload[key])
    return False, None


def _device_identifiers(device: Any) -> set[str]:
    if not isinstance(device, dict):
        return set()
    identifiers: set[str] = set()
    for key in _IDENTIFIER_KEYS:
        normalized = _normalize_identifier(device.get(key))
        if normalized is not None:
            identifiers.add(normalized)
    return identifiers


def _sanitize_mqtt_state(value: Any) -> dict[str, Any] | None:
    """Return a bounded copy of persisted MQTT state."""
    if not isinstance(value, dict):
        return None

    sanitized: dict[str, Any] = {}
    for field in _STATE_FIELDS:
        if field not in value:
            continue
        raw = value[field]
        if field in {"open", "state", "online"}:
            converted = _strict_bool(raw)
        elif field == "position":
            converted = _bounded_number(raw, 0, 100)
        elif field == "rssi":
            converted = _bounded_number(raw, -200, 0)
        else:
            converted = _firmware(raw)
        if converted is not _INVALID:
            sanitized[field] = converted

    message_type = _normalize_message_type(value.get("last_message_type"))
    if message_type is not None:
        sanitized["last_message_type"] = message_type

    received_at = _source_timestamp(value.get("last_received_at"))
    if received_at is not _INVALID:
        sanitized["last_received_at"] = received_at

    source_sequence = _source_sequence(value.get("source_sequence"))
    if source_sequence is not _INVALID:
        sanitized["source_sequence"] = source_sequence

    source_timestamp = _source_timestamp(value.get("source_timestamp"))
    if source_timestamp is not _INVALID:
        sanitized["source_timestamp"] = source_timestamp

    raw_ordering = value.get("_ordering")
    ordering: dict[str, dict[str, Any]] = {}
    if isinstance(raw_ordering, dict):
        for category in _ORDERING_CATEGORIES:
            raw_marker = raw_ordering.get(category)
            if not isinstance(raw_marker, dict):
                continue
            marker: dict[str, Any] = {}
            sequence = _source_sequence(raw_marker.get("source_sequence"))
            if sequence is not _INVALID:
                marker["source_sequence"] = sequence
            timestamp = _source_timestamp(raw_marker.get("source_timestamp"))
            if timestamp is not _INVALID:
                marker["source_timestamp"] = timestamp
            if marker:
                ordering[category] = marker
    if ordering:
        sanitized["_ordering"] = ordering

    return sanitized or None


def _preserve_mqtt_state(
    previous_devices: Any, refreshed_devices: dict[str, Any]
) -> None:
    """Transfer sanitized state only across unique same-type identities."""
    if not isinstance(previous_devices, dict):
        previous_devices = {}

    for device_type, refreshed_collection in refreshed_devices.items():
        if not isinstance(refreshed_collection, list):
            continue
        previous_collection = previous_devices.get(device_type, [])
        if not isinstance(previous_collection, list):
            previous_collection = []

        previous_counts = Counter(
            identifier
            for device in previous_collection
            for identifier in _device_identifiers(device)
        )
        refreshed_counts = Counter(
            identifier
            for device in refreshed_collection
            for identifier in _device_identifiers(device)
        )

        for refreshed in refreshed_collection:
            if not isinstance(refreshed, dict):
                continue
            refreshed.pop(MQTT_STATE_KEY, None)
            unique_ids = {
                identifier
                for identifier in _device_identifiers(refreshed)
                if previous_counts[identifier] == 1
                and refreshed_counts[identifier] == 1
            }
            if not unique_ids:
                continue
            candidates = [
                previous
                for previous in previous_collection
                if isinstance(previous, dict)
                and unique_ids.intersection(_device_identifiers(previous))
            ]
            if len(candidates) != 1:
                continue
            state = _sanitize_mqtt_state(candidates[0].get(MQTT_STATE_KEY))
            if state is not None:
                refreshed[MQTT_STATE_KEY] = state


def _payload_state(
    device_type: str, message_type: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Extract only explicitly allowed fields from one decoded MQTT object."""
    updates: dict[str, Any] = {}
    root_message_type = message_type.split("/", 1)[0].lower()

    if device_type == "gate":
        position = _first_valid(
            payload, ("p", "position"), lambda value: _bounded_number(value, 0, 100)
        )
        if position is not _INVALID:
            updates["position"] = position

        open_aliases = ("open", "state")
        if root_message_type == "s":
            open_aliases += ("s",)
        open_state = _first_valid(payload, open_aliases, _strict_bool)
        if open_state is not _INVALID:
            updates["open"] = open_state
        elif position is not _INVALID:
            if position >= 75:
                updates["open"] = True
            elif position <= 65:
                updates["open"] = False

    state_message_types = (
        {"s", "st", "sts"} if device_type == "rfid" else {"s", "st", "gl", "gls"}
    )
    if (
        device_type in SWITCH_DEVICE_TYPES
        and root_message_type in state_message_types
    ):
        state = _first_valid(payload, ("s", "state"), _strict_bool)
        if state is not _INVALID:
            updates["state"] = state

    online = _first_valid(
        payload,
        ("onlineStatus", "online", "connected", "available", "sts"),
        _strict_bool,
    )
    if online is not _INVALID:
        updates["online"] = online

    rssi = _first_valid(
        payload, ("rssi",), lambda value: _bounded_number(value, -200, 0)
    )
    if rssi is not _INVALID:
        updates["rssi"] = rssi

    firmware = _first_valid(
        payload,
        ("firmware_version", "firmwareVersion", "av", "version"),
        _firmware,
    )
    if firmware is not _INVALID:
        updates["firmware_version"] = firmware

    return updates or None



class GritHubCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch hub data and accept sanitized, already-parsed MQTT state."""

    def __init__(
        self,
        hass,
        api: GritHubApiClient,
        scan_interval: int,
        expected_mqtt_hub_id: Any | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self._expected_mqtt_hub_id = (
            None
            if expected_mqtt_hub_id is None
            else _normalize_identifier(expected_mqtt_hub_id)
        )
        if (
            expected_mqtt_hub_id is not None
            and self._expected_mqtt_hub_id is None
        ):
            raise ValueError("expected MQTT hub identifier is invalid")

    async def _async_update_data(self) -> dict[str, Any]:
        previous_devices = (
            self.data.get("devices", {}) if isinstance(self.data, dict) else {}
        )
        data: dict[str, Any] = {
            "devices": {},
            "hub": None,
            "health": None,
            "errors": {},
        }
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

        _preserve_mqtt_state(previous_devices, data["devices"])
        return data

    def handle_mqtt_message(
        self,
        hub_id: Any,
        device_type: Any,
        device_id: Any,
        message_type: Any,
        payload: Any,
    ) -> bool:
        """Apply one already-parsed MQTT message without retaining raw input."""
        if self._expected_mqtt_hub_id is None:
            _LOGGER.debug(
                "GRIT MQTT message rejected: hub identity is not configured"
            )
            return False

        normalized_hub_id = _normalize_identifier(hub_id)
        normalized_device_id = _normalize_identifier(device_id)
        normalized_message_type = _normalize_message_type(message_type)
        if (
            normalized_hub_id != self._expected_mqtt_hub_id
            or normalized_device_id is None
            or normalized_message_type is None
            or not isinstance(device_type, str)
            or device_type not in DEVICE_TYPES
            or not isinstance(payload, dict)
        ):
            _LOGGER.debug(
                "GRIT MQTT message rejected: invalid routing or payload"
            )
            return False

        if not isinstance(self.data, dict):
            _LOGGER.debug(
                "GRIT MQTT message rejected: coordinator data is unavailable"
            )
            return False
        devices = self.data.get("devices")
        if not isinstance(devices, dict):
            _LOGGER.debug(
                "GRIT MQTT message rejected: coordinator data is unavailable"
            )
            return False
        collection = devices.get(device_type)
        if not isinstance(collection, list):
            _LOGGER.debug(
                "GRIT MQTT message rejected: device collection is unavailable"
            )
            return False

        matches = [
            (index, device)
            for index, device in enumerate(collection)
            if normalized_device_id in _device_identifiers(device)
        ]
        if len(matches) != 1:
            _LOGGER.debug(
                "GRIT MQTT message rejected: device identity is not unique"
            )
            return False

        sequence_present, source_sequence = _ordering_value(
            payload,
            ("source_sequence", "sequence", "seq"),
            _source_sequence,
        )
        timestamp_present, source_timestamp = _ordering_value(
            payload,
            ("source_timestamp", "timestamp", "ts"),
            _source_timestamp,
        )
        if (
            (sequence_present and source_sequence is _INVALID)
            or (timestamp_present and source_timestamp is _INVALID)
        ):
            _LOGGER.debug(
                "GRIT MQTT message rejected: invalid ordering metadata"
            )
            return False

        updates = _payload_state(
            device_type, normalized_message_type, payload
        )
        if updates is None:
            _LOGGER.debug(
                "GRIT MQTT message rejected: no supported state"
            )
            return False

        index, device = matches[0]
        previous_state = (
            _sanitize_mqtt_state(device.get(MQTT_STATE_KEY)) or {}
        )
        categories = {_FIELD_CATEGORIES[field] for field in updates}
        previous_ordering = previous_state.get("_ordering", {})
        if not isinstance(previous_ordering, dict):
            previous_ordering = {}

        for category in categories:
            marker = previous_ordering.get(category, {})
            if not isinstance(marker, dict):
                continue
            previous_sequence = marker.get("source_sequence")
            previous_timestamp = marker.get("source_timestamp")
            if (
                sequence_present
                and previous_sequence is not None
                and source_sequence <= previous_sequence
            ):
                _LOGGER.debug(
                    "GRIT MQTT message rejected: update is not newer"
                )
                return False
            if (
                timestamp_present
                and previous_timestamp is not None
                and source_timestamp <= previous_timestamp
            ):
                _LOGGER.debug(
                    "GRIT MQTT message rejected: update is not newer"
                )
                return False

        same_values = all(
            previous_state.get(field, _INVALID) == value
            for field, value in updates.items()
        )
        same_ordering = (
            (not sequence_present)
            or previous_state.get("source_sequence") == source_sequence
        ) and (
            (not timestamp_present)
            or previous_state.get("source_timestamp") == source_timestamp
        )
        if (
            same_values
            and same_ordering
            and previous_state.get("last_message_type")
            == normalized_message_type
        ):
            _LOGGER.debug("GRIT MQTT message ignored: duplicate state")
            return False

        next_state = dict(previous_state)
        next_state.update(updates)
        next_state["last_message_type"] = normalized_message_type
        next_state["last_received_at"] = datetime.now(timezone.utc)
        if sequence_present:
            next_state["source_sequence"] = source_sequence
        else:
            next_state.pop("source_sequence", None)
        if timestamp_present:
            next_state["source_timestamp"] = source_timestamp
        else:
            next_state.pop("source_timestamp", None)

        next_ordering = {
            category: dict(marker)
            for category, marker in previous_ordering.items()
            if category in _ORDERING_CATEGORIES and isinstance(marker, dict)
        }
        for category in categories:
            marker: dict[str, Any] = {}
            if sequence_present:
                marker["source_sequence"] = source_sequence
            if timestamp_present:
                marker["source_timestamp"] = source_timestamp
            # Without source metadata, arrival order is the only available order.
            if marker:
                next_ordering[category] = marker
            else:
                next_ordering.pop(category, None)
        if next_ordering:
            next_state["_ordering"] = next_ordering
        else:
            next_state.pop("_ordering", None)

        next_data = dict(self.data)
        next_devices = dict(devices)
        next_collection = list(collection)
        next_device = dict(device)
        next_device[MQTT_STATE_KEY] = next_state
        next_collection[index] = next_device
        next_devices[device_type] = next_collection
        next_data["devices"] = next_devices
        self.async_set_updated_data(next_data)
        return True

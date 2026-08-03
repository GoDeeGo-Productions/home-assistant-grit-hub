"""Data update coordinator for GRIT Hub."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
import time
from typing import Any, Callable

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GritHubApiClient, GritHubApiError
from .const import (
    DEVICE_TYPES,
    DOMAIN,
    REST_DISCOVERY_TIMEOUT,
    SWITCH_DEVICE_TYPES,
)
from .hub import derive_gritlock_state

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
_LOCAL_RECEIVE_SEQUENCE_KEY = "_receive_sequence"
_FIELD_OBSERVATIONS_KEY = "_field_observations"

_RECONCILIATION_DEVICE_TYPES = ("gate", "rfid")
_COMMAND_STATE_FIELDS = {
    "gate": "open",
    "rfid": "state",
}
_LIVE_STATE_FIELDS = {
    "gate": ("position", "open"),
    "rfid": ("state",),
}
_RECONCILIATION_CONCURRENCY = 4
_RECONCILIATION_MAX_TARGETS = 64
_RECONCILIATION_MAX_PASSES = 2
_RECONCILIATION_PASS_TIMEOUT = REST_DISCOVERY_TIMEOUT * 3
_MAX_CONFIRM_TIMEOUT = REST_DISCOVERY_TIMEOUT * 6
_GRITLOCK_SETTLE_TIME = 0.25
_MAX_GRITLOCK_OBSERVATIONS = 64
_MAX_MQTT_STATE_WAITERS = 64

_INVALID = object()


@dataclass(frozen=True, slots=True)
class _GritlockObservation:
    """One bounded authoritative trigger /gl observation."""

    participating: bool
    locked: bool
    receive_sequence: int
    received_monotonic: float


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


def _strict_binary_bool(value: Any) -> bool | object:
    """Accept only boolean or integer 0/1 device-state fields."""
    if isinstance(value, bool):
        return value
    return bool(value) if isinstance(value, int) and value in (0, 1) else _INVALID


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


def _local_receive_sequence(value: Any) -> int | object:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return _INVALID
    return value


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


def _telemetry_identifier(device: Any) -> str | None:
    """Return the documented mesh-device ID used by the telemetry route."""
    if not isinstance(device, dict):
        return None
    return _normalize_identifier(device.get("id"))


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


    received_at = _source_timestamp(value.get("last_received_at"))
    if received_at is not _INVALID:
        sanitized["last_received_at"] = received_at

    receive_sequence = _local_receive_sequence(
        value.get(_LOCAL_RECEIVE_SEQUENCE_KEY)
    )
    if receive_sequence is not _INVALID:
        sanitized[_LOCAL_RECEIVE_SEQUENCE_KEY] = receive_sequence

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

    raw_observations = value.get(_FIELD_OBSERVATIONS_KEY)
    observations: dict[str, int] = {}
    if isinstance(raw_observations, dict):
        for field in _STATE_FIELDS:
            sequence = _local_receive_sequence(raw_observations.get(field))
            if sequence is not _INVALID:
                observations[field] = sequence
    if observations:
        sanitized[_FIELD_OBSERVATIONS_KEY] = observations

    return sanitized or None


def _preserve_mqtt_state(
    previous_devices: Any,
    refreshed_devices: dict[str, Any],
) -> None:
    """Transfer sanitized MQTT state across unique same-type identities."""
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

        live_fields = _LIVE_STATE_FIELDS.get(device_type)
        if live_fields is None:
            continue
        for previous in previous_collection:
            if not isinstance(previous, dict):
                continue
            state = _sanitize_mqtt_state(previous.get(MQTT_STATE_KEY))
            if state is None or not any(
                field in state for field in live_fields
            ):
                continue
            unique_ids = {
                identifier
                for identifier in _device_identifiers(previous)
                if previous_counts[identifier] == 1
            }
            if not unique_ids or any(
                refreshed_counts[identifier] > 0
                for identifier in unique_ids
            ):
                continue

            preserved: dict[str, Any] = {}
            for key in _IDENTIFIER_KEYS:
                identifier = _normalize_identifier(previous.get(key))
                if identifier in unique_ids:
                    preserved[key] = identifier
            if not preserved:
                continue
            preserved[MQTT_STATE_KEY] = state
            refreshed_collection.append(preserved)


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

    if device_type == "rfid" and root_message_type in {"s", "st"}:
        state = _first_valid(payload, ("s", "state"), _strict_bool)
        if state is not _INVALID:
            updates["state"] = state
    elif (
        device_type in SWITCH_DEVICE_TYPES
        and root_message_type in {"s", "st", "gl", "gls"}
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
        self._mqtt_connected = False
        self._mqtt_connection_generation = 0
        self._mqtt_receive_sequence = 0
        self._refresh_sequence = 0
        self._hub_update_sequence = 0
        self._gritlock_update_sequence = 0
        self._gritlock_observations: dict[
            str, _GritlockObservation
        ] = {}
        self._gritlock_mqtt_authoritative = False
        self._reconciliation_task: asyncio.Task[None] | None = None
        self._reconcile_again = False
        self._reconciliation_enabled = True
        self._telemetry_request_tasks: dict[
            tuple[str, str], asyncio.Task[None]
        ] = {}
        self._telemetry_request_waiters: dict[tuple[str, str], int] = {}
        self._mqtt_state_waiters: set[asyncio.Future[None]] = set()
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

    @property
    def mqtt_connected(self) -> bool:
        """Return whether MQTT is connected and subscribed."""
        return self._mqtt_connected

    @property
    def hub_data(self) -> dict[str, Any]:
        """Return only the API client's sanitized hub allowlist."""
        if not isinstance(self.data, dict):
            return {}
        hub = self.data.get("hub")
        return hub if isinstance(hub, dict) else {}

    @property
    def hub_id(self) -> str | None:
        """Return the stable documented hub identifier when available."""
        value = self.hub_data.get("id")
        if isinstance(value, str):
            return value
        return self._expected_mqtt_hub_id

    @property
    def gritlock_state(self) -> bool | None:
        """Return MQTT consensus, or provisional REST startup evidence."""
        if self._gritlock_mqtt_authoritative:
            states = {
                observation.locked
                for observation in self._gritlock_observations.values()
                if observation.participating
            }
            return next(iter(states)) if len(states) == 1 else None
        devices = (
            self.data.get("devices")
            if isinstance(self.data, dict)
            else None
        )
        return derive_gritlock_state(devices)

    @property
    def gritlock_participating_trigger_ids(self) -> frozenset[str]:
        """Return the bounded currently known MQTT participation set."""
        return frozenset(
            trigger_id
            for trigger_id, observation in self._gritlock_observations.items()
            if observation.participating
        )

    @property
    def refresh_sequence(self) -> int:
        """Return the most recently started REST refresh generation."""
        return self._refresh_sequence

    @property
    def mqtt_receive_sequence(self) -> int:
        """Return the latest accepted local MQTT observation sequence."""
        return self._mqtt_receive_sequence

    @property
    def hub_update_sequence(self) -> int:
        """Return the last generation with a valid current-hub response."""
        return self._hub_update_sequence

    @property
    def gritlock_update_sequence(self) -> int:
        """Return the last generation with a successful trigger read."""
        return self._gritlock_update_sequence

    def set_mqtt_connected(self, connected: bool) -> bool:
        """Update broker state on the event loop and notify once per change."""
        if not isinstance(connected, bool):
            raise TypeError("MQTT connection state must be a boolean")
        if self._mqtt_connected == connected:
            return False
        self._mqtt_connection_generation += 1
        self._mqtt_connected = connected
        if not connected:
            self.cancel_state_reconciliation()
            self._gritlock_observations.clear()
            self._wake_mqtt_state_waiters()
        self.async_update_listeners()
        return True

    def _wake_mqtt_state_waiters(self) -> None:
        """Wake bounded state waiters without retaining message details."""
        for waiter in tuple(self._mqtt_state_waiters):
            if not waiter.done():
                waiter.set_result(None)

    def start_state_reconciliation(self) -> bool:
        """Start or coalesce one gate/RFID telemetry reconciliation pass."""
        if not self._reconciliation_enabled or not self._mqtt_connected:
            return False
        task = self._reconciliation_task
        if task is not None and not task.done():
            self._reconcile_again = True
            return False
        self._reconcile_again = False
        self._reconciliation_task = asyncio.create_task(
            self._async_reconciliation_loop()
        )
        return True

    def cancel_state_reconciliation(self) -> None:
        """Cancel any in-flight telemetry reconciliation pass."""
        self._reconcile_again = False
        task = self._reconciliation_task
        if task is not None and not task.done():
            task.cancel()

    async def async_stop_state_reconciliation(self) -> None:
        """Cancel and await telemetry work during unload or failed setup."""
        self._reconciliation_enabled = False
        self.cancel_state_reconciliation()
        task = self._reconciliation_task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        telemetry_tasks = tuple(set(self._telemetry_request_tasks.values()))
        for telemetry_task in telemetry_tasks:
            if not telemetry_task.done():
                telemetry_task.cancel()
        if telemetry_tasks:
            await asyncio.gather(*telemetry_tasks, return_exceptions=True)
        self._telemetry_request_tasks.clear()
        self._telemetry_request_waiters.clear()
        self._gritlock_observations.clear()
        self._wake_mqtt_state_waiters()

    async def _async_reconciliation_loop(self) -> None:
        current_task = asyncio.current_task()
        try:
            for _ in range(_RECONCILIATION_MAX_PASSES):
                if (
                    not self._reconciliation_enabled
                    or not self._mqtt_connected
                ):
                    break
                self._reconcile_again = False
                reconciled = await self._async_request_device_telemetry()
                if not reconciled:
                    _LOGGER.warning(
                        "GRIT device state reconciliation was incomplete"
                    )
                if not self._reconcile_again:
                    break
            self._reconcile_again = False
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.warning("GRIT device state reconciliation failed")
        finally:
            if self._reconciliation_task is current_task:
                restart = (
                    self._reconcile_again
                    and self._reconciliation_enabled
                    and self._mqtt_connected
                )
                self._reconciliation_task = None
                self._reconcile_again = False
                if restart:
                    self.start_state_reconciliation()

    async def _async_request_device_telemetry(self) -> bool:
        """Request current telemetry for every known gate and RFID reader."""
        data = self.data if isinstance(self.data, dict) else {}
        devices = data.get("devices")
        if not isinstance(devices, dict):
            return False

        targets: list[tuple[str, str]] = []
        for device_type in _RECONCILIATION_DEVICE_TYPES:
            collection = devices.get(device_type)
            if not isinstance(collection, list):
                continue
            identifiers = [
                _telemetry_identifier(device) for device in collection
            ]
            counts = Counter(
                identifier
                for identifier in identifiers
                if identifier is not None
            )
            targets.extend(
                (device_type, identifier)
                for identifier in identifiers
                if identifier is not None and counts[identifier] == 1
            )

        truncated = len(targets) > _RECONCILIATION_MAX_TARGETS
        targets = targets[:_RECONCILIATION_MAX_TARGETS]
        semaphore = asyncio.Semaphore(_RECONCILIATION_CONCURRENCY)

        async def request_one(
            device_type: str,
            device_id: str,
        ) -> bool:
            async with semaphore:
                try:
                    await self._async_request_target_telemetry(
                        device_type,
                        device_id,
                        cancel_if_unshared=True,
                    )
                except Exception:
                    return False
                return True

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        request_one(device_type, device_id)
                        for device_type, device_id in targets
                    )
                ),
                timeout=_RECONCILIATION_PASS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return False
        return not truncated and all(results)

    async def _async_request_target_telemetry(
        self,
        device_type: str,
        device_id: str,
        *,
        cancel_if_unshared: bool = False,
    ) -> None:
        """Coalesce one bounded telemetry request for a supported target."""
        key = (device_type, device_id)
        task = self._telemetry_request_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(
                self.api.request_device_telemetry(device_type, device_id)
            )
            self._telemetry_request_tasks[key] = task

            def discard(completed: asyncio.Task[None]) -> None:
                if self._telemetry_request_tasks.get(key) is completed:
                    self._telemetry_request_tasks.pop(key, None)

            task.add_done_callback(discard)
        self._telemetry_request_waiters[key] = (
            self._telemetry_request_waiters.get(key, 0) + 1
        )
        cancelled = False
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            remaining = self._telemetry_request_waiters.get(key, 1) - 1
            if remaining <= 0:
                self._telemetry_request_waiters.pop(key, None)
                should_cancel = (
                    cancel_if_unshared or not self._reconciliation_enabled
                )
                if cancelled and should_cancel and not task.done():
                    task.cancel()
            else:
                self._telemetry_request_waiters[key] = remaining

    def _mqtt_field_observation(
        self,
        device_type: str,
        device_id: str,
        field: str,
        after_sequence: int,
    ) -> Any:
        """Return a field only when MQTT observed it after the boundary."""
        data = self.data if isinstance(self.data, dict) else {}
        devices = data.get("devices")
        if not isinstance(devices, dict):
            return _INVALID
        collection = devices.get(device_type)
        if not isinstance(collection, list):
            return _INVALID
        matches = [
            device
            for device in collection
            if device_id in _device_identifiers(device)
        ]
        if len(matches) != 1:
            return _INVALID
        state = _sanitize_mqtt_state(matches[0].get(MQTT_STATE_KEY))
        if state is None:
            return _INVALID
        observations = state.get(_FIELD_OBSERVATIONS_KEY)
        if not isinstance(observations, dict):
            return _INVALID
        observed_sequence = _local_receive_sequence(observations.get(field))
        if (
            observed_sequence is _INVALID
            or observed_sequence <= after_sequence
        ):
            return _INVALID
        return state.get(field, _INVALID)

    async def async_confirm_device_state(
        self,
        device_type: str,
        device_id: Any,
        expected: bool,
        *,
        after_sequence: int,
        timeout: float,
    ) -> bool:
        """Request telemetry and require a newer matching MQTT observation."""
        field = _COMMAND_STATE_FIELDS.get(device_type)
        normalized_id = _normalize_identifier(device_id)
        if (
            field is None
            or normalized_id is None
            or not isinstance(expected, bool)
            or _local_receive_sequence(after_sequence) is _INVALID
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= _MAX_CONFIRM_TIMEOUT
        ):
            return False

        connection_generation = self._mqtt_connection_generation

        def confirmation_result() -> bool | None:
            observation = self._mqtt_field_observation(
                device_type,
                normalized_id,
                field,
                after_sequence,
            )
            if observation is expected:
                return True
            if device_type == "rfid" and observation is not _INVALID:
                return False
            return None

        async def request_and_wait() -> bool:
            if (
                not self._reconciliation_enabled
                or not self._mqtt_connected
                or self._mqtt_connection_generation != connection_generation
            ):
                return False
            await self._async_request_target_telemetry(
                device_type,
                normalized_id,
            )
            while (
                self._reconciliation_enabled
                and self._mqtt_connected
                and self._mqtt_connection_generation == connection_generation
            ):
                result = confirmation_result()
                if result is not None:
                    return result
                if len(self._mqtt_state_waiters) >= _MAX_MQTT_STATE_WAITERS:
                    return False
                waiter = asyncio.get_running_loop().create_future()
                self._mqtt_state_waiters.add(waiter)
                try:
                    result = confirmation_result()
                    if result is not None:
                        return result
                    await waiter
                finally:
                    self._mqtt_state_waiters.discard(waiter)
            return False

        try:
            return await asyncio.wait_for(request_and_wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False

    async def async_confirm_gritlock_state(
        self,
        expected: bool,
        *,
        after_sequence: int,
        known_participants: frozenset[str] | set[str],
        timeout: float,
    ) -> bool:
        """Require a fresh settled authoritative trigger /gl consensus."""
        if (
            not isinstance(expected, bool)
            or _local_receive_sequence(after_sequence) is _INVALID
            or not isinstance(known_participants, (frozenset, set))
            or len(known_participants) > _MAX_GRITLOCK_OBSERVATIONS
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= _MAX_CONFIRM_TIMEOUT
        ):
            return False
        normalized_known = frozenset(
            _normalize_identifier(trigger_id)
            for trigger_id in known_participants
        )
        if None in normalized_known or len(normalized_known) != len(
            known_participants
        ):
            return False

        connection_generation = self._mqtt_connection_generation

        def evaluate() -> tuple[bool | None, float | None]:
            fresh = {
                trigger_id: observation
                for trigger_id, observation in self._gritlock_observations.items()
                if observation.receive_sequence > after_sequence
            }
            participating = {
                trigger_id: observation
                for trigger_id, observation in fresh.items()
                if observation.participating
            }
            if any(
                observation.locked is not expected
                for observation in participating.values()
            ):
                return False, None
            if not participating:
                return None, None
            if normalized_known and not normalized_known.issubset(fresh):
                return None, None
            latest_received = max(
                observation.received_monotonic
                for observation in fresh.values()
            )
            quiet_remaining = _GRITLOCK_SETTLE_TIME - (
                time.monotonic() - latest_received
            )
            if quiet_remaining > 0:
                return None, quiet_remaining
            return True, None

        async def wait_for_consensus() -> bool:
            while (
                self._reconciliation_enabled
                and self._mqtt_connected
                and self._mqtt_connection_generation == connection_generation
            ):
                outcome, quiet_remaining = evaluate()
                if outcome is not None:
                    return outcome
                if len(self._mqtt_state_waiters) >= _MAX_MQTT_STATE_WAITERS:
                    return False
                waiter = asyncio.get_running_loop().create_future()
                self._mqtt_state_waiters.add(waiter)
                try:
                    outcome, quiet_remaining = evaluate()
                    if outcome is not None:
                        return outcome
                    if quiet_remaining is None:
                        await waiter
                    else:
                        try:
                            await asyncio.wait_for(
                                waiter,
                                timeout=quiet_remaining,
                            )
                        except asyncio.TimeoutError:
                            pass
                finally:
                    self._mqtt_state_waiters.discard(waiter)
            return False

        try:
            return await asyncio.wait_for(
                wait_for_consensus(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return False

    def _apply_gritlock_observation(
        self,
        trigger_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Apply only strict bounded trigger /gl consensus fields."""
        participating = _strict_binary_bool(payload.get("gte", _INVALID))
        locked = _strict_binary_bool(payload.get("gls", _INVALID))
        if participating is _INVALID or locked is _INVALID:
            _LOGGER.debug(
                "GRIT MQTT message rejected: invalid GRITLock state"
            )
            return False
        if (
            trigger_id not in self._gritlock_observations
            and len(self._gritlock_observations)
            >= _MAX_GRITLOCK_OBSERVATIONS
        ):
            _LOGGER.debug(
                "GRIT MQTT message rejected: GRITLock state limit reached"
            )
            return False

        self._gritlock_mqtt_authoritative = True
        self._mqtt_receive_sequence += 1
        self._gritlock_observations[trigger_id] = _GritlockObservation(
            participating=participating,
            locked=locked,
            receive_sequence=self._mqtt_receive_sequence,
            received_monotonic=time.monotonic(),
        )
        self.async_update_listeners()
        self._wake_mqtt_state_waiters()
        return True

    async def _async_update_data(self) -> dict[str, Any]:
        self._refresh_sequence += 1
        refresh_sequence = self._refresh_sequence
        hub_refreshed = False
        triggers_refreshed = False
        previous_data = self.data if isinstance(self.data, dict) else {}
        previous_devices = previous_data.get("devices", {})
        previous_hub = previous_data.get("hub")
        data: dict[str, Any] = {
            "devices": {},
            "hub": previous_hub if isinstance(previous_hub, dict) else None,
            "health": None,
            "errors": {},
        }
        try:
            await self.api.health_check()
            data["health"] = {"reachable": True}
        except GritHubApiError as err:
            raise UpdateFailed(str(err)) from err

        try:
            refreshed_hub = await self.api.get_hub()
            if isinstance(refreshed_hub, dict) and refreshed_hub:
                data["hub"] = refreshed_hub
                hub_refreshed = True
        except GritHubApiError as err:
            data["errors"]["hub"] = str(err)

        for dev_type in DEVICE_TYPES:
            try:
                data["devices"][dev_type] = await self.api.get_collection(
                    dev_type
                )
                if dev_type == "trigger":
                    triggers_refreshed = True
            except GritHubApiError as err:
                previous_collection = previous_devices.get(dev_type, [])
                if (
                    dev_type in _RECONCILIATION_DEVICE_TYPES
                    and isinstance(previous_collection, list)
                ):
                    data["devices"][dev_type] = [
                        dict(device)
                        for device in previous_collection
                        if isinstance(device, dict)
                    ]
                else:
                    data["devices"][dev_type] = []
                data["errors"][dev_type] = str(err)

        latest_data = self.data if isinstance(self.data, dict) else previous_data
        latest_devices = latest_data.get("devices", previous_devices)
        _preserve_mqtt_state(
            latest_devices,
            data["devices"],
        )
        if hub_refreshed:
            self._hub_update_sequence = refresh_sequence
        if triggers_refreshed:
            self._gritlock_update_sequence = refresh_sequence
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

        if device_type == "trigger" and normalized_message_type.lower() == "gl":
            return self._apply_gritlock_observation(
                normalized_device_id, payload
            )

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
                previous_sequence is not None
                and (
                    not sequence_present
                    or source_sequence <= previous_sequence
                )
            ):
                _LOGGER.debug(
                    "GRIT MQTT message rejected: update is not newer"
                )
                return False
            if (
                previous_timestamp is not None
                and (
                    not timestamp_present
                    or source_timestamp <= previous_timestamp
                )
            ):
                _LOGGER.debug(
                    "GRIT MQTT message rejected: update is not newer"
                )
                return False

        next_state = dict(previous_state)
        next_state.update(updates)
        self._mqtt_receive_sequence += 1
        next_state[_LOCAL_RECEIVE_SEQUENCE_KEY] = (
            self._mqtt_receive_sequence
        )

        next_state["last_received_at"] = datetime.now(timezone.utc)
        if sequence_present:
            next_state["source_sequence"] = source_sequence
        else:
            next_state.pop("source_sequence", None)
        if timestamp_present:
            next_state["source_timestamp"] = source_timestamp
        else:
            next_state.pop("source_timestamp", None)

        previous_observations = previous_state.get(
            _FIELD_OBSERVATIONS_KEY,
            {},
        )
        next_observations = (
            dict(previous_observations)
            if isinstance(previous_observations, dict)
            else {}
        )
        for field in updates:
            next_observations[field] = self._mqtt_receive_sequence
        next_state[_FIELD_OBSERVATIONS_KEY] = next_observations

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
        self._wake_mqtt_state_waiters()
        return True

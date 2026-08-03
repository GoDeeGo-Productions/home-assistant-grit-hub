"""Bounded installation discovery for GRIT REST and MQTT settings."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
import threading
import time
from typing import Any, Iterable

from .const import (
    DEFAULT_MQTT_PORT,
    MAX_MQTT_HOST_LENGTH,
    MAX_MQTT_HUB_ID_LENGTH,
)
from .hub import normalize_ethernet_ip, normalize_hub_id
from .mqtt_live import (
    MAX_MQTT_TOPIC_COMPONENT_LENGTH,
    MAX_MQTT_TOPIC_LENGTH,
    MQTT_QOS,
    MQTT_TOPIC,
)

_LOGGER = logging.getLogger(__name__)

_CANCEL_POLL_INTERVAL = 0.05


@dataclass(frozen=True, slots=True)
class RestMqttDiscovery:
    """MQTT candidates derived only from documented current-hub fields."""

    host: str | None = None
    port: int | None = None
    hub_id: str | None = None
    use_tls: bool | None = None


@dataclass(frozen=True, slots=True)
class MqttProbeResult:
    """Result of one bounded passive broker probe."""

    connected: bool
    hub_id: str | None = None
    ambiguous: bool = False


def _valid_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or len(value) > MAX_MQTT_HOST_LENGTH
        or not value.isprintable()
        or any(char.isspace() for char in value)
        or any(char in value for char in "/\\")
    ):
        return None
    return value


def _valid_hub_id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value).strip()
    if (
        not value
        or len(value) > MAX_MQTT_HUB_ID_LENGTH
        or not value.isprintable()
        or any(char.isspace() for char in value)
        or any(char in value for char in "/+#")
    ):
        return None
    return value


def _valid_port(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= 65535 else None


def extract_rest_mqtt_discovery(
    payloads: Iterable[Any],
) -> RestMqttDiscovery:
    """Map exact documented hub fields to the v0.1.0 MQTT defaults."""
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        return RestMqttDiscovery(
            host=normalize_ethernet_ip(payload.get("ipAddressEthernet")),
            port=DEFAULT_MQTT_PORT,
            hub_id=normalize_hub_id(payload.get("id")),
            use_tls=False,
        )
    return RestMqttDiscovery()


def _reason_code_is_success(reason_code: Any) -> bool:
    try:
        failure = getattr(reason_code, "is_failure")
    except Exception:
        failure = None
    if isinstance(failure, bool):
        return not failure
    try:
        return int(reason_code) == 0
    except Exception:
        return False


def _topic_hub_id(topic: Any) -> str | None:
    if not isinstance(topic, str) or len(topic) > MAX_MQTT_TOPIC_LENGTH:
        return None
    parts = topic.split("/")
    if (
        len(parts) < 5
        or parts[0] != "grit"
        or any(
            not part or len(part) > MAX_MQTT_TOPIC_COMPONENT_LENGTH
            for part in parts
        )
    ):
        return None
    return _valid_hub_id(parts[1])


def _create_client(mqtt: Any) -> Any:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=False,
        )
    except TypeError:
        try:
            return mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            return mqtt.Client(protocol=mqtt.MQTTv311)


def passive_mqtt_discover(
    host: str,
    port: int,
    *,
    timeout: float,
    expected_hub_id: str | None = None,
    username: str | None = None,
    password: str | None = None,
    use_tls: bool = False,
    verify_tls: bool = True,
    keepalive: int = 60,
    cancel_event: threading.Event | None = None,
) -> MqttProbeResult:
    """Perform one passive, subscription-only MQTT discovery attempt."""
    if _valid_host(host) is None:
        return MqttProbeResult(False)
    if _valid_port(port) is None:
        return MqttProbeResult(False)
    if expected_hub_id is not None:
        expected_hub_id = normalize_hub_id(expected_hub_id)
        if expected_hub_id is None:
            return MqttProbeResult(False)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= 30
        or isinstance(keepalive, bool)
        or not isinstance(keepalive, int)
        or not 1 <= keepalive <= 65535
        or not isinstance(use_tls, bool)
        or not isinstance(verify_tls, bool)
        or (username is not None and not isinstance(username, str))
        or (password is not None and not isinstance(password, str))
        or (password is not None and username is None)
        or (
            cancel_event is not None
            and not callable(getattr(cancel_event, "is_set", None))
        )
    ):
        return MqttProbeResult(False)
    if cancel_event is not None and cancel_event.is_set():
        return MqttProbeResult(False)

    topic_filter = (
        f"grit/{expected_hub_id}/+/+/#"
        if expected_hub_id is not None
        else MQTT_TOPIC
    )

    condition = threading.Condition()
    client: Any | None = None
    active = True
    subscribed = False
    subscription_mid: Any | None = None
    failed = False
    cancelled = False
    hub_ids: set[str] = set()
    loop_started = False

    def is_current(callback_client: Any) -> bool:
        with condition:
            return active and callback_client is client

    def on_connect(
        callback_client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        nonlocal failed, subscription_mid
        if not is_current(callback_client):
            return
        if not _reason_code_is_success(reason_code):
            with condition:
                if active and callback_client is client:
                    failed = True
                    condition.notify_all()
            return
        try:
            result, message_id = callback_client.subscribe(
                topic_filter,
                qos=MQTT_QOS,
            )
        except Exception:
            result = None
            message_id = None
        with condition:
            if not active or callback_client is not client:
                return
            if not _reason_code_is_success(result):
                failed = True
            else:
                subscription_mid = message_id
            condition.notify_all()

    def on_subscribe(
        callback_client: Any,
        _userdata: Any,
        message_id: Any,
        reason_codes: Any,
        _properties: Any = None,
    ) -> None:
        nonlocal subscribed, failed
        if not is_current(callback_client):
            return
        if isinstance(reason_codes, (list, tuple)):
            acknowledged = bool(reason_codes) and all(
                _reason_code_is_success(reason_code)
                for reason_code in reason_codes
            )
        else:
            acknowledged = _reason_code_is_success(reason_codes)
        with condition:
            if (
                not active
                or callback_client is not client
                or subscription_mid is None
                or message_id != subscription_mid
            ):
                return
            if acknowledged:
                subscribed = True
            else:
                failed = True
            condition.notify_all()

    def on_connect_fail(callback_client: Any, _userdata: Any) -> None:
        nonlocal failed
        with condition:
            if active and callback_client is client:
                failed = True
                condition.notify_all()

    def on_disconnect(
        callback_client: Any,
        _userdata: Any,
        _reason_code: Any,
        _properties: Any = None,
    ) -> None:
        nonlocal subscribed, failed
        with condition:
            if active and callback_client is client:
                subscribed = False
                failed = True
                condition.notify_all()

    def on_message(
        callback_client: Any,
        _userdata: Any,
        message: Any,
    ) -> None:
        nonlocal failed
        if not is_current(callback_client):
            return
        hub_id = _topic_hub_id(getattr(message, "topic", None))
        if hub_id is None:
            return
        with condition:
            if (
                not active
                or callback_client is not client
                or not subscribed
            ):
                return
            if (
                expected_hub_id is not None
                and hub_id != expected_hub_id
            ):
                failed = True
            else:
                hub_ids.add(hub_id)
            condition.notify_all()

    try:
        mqtt = importlib.import_module("paho.mqtt.client")
        client = _create_client(mqtt)
        client.on_connect = on_connect
        client.on_connect_fail = on_connect_fail
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.on_subscribe = on_subscribe
        client.connect_timeout = float(timeout)
        if username is not None:
            client.username_pw_set(username, password)
        if use_tls:
            client.tls_set()
            if not verify_tls:
                client.tls_insecure_set(True)
        connect_result = client.connect_async(
            host, port, keepalive=keepalive
        )
        if not _reason_code_is_success(connect_result):
            return MqttProbeResult(False)
        loop_started = True
        result = client.loop_start()
        if not _reason_code_is_success(result):
            return MqttProbeResult(False)

        deadline = time.monotonic() + float(timeout)
        with condition:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if failed:
                    break
                if expected_hub_id is not None and subscribed:
                    break
                if expected_hub_id is None and len(hub_ids) > 1:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                condition.wait(
                    min(remaining, _CANCEL_POLL_INTERVAL)
                    if cancel_event is not None
                    else remaining
                )
            connected = subscribed and not failed and not cancelled
            observed = set(hub_ids)

        if not connected:
            return MqttProbeResult(False)
        if expected_hub_id is not None:
            return MqttProbeResult(True, expected_hub_id)
        if len(observed) == 1:
            return MqttProbeResult(True, next(iter(observed)))
        return MqttProbeResult(True, ambiguous=len(observed) > 1)
    except Exception:
        _LOGGER.debug("GRIT MQTT discovery failed")
        return MqttProbeResult(False)
    finally:
        with condition:
            active = False
            condition.notify_all()
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            if loop_started:
                try:
                    client.loop_stop()
                except Exception:
                    pass

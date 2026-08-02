"""Small MQTT client for receiving live GRIT device updates.

Paho is imported only when :meth:`GritLiveMqtt.start` is called. Importing this
module or constructing the client does not load Paho or make a network
connection.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
import importlib
import json
import logging
import threading
from typing import Any, TypeAlias

_LOGGER = logging.getLogger(__name__)

MQTT_TOPIC = "grit/+/+/+/#"
MQTT_QOS = 0
MQTT_KEEPALIVE = 60
MAX_MQTT_PAYLOAD_SIZE = 65_536
MAX_MQTT_TOPIC_LENGTH = 512
MAX_MQTT_TOPIC_COMPONENT_LENGTH = 128

GritMqttMessageCallback: TypeAlias = Callable[
    [str, str, str, str, dict[str, Any]], None
]
GritMqttConnectionStateCallback: TypeAlias = Callable[[bool], None]


class _LifecycleState(Enum):
    """Internal MQTT client lifecycle states."""

    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()


class GritLiveMqtt:
    """Receive GRIT MQTT messages and pass parsed data to a callback."""

    def __init__(
        self,
        host: str,
        port: int,
        message_callback: GritMqttMessageCallback,
        *,
        username: str | None = None,
        password: str | None = None,
        keepalive: int = MQTT_KEEPALIVE,
        use_tls: bool = False,
        verify_tls: bool = True,
        connection_state_callback: GritMqttConnectionStateCallback | None = None,
    ) -> None:
        """Initialize connection settings without connecting to the broker."""
        if not isinstance(host, str) or not host.strip():
            raise ValueError("MQTT host must be a non-empty string")
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
        ):
            raise ValueError("MQTT port must be between 1 and 65535")
        if (
            isinstance(keepalive, bool)
            or not isinstance(keepalive, int)
            or not 1 <= keepalive <= 65535
        ):
            raise ValueError("MQTT keepalive must be between 1 and 65535")
        if not isinstance(use_tls, bool):
            raise TypeError("MQTT TLS setting must be a boolean")
        if not isinstance(verify_tls, bool):
            raise TypeError("MQTT TLS verification setting must be a boolean")
        if username is not None and not isinstance(username, str):
            raise TypeError("MQTT username must be a string or None")
        if password is not None and not isinstance(password, str):
            raise TypeError("MQTT password must be a string or None")
        if password is not None and username is None:
            raise ValueError("MQTT password requires a username")
        if not callable(message_callback):
            raise TypeError("MQTT message callback must be callable")
        if connection_state_callback is not None and not callable(
            connection_state_callback
        ):
            raise TypeError("MQTT connection-state callback must be callable")

        self._host = host.strip()
        self._port = port
        self._username = username
        self._password = password
        self._keepalive = keepalive
        self._use_tls = use_tls
        self._verify_tls = verify_tls
        self._message_callback = message_callback
        self._connection_state_callback = connection_state_callback

        self._client: Any | None = None
        self._network_loop_started = False
        self._connected = False
        self._reported_connection_state: bool | None = None
        self._state = _LifecycleState.STOPPED
        self._state_condition = threading.Condition()

    @property
    def connected(self) -> bool:
        """Return whether the broker connection and subscription are active."""
        with self._state_condition:
            return self._connected

    def start(self) -> bool:
        """Connect and start the Paho network loop once."""
        with self._state_condition:
            if self._state is not _LifecycleState.STOPPED:
                return False
            self._state = _LifecycleState.STARTING
            self._reported_connection_state = None

        client: Any | None = None
        loop_started = False
        try:
            mqtt = importlib.import_module("paho.mqtt.client")
            client = self._create_client(mqtt)

            with self._state_condition:
                cancelled = self._state is not _LifecycleState.STARTING
                if not cancelled:
                    self._client = client

            if cancelled:
                self._abort_start(client, loop_started)
                return False

            if self._username is not None:
                client.username_pw_set(self._username, self._password)

            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message

            if self._use_tls:
                client.tls_set()
                if not self._verify_tls:
                    client.tls_insecure_set(True)
            if self._start_was_cancelled(client):
                self._abort_start(client, loop_started)
                return False

            client.connect(self._host, self._port, keepalive=self._keepalive)

            if self._start_was_cancelled(client):
                self._abort_start(client, loop_started)
                return False

            loop_started = True
            client.loop_start()

            with self._state_condition:
                cancelled = (
                    self._state is not _LifecycleState.STARTING
                    or self._client is not client
                )
                if not cancelled:
                    self._network_loop_started = True
                    self._state = _LifecycleState.RUNNING
                    self._state_condition.notify_all()

            if cancelled:
                self._abort_start(client, loop_started)
                return False

            return True
        except Exception:  # Paho and socket implementations vary.
            with self._state_condition:
                cancelled = self._state is _LifecycleState.STOPPING
            if not cancelled:
                _LOGGER.error("GRIT MQTT client failed to start")
            self._abort_start(client, loop_started)
            return False

    def stop(self) -> None:
        """Disconnect and stop the network loop; repeated calls are safe."""
        with self._state_condition:
            if self._state is _LifecycleState.STOPPED:
                return

            if self._state is _LifecycleState.STOPPING:
                self._state_condition.wait_for(
                    lambda: self._state is _LifecycleState.STOPPED
                )
                return

            if self._state is _LifecycleState.STARTING:
                self._state = _LifecycleState.STOPPING
                self._connected = False
                self._state_condition.wait_for(
                    lambda: self._state is _LifecycleState.STOPPED
                )
                return

            self._state = _LifecycleState.STOPPING
            client = self._client
            loop_started = self._network_loop_started
            self._client = None
            self._network_loop_started = False
            self._connected = False

        if client is not None:
            self._close_client(client, loop_started)

        with self._state_condition:
            self._state = _LifecycleState.STOPPED
            self._state_condition.notify_all()

    def _start_was_cancelled(self, client: Any) -> bool:
        """Return whether stop was requested for the starting client."""
        with self._state_condition:
            return (
                self._state is not _LifecycleState.STARTING
                or self._client is not client
            )

    def _abort_start(self, client: Any | None, loop_started: bool) -> None:
        """Clean up a failed or cancelled start and release waiting stops."""
        with self._state_condition:
            if self._state is _LifecycleState.STARTING:
                self._state = _LifecycleState.STOPPING
            if self._client is client:
                self._client = None
            self._network_loop_started = False
            self._connected = False

        if client is not None:
            self._close_client(client, loop_started)

        with self._state_condition:
            self._state = _LifecycleState.STOPPED
            self._state_condition.notify_all()

    @staticmethod
    def _create_client(mqtt: Any) -> Any:
        """Create a Paho client across supported callback API versions."""
        try:
            return mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            return mqtt.Client(protocol=mqtt.MQTTv311)

    @staticmethod
    def _close_client(client: Any, loop_started: bool) -> None:
        """Close a Paho client without exposing connection details."""
        try:
            client.disconnect()
        except Exception:  # Paho and socket implementations vary.
            _LOGGER.warning("GRIT MQTT client disconnect failed")
        finally:
            if loop_started:
                try:
                    client.loop_stop()
                except Exception:  # Paho and socket implementations vary.
                    _LOGGER.warning("GRIT MQTT network loop failed to stop")

    @staticmethod
    def _reason_code_is_success(reason_code: Any) -> bool:
        """Classify Paho reason codes without raising into callback threads."""
        try:
            is_failure = getattr(reason_code, "is_failure", None)
            if isinstance(is_failure, bool):
                return not is_failure
            value = getattr(reason_code, "value", reason_code)
            return int(value) == 0
        except Exception:  # Third-party reason-code implementations vary.
            return False

    def _client_is_current(self, client: Any) -> bool:
        """Return whether a callback belongs to the active client generation."""
        with self._state_condition:
            return self._client is client and self._state in (
                _LifecycleState.STARTING,
                _LifecycleState.RUNNING,
            )

    def _set_connection_state(self, client: Any, connected: bool) -> bool:
        """Update and report state for the current client without duplicates."""
        callback: GritMqttConnectionStateCallback | None = None
        with self._state_condition:
            if self._client is not client or self._state not in (
                _LifecycleState.STARTING,
                _LifecycleState.RUNNING,
            ):
                return False
            self._connected = connected
            if self._reported_connection_state == connected:
                return True
            self._reported_connection_state = connected
            callback = self._connection_state_callback

        if callback is not None:
            try:
                callback(connected)
            except Exception:
                _LOGGER.error("GRIT MQTT connection-state callback failed")
        return True

    def _on_connect(
        self,
        client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
    ) -> None:
        """Subscribe after a successful initial connection or reconnect."""
        success = self._reason_code_is_success(reason_code)
        if not self._client_is_current(client):
            return
        if not success:
            if self._set_connection_state(client, False):
                _LOGGER.warning("GRIT MQTT connection rejected")
            return

        try:
            result, _message_id = client.subscribe(MQTT_TOPIC, qos=MQTT_QOS)
        except Exception:  # Paho implementations vary.
            if self._set_connection_state(client, False):
                _LOGGER.warning("GRIT MQTT subscription failed")
            return

        if not self._client_is_current(client):
            return
        if not self._reason_code_is_success(result):
            if self._set_connection_state(client, False):
                _LOGGER.warning("GRIT MQTT subscription failed")
            return
        if not self._set_connection_state(client, True):
            return

        _LOGGER.info("GRIT MQTT connection established")

    def _on_disconnect(
        self,
        client: Any,
        _userdata: Any,
        reason_code: Any,
    ) -> None:
        """Record broker disconnection without logging endpoint details."""
        success = self._reason_code_is_success(reason_code)
        if not self._set_connection_state(client, False):
            return
        if success:
            _LOGGER.info("GRIT MQTT connection closed")
        else:
            _LOGGER.warning("GRIT MQTT connection lost")

    def _on_message(self, client: Any, _userdata: Any, message: Any) -> None:
        """Validate and pass a decoded MQTT message to the injected callback."""
        if not self._client_is_current(client):
            return

        raw_payload = getattr(message, "payload", None)
        if not isinstance(raw_payload, (bytes, bytearray, memoryview)):
            _LOGGER.warning("GRIT MQTT message rejected: invalid payload")
            return

        try:
            payload_view = memoryview(raw_payload)
            if payload_view.nbytes > MAX_MQTT_PAYLOAD_SIZE:
                _LOGGER.warning("GRIT MQTT message rejected: payload too large")
                return
            payload_text = payload_view.tobytes().decode("utf-8")
        except (TypeError, ValueError, UnicodeDecodeError):
            _LOGGER.warning("GRIT MQTT message rejected: invalid UTF-8")
            return

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            _LOGGER.warning("GRIT MQTT message rejected: invalid JSON")
            return

        if not isinstance(payload, dict):
            _LOGGER.warning("GRIT MQTT message rejected: expected an object")
            return

        topic = getattr(message, "topic", None)
        if not isinstance(topic, str) or len(topic) > MAX_MQTT_TOPIC_LENGTH:
            _LOGGER.warning("GRIT MQTT message rejected: invalid topic")
            return

        parts = topic.split("/")
        if (
            len(parts) < 5
            or parts[0] != "grit"
            or any(
                not part or len(part) > MAX_MQTT_TOPIC_COMPONENT_LENGTH
                for part in parts
            )
        ):
            _LOGGER.warning("GRIT MQTT message rejected: invalid topic")
            return

        hub_id = parts[1]
        device_type = parts[2]
        device_id = parts[3]
        message_type = "/".join(parts[4:])

        if not self._client_is_current(client):
            return

        try:
            self._message_callback(
                hub_id,
                device_type,
                device_id,
                message_type,
                payload,
            )
        except Exception:  # The callback boundary must not stop Paho's loop.
            _LOGGER.error("GRIT MQTT message callback failed")

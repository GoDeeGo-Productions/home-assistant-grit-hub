"""Network-free unit tests for the standalone GRIT MQTT client."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path
import threading
from types import ModuleType, SimpleNamespace
from typing import Any
import unittest
from unittest import mock

THREAD_TIMEOUT = 5
FABRICATED_HOST = "broker.fabricated.invalid"
FABRICATED_PORT = 18_883
FABRICATED_USERNAME = "fabricated-user"
FABRICATED_PASSWORD = "fabricated-password"
FABRICATED_HUB_ID = "hub-test"
FABRICATED_DEVICE_ID = "device-test"
FABRICATED_TOPIC = (
    f"grit/{FABRICATED_HUB_ID}/gate/{FABRICATED_DEVICE_ID}/sts/detail"
)


def _load_mqtt_module() -> tuple[ModuleType, list[str]]:
    """Load mqtt_live.py without importing its Home Assistant package."""
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "grit_hub"
        / "mqtt_live.py"
    )
    imported_names: list[str] = []
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        imported_names.append(name)
        if name == "paho" or name.startswith("paho."):
            raise AssertionError("mqtt_live.py imported Paho during module load")
        return real_import(name, *args, **kwargs)

    module = ModuleType("grit_hub_mqtt_live_under_test")
    module.__file__ = str(module_path)
    source = module_path.read_text(encoding="utf-8")
    code = compile(source, str(module_path), "exec")
    with mock.patch("builtins.__import__", side_effect=guarded_import):
        exec(code, module.__dict__)
    return module, imported_names


MQTT_MODULE, MODULE_IMPORTS = _load_mqtt_module()


class FakeMessage:
    """Minimal Paho message stand-in."""

    def __init__(self, payload: Any, topic: Any) -> None:
        self.payload = payload
        self.topic = topic


class BadReasonCode:
    """Reason code whose properties cannot be inspected safely."""

    @property
    def is_failure(self) -> bool:
        raise RuntimeError("fabricated malformed reason code")


class FakeClient:
    """Deterministic, socket-free Paho client stand-in."""

    def __init__(
        self,
        *,
        connect_error: Exception | None = None,
        loop_start_error: Exception | None = None,
        tls_set_error: Exception | None = None,
        loop_start_entered: threading.Event | None = None,
        loop_start_release: threading.Event | None = None,
        synchronous_connect: bool = False,
        synchronous_disconnect: bool = False,
        subscribe_result: Any = 0,
    ) -> None:
        self.connect_error = connect_error
        self.loop_start_error = loop_start_error
        self.tls_set_error = tls_set_error
        self.loop_start_entered = loop_start_entered
        self.loop_start_release = loop_start_release
        self.synchronous_connect = synchronous_connect
        self.synchronous_disconnect = synchronous_disconnect
        self.subscribe_result = subscribe_result

        self.constructor_kwargs: dict[str, Any] = {}
        self.credentials: tuple[str, str | None] | None = None
        self.tls_set_calls = 0
        self.tls_insecure_set_calls: list[bool] = []
        self.call_order: list[str] = []
        self.connect_calls: list[tuple[str, int, int]] = []
        self.loop_start_calls = 0
        self.subscribe_calls: list[tuple[str, int]] = []
        self.disconnect_calls = 0
        self.loop_stop_calls = 0

        self.on_connect: Callable[..., None] | None = None
        self.on_disconnect: Callable[..., None] | None = None
        self.on_message: Callable[..., None] | None = None

    def tls_set(self) -> None:
        self.tls_set_calls += 1
        self.call_order.append("tls_set")
        if self.tls_set_error is not None:
            raise self.tls_set_error

    def tls_insecure_set(self, value: bool) -> None:
        self.tls_insecure_set_calls.append(value)
        self.call_order.append("tls_insecure_set")
    def username_pw_set(self, username: str, password: str | None) -> None:
        self.credentials = (username, password)

    def connect(self, host: str, port: int, *, keepalive: int) -> None:
        self.connect_calls.append((host, port, keepalive))
        self.call_order.append("connect")
        if self.connect_error is not None:
            raise self.connect_error

    def loop_start(self) -> None:
        self.loop_start_calls += 1
        if self.loop_start_entered is not None:
            self.loop_start_entered.set()
        if self.loop_start_release is not None and not self.loop_start_release.wait(
            THREAD_TIMEOUT
        ):
            raise TimeoutError("fake loop-start release timed out")
        if self.loop_start_error is not None:
            raise self.loop_start_error
        if self.synchronous_connect and self.on_connect is not None:
            self.on_connect(self, None, None, 0)

    def subscribe(self, topic: str, *, qos: int) -> tuple[Any, int]:
        self.subscribe_calls.append((topic, qos))
        return self.subscribe_result, 1

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.synchronous_disconnect and self.on_disconnect is not None:
            self.on_disconnect(self, None, 0)

    def loop_stop(self) -> None:
        self.loop_stop_calls += 1


class FakeClientFactory:
    """Create fake clients from a deterministic queue."""

    def __init__(
        self,
        clients: list[FakeClient] | None = None,
        *,
        construction_entered: threading.Event | None = None,
        construction_release: threading.Event | None = None,
    ) -> None:
        self._clients = list(clients or [])
        self.construction_entered = construction_entered
        self.construction_release = construction_release
        self.instances: list[FakeClient] = []
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.calls.append(kwargs)
        if self.construction_entered is not None:
            self.construction_entered.set()
        if self.construction_release is not None and not self.construction_release.wait(
            THREAD_TIMEOUT
        ):
            raise TimeoutError("fake construction release timed out")
        client = self._clients.pop(0) if self._clients else FakeClient()
        client.constructor_kwargs = kwargs
        self.instances.append(client)
        return client


class GritLiveMqttTests(unittest.TestCase):
    """Exercise the MQTT client without Paho, sockets, or Home Assistant."""

    def _paho_patch(self, factory: FakeClientFactory) -> mock._patch[Any]:
        fake_paho = SimpleNamespace(
            CallbackAPIVersion=SimpleNamespace(VERSION1=object()),
            MQTTv311=object(),
            Client=factory,
        )
        return mock.patch.object(
            MQTT_MODULE.importlib,
            "import_module",
            return_value=fake_paho,
        )

    def _new_client(
        self,
        callback: Callable[..., None] | None = None,
        **kwargs: Any,
    ) -> Any:
        return MQTT_MODULE.GritLiveMqtt(
            FABRICATED_HOST,
            FABRICATED_PORT,
            callback or (lambda *_args: None),
            **kwargs,
        )

    def _start_thread(
        self, target: Callable[[], Any]
    ) -> tuple[threading.Thread, list[Any], list[BaseException]]:
        results: list[Any] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                results.append(target())
            except BaseException as err:  # Report failures in the test thread.
                errors.append(err)

        thread = threading.Thread(target=run)
        thread.start()
        return thread, results, errors

    def _join_thread(
        self,
        thread: threading.Thread,
        errors: list[BaseException],
    ) -> None:
        thread.join(THREAD_TIMEOUT)
        self.assertFalse(thread.is_alive(), "test thread did not finish")
        if errors:
            raise errors[0]

    def _coordinated_stop(
        self,
        client: Any,
        release_event: threading.Event,
    ) -> None:
        """Release a fake block only after stop has entered STOPPING."""
        release_errors: list[BaseException] = []

        def release_after_transition() -> None:
            try:
                with client._state_condition:
                    if client._state is not MQTT_MODULE._LifecycleState.STOPPING:
                        raise AssertionError("stop did not enter STOPPING")
                    release_event.set()
            except BaseException as err:
                release_errors.append(err)

        with client._state_condition:
            release_thread = threading.Thread(target=release_after_transition)
            release_thread.start()
            client.stop()

        self._join_thread(release_thread, release_errors)

    def _assert_stopped(self, client: Any) -> None:
        self.assertFalse(client.connected)
        self.assertIsNone(client._client)
        self.assertIs(client._state, MQTT_MODULE._LifecycleState.STOPPED)

    def test_module_load_does_not_import_paho(self) -> None:
        self.assertFalse(any(name.startswith("paho") for name in MODULE_IMPORTS))

    def test_construction_does_not_connect(self) -> None:
        factory = FakeClientFactory()
        with self._paho_patch(factory):
            self._new_client()
        self.assertEqual(factory.calls, [])

    def test_blank_host_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MQTT_MODULE.GritLiveMqtt(" ", FABRICATED_PORT, lambda *_args: None)

    def test_invalid_ports_are_rejected(self) -> None:
        for port in (0, 65_536, True, "1883"):
            with self.subTest(port=port), self.assertRaises((TypeError, ValueError)):
                MQTT_MODULE.GritLiveMqtt(
                    FABRICATED_HOST, port, lambda *_args: None
                )

    def test_invalid_keepalive_values_are_rejected(self) -> None:
        for keepalive in (0, 65_536, True, "60"):
            with self.subTest(keepalive=keepalive), self.assertRaises(
                (TypeError, ValueError)
            ):
                self._new_client(keepalive=keepalive)

    def test_password_without_username_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._new_client(password=FABRICATED_PASSWORD)

    def test_non_callable_callback_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self._new_client(callback="not-callable")

    def test_connection_state_callback_requires_callable(self) -> None:
        with self.assertRaises(TypeError):
            self._new_client(connection_state_callback="not-callable")

    def test_connection_state_reports_only_after_subscription(self) -> None:
        states: list[bool] = []
        fake = FakeClient()
        factory = FakeClientFactory([fake])
        client = self._new_client(connection_state_callback=states.append)
        with self._paho_patch(factory):
            self.assertTrue(client.start())

        self.assertEqual(states, [])
        fake.on_connect(fake, None, None, 0)
        self.assertEqual(states, [True])
        self.assertTrue(client.connected)
        fake.on_connect(fake, None, None, 0)
        self.assertEqual(states, [True])
        fake.on_disconnect(fake, None, 1)
        fake.on_disconnect(fake, None, 1)
        self.assertEqual(states, [True, False])
        self.assertFalse(client.connected)
        client.stop()

    def test_connection_rejection_reports_not_connected(self) -> None:
        states: list[bool] = []
        fake = FakeClient()
        factory = FakeClientFactory([fake])
        client = self._new_client(connection_state_callback=states.append)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake.on_connect(fake, None, None, 1)
        self.assertEqual(states, [False])
        self.assertFalse(client.connected)
        self.assertEqual(fake.subscribe_calls, [])
        client.stop()

    def test_subscription_failure_reports_not_connected(self) -> None:
        states: list[bool] = []
        fake = FakeClient(subscribe_result=1)
        factory = FakeClientFactory([fake])
        client = self._new_client(connection_state_callback=states.append)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake.on_connect(fake, None, None, 0)
        self.assertEqual(states, [False])
        self.assertFalse(client.connected)
        client.stop()
    def test_successful_lifecycle_and_subscription(self) -> None:
        factory = FakeClientFactory()
        client = self._new_client(
            username=FABRICATED_USERNAME,
            password=FABRICATED_PASSWORD,
        )
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        self.assertEqual(
            fake.connect_calls,
            [(FABRICATED_HOST, FABRICATED_PORT, MQTT_MODULE.MQTT_KEEPALIVE)],
        )
        self.assertEqual(
            fake.credentials,
            (FABRICATED_USERNAME, FABRICATED_PASSWORD),
        )
        fake.on_connect(fake, None, None, 0)
        self.assertTrue(client.connected)
        self.assertEqual(
            fake.subscribe_calls,
            [(MQTT_MODULE.MQTT_TOPIC, MQTT_MODULE.MQTT_QOS)],
        )
        client.stop()
        self._assert_stopped(client)
        self.assertEqual(fake.disconnect_calls, 1)
        self.assertEqual(fake.loop_stop_calls, 1)

    def test_repeated_start_does_not_create_another_client(self) -> None:
        factory = FakeClientFactory()
        client = self._new_client()
        with self._paho_patch(factory):
            self.assertTrue(client.start())
            self.assertFalse(client.start())
        self.assertEqual(len(factory.instances), 1)
        client.stop()

    def test_repeated_stop_is_safe(self) -> None:
        factory = FakeClientFactory()
        client = self._new_client()
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        client.stop()
        client.stop()
        self._assert_stopped(client)
        self.assertEqual(fake.disconnect_calls, 1)
        self.assertEqual(fake.loop_stop_calls, 1)

    def test_stop_during_client_creation_cancels_start(self) -> None:
        construction_entered = threading.Event()
        construction_release = threading.Event()
        factory = FakeClientFactory(
            construction_entered=construction_entered,
            construction_release=construction_release,
        )
        client = self._new_client()
        with self._paho_patch(factory):
            start_thread, results, start_errors = self._start_thread(client.start)
            self.assertTrue(construction_entered.wait(THREAD_TIMEOUT))
            stop_thread, _, stop_errors = self._start_thread(
                lambda: self._coordinated_stop(client, construction_release)
            )
            self._join_thread(start_thread, start_errors)
            self._join_thread(stop_thread, stop_errors)
        self.assertEqual(results, [False])
        fake = factory.instances[0]
        self.assertEqual(fake.connect_calls, [])
        self.assertEqual(fake.loop_start_calls, 0)
        self.assertEqual(fake.disconnect_calls, 1)
        self._assert_stopped(client)

    def test_stop_while_loop_start_is_blocked_cleans_client(self) -> None:
        loop_entered = threading.Event()
        loop_release = threading.Event()
        fake = FakeClient(
            loop_start_entered=loop_entered,
            loop_start_release=loop_release,
        )
        factory = FakeClientFactory([fake])
        client = self._new_client()
        with self._paho_patch(factory):
            start_thread, results, start_errors = self._start_thread(client.start)
            self.assertTrue(loop_entered.wait(THREAD_TIMEOUT))
            stop_thread, _, stop_errors = self._start_thread(
                lambda: self._coordinated_stop(client, loop_release)
            )
            self._join_thread(start_thread, start_errors)
            self._join_thread(stop_thread, stop_errors)
        self.assertEqual(results, [False])
        self.assertEqual(fake.disconnect_calls, 1)
        self.assertEqual(fake.loop_stop_calls, 1)
        self._assert_stopped(client)

    def test_connect_failure_cleans_partial_client(self) -> None:
        fake = FakeClient(connect_error=OSError("fabricated connect failure"))
        factory = FakeClientFactory([fake])
        client = self._new_client()
        with self._paho_patch(factory):
            self.assertFalse(client.start())
        self.assertEqual(fake.disconnect_calls, 1)
        self.assertEqual(fake.loop_stop_calls, 0)
        self._assert_stopped(client)

    def test_loop_start_failure_cleans_partial_loop(self) -> None:
        fake = FakeClient(
            loop_start_error=RuntimeError("fabricated loop-start failure")
        )
        factory = FakeClientFactory([fake])
        client = self._new_client()
        with self._paho_patch(factory):
            self.assertFalse(client.start())
        self.assertEqual(fake.disconnect_calls, 1)
        self.assertEqual(fake.loop_stop_calls, 1)
        self._assert_stopped(client)

    def test_synchronous_connect_callback_during_start_does_not_deadlock(self) -> None:
        fake = FakeClient(synchronous_connect=True)
        factory = FakeClientFactory([fake])
        client = self._new_client()
        with self._paho_patch(factory):
            thread, results, errors = self._start_thread(client.start)
            self._join_thread(thread, errors)
        self.assertEqual(results, [True])
        self.assertTrue(client.connected)
        self.assertEqual(len(fake.subscribe_calls), 1)
        client.stop()

    def test_synchronous_disconnect_callback_during_stop_does_not_deadlock(self) -> None:
        fake = FakeClient(synchronous_connect=True, synchronous_disconnect=True)
        factory = FakeClientFactory([fake])
        client = self._new_client()
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        thread, _, errors = self._start_thread(client.stop)
        self._join_thread(thread, errors)
        self._assert_stopped(client)

    def test_late_on_connect_after_stop_is_ignored(self) -> None:
        states: list[bool] = []
        factory = FakeClientFactory()
        client = self._new_client(connection_state_callback=states.append)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        client.stop()
        fake.on_connect(fake, None, None, 0)
        self.assertFalse(client.connected)
        self.assertEqual(fake.subscribe_calls, [])
        self.assertEqual(states, [])

    def test_obsolete_disconnect_does_not_change_replacement_state(self) -> None:
        states: list[bool] = []
        old = FakeClient()
        replacement = FakeClient()
        factory = FakeClientFactory([old, replacement])
        client = self._new_client(connection_state_callback=states.append)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
            client.stop()
            self.assertTrue(client.start())
        replacement.on_connect(replacement, None, None, 0)
        self.assertTrue(client.connected)
        self.assertEqual(states, [True])
        old.on_disconnect(old, None, 1)
        self.assertTrue(client.connected)
        self.assertEqual(states, [True])
        client.stop()

    def test_obsolete_on_message_is_ignored(self) -> None:
        received: list[tuple[Any, ...]] = []
        old = FakeClient()
        replacement = FakeClient()
        factory = FakeClientFactory([old, replacement])
        client = self._new_client(lambda *args: received.append(args))
        with self._paho_patch(factory):
            self.assertTrue(client.start())
            client.stop()
            self.assertTrue(client.start())
        old.on_message(old, None, FakeMessage(b"{}", FABRICATED_TOPIC))
        self.assertEqual(received, [])
        client.stop()

    def test_post_stop_on_message_is_ignored(self) -> None:
        received: list[tuple[Any, ...]] = []
        factory = FakeClientFactory()
        client = self._new_client(lambda *args: received.append(args))
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        client.stop()
        fake.on_message(fake, None, FakeMessage(b"{}", FABRICATED_TOPIC))
        self.assertEqual(received, [])

    def test_valid_message_preserves_additional_message_type_components(self) -> None:
        received: list[tuple[Any, ...]] = []
        factory = FakeClientFactory()
        client = self._new_client(lambda *args: received.append(args))
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        fake.on_message(
            fake,
            None,
            FakeMessage(b'{"state": true}', FABRICATED_TOPIC),
        )
        self.assertEqual(
            received,
            [
                (
                    FABRICATED_HUB_ID,
                    "gate",
                    FABRICATED_DEVICE_ID,
                    "sts/detail",
                    {"state": True},
                )
            ],
        )
        client.stop()

    def _assert_message_rejected(self, payload: Any, topic: Any) -> None:
        received: list[tuple[Any, ...]] = []
        factory = FakeClientFactory()
        client = self._new_client(lambda *args: received.append(args))
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        fake.on_message(fake, None, FakeMessage(payload, topic))
        self.assertEqual(received, [])
        client.stop()

    def test_malformed_utf8_is_rejected(self) -> None:
        self._assert_message_rejected(b"\xff", FABRICATED_TOPIC)

    def test_malformed_json_is_rejected(self) -> None:
        self._assert_message_rejected(b"{", FABRICATED_TOPIC)

    def test_non_object_json_is_rejected(self) -> None:
        self._assert_message_rejected(b"[]", FABRICATED_TOPIC)

    def test_non_bytes_payload_is_rejected(self) -> None:
        self._assert_message_rejected("not-bytes", FABRICATED_TOPIC)

    def test_oversized_payload_is_rejected(self) -> None:
        self._assert_message_rejected(
            b"x" * (MQTT_MODULE.MAX_MQTT_PAYLOAD_SIZE + 1),
            FABRICATED_TOPIC,
        )

    def test_oversized_topic_is_rejected(self) -> None:
        self._assert_message_rejected(
            b"{}",
            "grit/" + ("x" * MQTT_MODULE.MAX_MQTT_TOPIC_LENGTH),
        )

    def test_empty_topic_component_is_rejected(self) -> None:
        self._assert_message_rejected(
            b"{}",
            f"grit/{FABRICATED_HUB_ID}//{FABRICATED_DEVICE_ID}/sts",
        )

    def test_oversized_topic_component_is_rejected(self) -> None:
        oversized = "x" * (MQTT_MODULE.MAX_MQTT_TOPIC_COMPONENT_LENGTH + 1)
        self._assert_message_rejected(
            b"{}",
            f"grit/{oversized}/gate/{FABRICATED_DEVICE_ID}/sts",
        )

    def test_malformed_reason_codes_do_not_raise(self) -> None:
        fake = FakeClient()
        factory = FakeClientFactory([fake])
        client = self._new_client()
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake.on_connect(fake, None, None, BadReasonCode())
        self.assertFalse(client.connected)
        fake.on_disconnect(fake, None, BadReasonCode())
        self.assertFalse(client.connected)
        fake.subscribe_result = BadReasonCode()
        fake.on_connect(fake, None, None, 0)
        client.stop()

    def test_tls_disabled_invokes_no_tls_methods(self) -> None:
        factory = FakeClientFactory()
        client = self._new_client(use_tls=False)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        self.assertEqual(fake.tls_set_calls, 0)
        self.assertEqual(fake.tls_insecure_set_calls, [])
        client.stop()

    def test_tls_secure_defaults_are_configured_before_connect(self) -> None:
        factory = FakeClientFactory()
        client = self._new_client(use_tls=True)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        self.assertEqual(fake.tls_set_calls, 1)
        self.assertEqual(fake.tls_insecure_set_calls, [])
        self.assertEqual(fake.call_order[:2], ["tls_set", "connect"])
        client.stop()

    def test_tls_verification_can_be_explicitly_disabled(self) -> None:
        factory = FakeClientFactory()
        client = self._new_client(use_tls=True, verify_tls=False)
        with self._paho_patch(factory):
            self.assertTrue(client.start())
        fake = factory.instances[0]
        self.assertEqual(fake.tls_set_calls, 1)
        self.assertEqual(fake.tls_insecure_set_calls, [True])
        self.assertEqual(
            fake.call_order[:3],
            ["tls_set", "tls_insecure_set", "connect"],
        )
        client.stop()

    def test_tls_configuration_failure_cleans_partial_client(self) -> None:
        fake = FakeClient(
            tls_set_error=RuntimeError("fabricated TLS setup failure")
        )
        factory = FakeClientFactory([fake])
        client = self._new_client(use_tls=True)
        with self._paho_patch(factory):
            self.assertFalse(client.start())
        self.assertEqual(fake.connect_calls, [])
        self.assertEqual(fake.disconnect_calls, 1)
        self.assertEqual(fake.loop_stop_calls, 0)
        self._assert_stopped(client)

    def test_tls_options_require_booleans(self) -> None:
        for kwargs in ({"use_tls": 1}, {"verify_tls": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                self._new_client(**kwargs)

    def test_logs_exclude_connection_and_message_values(self) -> None:
        payload_marker = "fabricated-payload-marker"
        factory = FakeClientFactory()
        client = self._new_client(
            username=FABRICATED_USERNAME,
            password=FABRICATED_PASSWORD,
        )
        with self.assertLogs(MQTT_MODULE._LOGGER, level="INFO") as captured:
            with self._paho_patch(factory):
                self.assertTrue(client.start())
            fake = factory.instances[0]
            fake.on_connect(fake, None, None, 0)
            fake.on_message(
                fake,
                None,
                FakeMessage(payload_marker.encode(), FABRICATED_TOPIC),
            )
            fake.on_disconnect(fake, None, 1)
            client.stop()

        output = "\n".join(captured.output)
        for sensitive in (
            FABRICATED_HOST,
            FABRICATED_USERNAME,
            FABRICATED_PASSWORD,
            FABRICATED_TOPIC,
            FABRICATED_HUB_ID,
            FABRICATED_DEVICE_ID,
            payload_marker,
        ):
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, output)
        self.assertIn("GRIT MQTT connection established", output)
        self.assertIn("GRIT MQTT message rejected: invalid JSON", output)
        self.assertIn("GRIT MQTT connection lost", output)


if __name__ == "__main__":
    unittest.main()

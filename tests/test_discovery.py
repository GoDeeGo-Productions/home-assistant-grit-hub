"""Network-free tests for documented installation discovery."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
HUB_ID = "0123456789abcdef0123456789abcdef"
OTHER_HUB_ID = "fedcba9876543210fedcba9876543210"
BROKER_IP = "192.0.2.44"


def _load_discovery():
    package_name = "_grit_discovery_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules[package_name] = package
    loaded = {}
    for module_name in ("const", "hub", "mqtt_live", "discovery"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{module_name}",
            COMPONENT_ROOT / f"{module_name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded


MODULES = _load_discovery()
DISCOVERY = MODULES["discovery"]
CONST = MODULES["const"]


class _CallbackApiVersion:
    VERSION1 = 1


class FakeMessage:
    def __init__(self, topic):
        self.topic = topic
        self.payload = b"ignored"


class FakePahoScenario:
    def __init__(self):
        self.messages_before_suback = []
        self.clients = []
        self.connect_reason = 0
        self.connect_result = 0
        self.subscribe_result = 0
        self.suback_reason_codes = [0]
        self.suback_message_id = 1
        self.suppress_suback = False
        self.loop_result = 0
        self.messages = []
        self.connect_failure = False
        self.silent = False
        self.loop_started_event = threading.Event()

    def module(self):
        scenario = self
        module = types.SimpleNamespace(
            CallbackAPIVersion=_CallbackApiVersion,
            MQTTv311=4,
        )

        class Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.connect_timeout = None
                self.on_connect = None
                self.on_connect_fail = None
                self.on_disconnect = None
                self.on_message = None
                self.on_subscribe = None
                self.connect_calls = []
                self.subscribe_calls = []
                self.disconnect_calls = 0
                self.loop_start_calls = 0
                self.loop_stop_calls = 0
                self.username_calls = []
                self.tls_calls = 0
                self.insecure_calls = []
                self.publish_calls = 0
                scenario.clients.append(self)

            def username_pw_set(self, username, password):
                self.username_calls.append((username, password))

            def tls_set(self):
                self.tls_calls += 1

            def tls_insecure_set(self, value):
                self.insecure_calls.append(value)

            def connect_async(self, host, port, *, keepalive):
                self.connect_calls.append((host, port, keepalive))
                return scenario.connect_result

            def loop_start(self):
                self.loop_start_calls += 1
                scenario.loop_started_event.set()
                if scenario.silent:
                    pass
                elif scenario.connect_failure:
                    self.on_connect_fail(self, None)
                else:
                    self.on_connect(
                        self,
                        None,
                        None,
                        scenario.connect_reason,
                    )
                    for topic_value in scenario.messages_before_suback:
                        self.on_message(self, None, FakeMessage(topic_value))
                    if self.subscribe_calls and not scenario.suppress_suback:
                        self.on_subscribe(
                            self,
                            None,
                            scenario.suback_message_id,
                            scenario.suback_reason_codes,
                        )
                    for topic_value in scenario.messages:
                        self.on_message(self, None, FakeMessage(topic_value))
                return scenario.loop_result

            def subscribe(self, topic, *, qos):
                self.subscribe_calls.append((topic, qos))
                return scenario.subscribe_result, 1

            def publish(self, *_args, **_kwargs):
                self.publish_calls += 1
                raise AssertionError("discovery must never publish")

            def disconnect(self):
                self.disconnect_calls += 1
                return 0

            def loop_stop(self):
                self.loop_stop_calls += 1
                return 0

        module.Client = Client
        return module


class RestExtractionTests(unittest.TestCase):
    def test_documented_hub_fields_become_mqtt_candidates(self):
        result = DISCOVERY.extract_rest_mqtt_discovery(
            [
                {
                    "id": HUB_ID,
                    "ipAddressEthernet": BROKER_IP,
                    "uuid": "device-id-must-not-be-used",
                }
            ]
        )
        self.assertEqual(
            result,
            DISCOVERY.RestMqttDiscovery(
                host=BROKER_IP,
                port=1883,
                hub_id=HUB_ID,
                use_tls=False,
            ),
        )

    def test_generic_identifiers_and_hosts_are_not_used(self):
        result = DISCOVERY.extract_rest_mqtt_discovery(
            [
                {
                    "uuid": HUB_ID,
                    "host": BROKER_IP,
                    "hostname": "hub.fabricated.invalid",
                    "staticIpAddress": BROKER_IP,
                }
            ]
        )
        self.assertIsNone(result.host)
        self.assertIsNone(result.hub_id)

    def test_missing_or_malformed_documented_hub_id_fails_closed(self):
        for value in (None, "", "short", "g" * 32, 123):
            with self.subTest(value=value):
                result = DISCOVERY.extract_rest_mqtt_discovery(
                    [{"id": value, "ipAddressEthernet": BROKER_IP}]
                )
                self.assertIsNone(result.hub_id)

    def test_missing_or_malformed_ethernet_ip_fails_closed(self):
        for value in (None, "", "hub.fabricated.invalid", "999.1.1.1", 123):
            with self.subTest(value=value):
                result = DISCOVERY.extract_rest_mqtt_discovery(
                    [{"id": HUB_ID, "ipAddressEthernet": value}]
                )
                self.assertIsNone(result.host)


class PassiveMqttDiscoveryTests(unittest.TestCase):
    def run_probe(self, scenario, **kwargs):
        with mock.patch.object(
            DISCOVERY.importlib,
            "import_module",
            return_value=scenario.module(),
        ):
            result = DISCOVERY.passive_mqtt_discover(
                BROKER_IP,
                1883,
                timeout=kwargs.pop("timeout", 0.01),
                expected_hub_id=kwargs.pop("expected_hub_id", HUB_ID),
                **kwargs,
            )
        return result, scenario.clients[0]

    def assert_stopped(self, client):
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.loop_start_calls, 1)
        self.assertEqual(client.loop_stop_calls, 1)
        self.assertEqual(len(client.connect_calls), 1)
        self.assertEqual(client.publish_calls, 0)

    def test_successful_subscription_completes_without_message(self):
        scenario = FakePahoScenario()
        started = time.monotonic()
        result, client = self.run_probe(
            scenario,
            username=CONST.DEFAULT_MQTT_USERNAME,
            password=CONST.DEFAULT_MQTT_PASSWORD,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result, DISCOVERY.MqttProbeResult(True, HUB_ID))
        self.assertLess(elapsed, 0.5)
        self.assertEqual(
            client.subscribe_calls,
            [(f"grit/{HUB_ID}/+/+/#", 0)],
        )
        self.assertEqual(
            client.username_calls,
            [
                (
                    CONST.DEFAULT_MQTT_USERNAME,
                    CONST.DEFAULT_MQTT_PASSWORD,
                )
            ],
        )
        self.assert_stopped(client)

    def test_subscribe_request_without_suback_times_out(self):
        scenario = FakePahoScenario()
        scenario.suppress_suback = True

        result, client = self.run_probe(scenario, timeout=0.02)

        self.assertFalse(result.connected)
        self.assertEqual(client.subscribe_calls, [(f"grit/{HUB_ID}/+/+/#", 0)])
        self.assert_stopped(client)

    def test_failed_suback_fails_closed(self):
        scenario = FakePahoScenario()
        scenario.suback_reason_codes = [128]

        result, client = self.run_probe(scenario)

        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_mismatched_suback_is_ignored_until_timeout(self):
        scenario = FakePahoScenario()
        scenario.suback_message_id = 2

        result, client = self.run_probe(scenario, timeout=0.02)

        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_matching_arriving_topic_is_accepted(self):
        scenario = FakePahoScenario()
        scenario.messages = [f"grit/{HUB_ID}/gate/device-fabricated/status"]
        result, client = self.run_probe(scenario)
        self.assertTrue(result.connected)
        self.assertEqual(result.hub_id, HUB_ID)
        self.assert_stopped(client)

    def test_message_before_matching_suback_is_not_discovery_evidence(self):
        scenario = FakePahoScenario()
        scenario.messages_before_suback = [
            f"grit/{HUB_ID}/gate/device-fabricated/status"
        ]
        result, client = self.run_probe(scenario, expected_hub_id=None)
        self.assertEqual(result, DISCOVERY.MqttProbeResult(True))
        self.assert_stopped(client)

    def test_wrong_arriving_topic_hub_is_rejected(self):
        scenario = FakePahoScenario()
        scenario.messages = [
            f"grit/{OTHER_HUB_ID}/gate/device-fabricated/status"
        ]
        result, client = self.run_probe(scenario)
        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_connection_and_subscription_failures_fail_closed(self):
        scenario = FakePahoScenario()
        scenario.connect_reason = 5
        result, client = self.run_probe(scenario)
        self.assertFalse(result.connected)
        self.assert_stopped(client)

        scenario = FakePahoScenario()
        scenario.subscribe_result = 4
        result, client = self.run_probe(scenario)
        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_timeout_is_bounded_and_client_is_stopped(self):
        scenario = FakePahoScenario()
        scenario.silent = True
        started = time.monotonic()
        result, client = self.run_probe(scenario, timeout=0.02)
        elapsed = time.monotonic() - started
        self.assertFalse(result.connected)
        self.assertLess(elapsed, 0.5)
        self.assert_stopped(client)

    def test_cancellation_signal_stops_probe_and_cleans_client(self):
        scenario = FakePahoScenario()
        scenario.silent = True
        cancel_event = threading.Event()
        result_holder = []

        def run() -> None:
            result, client = self.run_probe(
                scenario,
                timeout=1,
                cancel_event=cancel_event,
            )
            result_holder.append((result, client))

        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(
            scenario.loop_started_event.wait(0.5),
            "fake discovery loop did not start",
        )
        cancel_event.set()
        worker.join(0.5)
        self.assertFalse(worker.is_alive(), "cancelled discovery did not stop")
        result, client = result_holder[0]
        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_callbacks_after_cleanup_are_ignored(self):
        scenario = FakePahoScenario()
        scenario.silent = True
        result, client = self.run_probe(scenario, timeout=0.01)
        self.assertFalse(result.connected)
        client.on_connect(client, None, None, 0)
        client.on_subscribe(client, None, 1, [0])
        client.on_message(
            client,
            None,
            FakeMessage(
                f"grit/{HUB_ID}/gate/device-fabricated/status"
            ),
        )
        client.on_disconnect(client, None, 0)
        self.assertEqual(client.subscribe_calls, [])
        self.assert_stopped(client)

    def test_malformed_reason_code_never_escapes_callback(self):
        class MalformedReason:
            @property
            def is_failure(self):
                raise RuntimeError("fabricated malformed reason")

            def __int__(self):
                raise RuntimeError("fabricated malformed reason")

        scenario = FakePahoScenario()
        scenario.connect_reason = MalformedReason()
        result, client = self.run_probe(scenario)
        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_malformed_suback_reason_never_escapes_callback(self):
        class MalformedReason:
            @property
            def is_failure(self):
                raise RuntimeError("fabricated malformed reason")

            def __int__(self):
                raise RuntimeError("fabricated malformed reason")

        scenario = FakePahoScenario()
        scenario.suback_reason_codes = [MalformedReason()]
        result, client = self.run_probe(scenario)
        self.assertFalse(result.connected)
        self.assert_stopped(client)

    def test_connect_async_failure_cleans_up_without_loop(self):
        scenario = FakePahoScenario()
        scenario.connect_result = 4
        result, client = self.run_probe(scenario)
        self.assertFalse(result.connected)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.loop_start_calls, 0)
        self.assertEqual(client.loop_stop_calls, 0)
        self.assertEqual(len(client.connect_calls), 1)
        self.assertEqual(client.publish_calls, 0)

    def test_invalid_documented_hub_id_never_connects(self):
        scenario = FakePahoScenario()
        with mock.patch.object(
            DISCOVERY.importlib,
            "import_module",
            return_value=scenario.module(),
        ):
            result = DISCOVERY.passive_mqtt_discover(
                BROKER_IP,
                1883,
                timeout=0.01,
                expected_hub_id="not-documented",
            )
        self.assertFalse(result.connected)
        self.assertEqual(scenario.clients, [])

    def test_failure_log_contains_no_connection_values(self):
        values = (
            BROKER_IP,
            "fabricated-user-private",
            "fabricated-password-private",
            HUB_ID,
        )
        with (
            mock.patch.object(
                DISCOVERY.importlib,
                "import_module",
                side_effect=RuntimeError("fabricated import failure"),
            ),
            self.assertLogs(DISCOVERY._LOGGER.name, level="DEBUG") as captured,
        ):
            result = DISCOVERY.passive_mqtt_discover(
                values[0],
                1883,
                timeout=0.01,
                expected_hub_id=values[3],
                username=values[1],
                password=values[2],
            )
        self.assertFalse(result.connected)
        log_text = " ".join(captured.output)
        self.assertIn("GRIT MQTT discovery failed", log_text)
        for value in values:
            self.assertNotIn(value, log_text)


if __name__ == "__main__":
    unittest.main()

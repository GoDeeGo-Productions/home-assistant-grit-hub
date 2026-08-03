"""Network-free tests for GRIT MQTT config-entry lifecycle wiring."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import functools
import importlib.util
from pathlib import Path
import socket
import sys
import threading
import types
from typing import Any, Callable
import unittest
from unittest import mock


THREAD_TIMEOUT = 5
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
FABRICATED_BASE_URL = "https://api.fabricated.invalid"
FABRICATED_REST_TOKEN = "fabricated-rest-token"
FABRICATED_MQTT_HOST = "broker.fabricated.invalid"
FABRICATED_MQTT_HUB = "hub-fabricated"
FABRICATED_MQTT_USERNAME = "fabricated-user"
FABRICATED_MQTT_PASSWORD = "fabricated-password"
FABRICATED_DEVICE = "device-fabricated"


class ConfigEntryError(Exception):
    """Home Assistant config-entry configuration error stub."""


class ConfigEntryNotReady(Exception):
    """Home Assistant retryable setup error stub."""


class HomeAssistantError(Exception):
    """Home Assistant service error stub."""


class Scenario:
    """Mutable controls and observations shared by the fake runtime objects."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.apis: list[FakeApi] = []
        self.coordinators: list[FakeCoordinator] = []
        self.mqtt_clients: list[FakeMqtt] = []
        self.start_result = True
        self.start_state: bool | None = True
        self.start_error: Exception | None = None
        self.rest_error: Exception | None = None
        self.reconciliation_stop_error: Exception | None = None
        self.forward_error: Exception | None = None
        self.forward_hook: Callable[[], None] | None = None
        self.forward_entered = threading.Event()
        self.forward_release: asyncio.Event | None = None
        self.unload_result = True
        self.unload_error: Exception | None = None
        self.start_entered = threading.Event()
        self.start_release: threading.Event | None = None
        self.start_finished = threading.Event()
        self.stop_active_values: list[bool] = []
        self.runtime_for_stop: Any | None = None
        self.main_thread_id = threading.get_ident()


class FakeApi:
    """REST client stand-in that cannot perform I/O."""

    def __init__(
        self,
        hass: FakeHass,
        base_url: str,
        token: str,
        verify_ssl: bool,
    ) -> None:
        self.hass = hass
        self.base_url = base_url
        self.token = token
        self.verify_ssl = verify_ssl
        hass.scenario.events.append("api_construct")
        hass.scenario.apis.append(self)

    async def device_command(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def refresh_device(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def locate_device(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class GritHubApiError(Exception):
    """REST error stand-in."""


class FakeCoordinator:
    """Coordinator stand-in that records loop-thread state mutations."""

    def __init__(
        self,
        hass: FakeHass,
        api: FakeApi,
        scan_interval: int,
        *,
        expected_mqtt_hub_id: str | None = None,
    ) -> None:
        self.hass = hass
        self.api = api
        self.scan_interval = scan_interval
        self.expected_mqtt_hub_id = expected_mqtt_hub_id
        self.mqtt_connected = False
        self.listener_updates = 0
        self.data = {
            "devices": {
                "gate": [{"id": FABRICATED_DEVICE, "name": "Fabricated gate"}]
            }
        }
        self.messages: list[tuple[Any, ...]] = []
        self.message_thread_ids: list[int] = []
        self.reconciliation_starts = 0
        self.reconciliation_stops = 0
        hass.scenario.events.append("coordinator_construct")
        hass.scenario.coordinators.append(self)

    async def async_config_entry_first_refresh(self) -> None:
        self.hass.scenario.events.append("rest_refresh")
        if self.hass.scenario.rest_error is not None:
            raise self.hass.scenario.rest_error

    def handle_mqtt_message(self, *message: Any) -> None:
        self.hass.scenario.events.append("mqtt_message_apply")
        self.messages.append(message)
        self.message_thread_ids.append(threading.get_ident())

    def set_mqtt_connected(self, connected: bool) -> bool:
        if self.mqtt_connected == connected:
            return False
        self.mqtt_connected = connected
        self.listener_updates += 1
        self.hass.scenario.events.append(
            "mqtt_state_connected" if connected else "mqtt_state_disconnected"
        )
        return True

    def start_state_reconciliation(self) -> bool:
        self.reconciliation_starts += 1
        return True

    async def async_stop_state_reconciliation(self) -> None:
        self.reconciliation_stops += 1
        if self.hass.scenario.reconciliation_stop_error is not None:
            raise self.hass.scenario.reconciliation_stop_error
    async def async_request_refresh(self) -> None:
        return None


class FakeMqtt:
    """Standalone MQTT client stand-in with no Paho, threads, or sockets."""

    def __init__(
        self,
        host: str,
        port: int,
        message_callback: Callable[..., None],
        *,
        username: str | None = None,
        password: str | None = None,
        keepalive: int,
        use_tls: bool,
        verify_tls: bool,
        connection_state_callback: Callable[[bool], None],
    ) -> None:
        hass = _ACTIVE_HASS
        if hass is None:
            raise AssertionError("fake MQTT constructed without an active harness")
        self.scenario = hass.scenario
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.keepalive = keepalive
        self.use_tls = use_tls
        self.verify_tls = verify_tls
        self.message_callback = message_callback
        self.connection_state_callback = connection_state_callback
        self.start_thread_id: int | None = None
        self.stop_thread_ids: list[int] = []
        self.start_calls = 0
        self.stop_calls = 0
        self.stopped = False
        self.scenario.events.append("mqtt_construct")
        self.scenario.mqtt_clients.append(self)

    def start(self) -> bool:
        self.start_calls += 1
        self.start_thread_id = threading.get_ident()
        self.scenario.events.append("mqtt_start")
        self.scenario.start_entered.set()
        try:
            start_release = self.scenario.start_release
            if start_release is not None and not start_release.wait(THREAD_TIMEOUT):
                raise TimeoutError("fake MQTT start release timed out")
            if self.scenario.start_error is not None:
                raise self.scenario.start_error
            if self.scenario.start_state is not None:
                self.connection_state_callback(self.scenario.start_state)
            return self.scenario.start_result
        finally:
            self.scenario.start_finished.set()

    def stop(self) -> None:
        self.stop_calls += 1
        self.stop_thread_ids.append(threading.get_ident())
        runtime = self.scenario.runtime_for_stop
        if runtime is not None:
            self.scenario.stop_active_values.append(runtime.active)
        if self.scenario.start_release is not None:
            self.scenario.start_release.set()
        self.stopped = True
        self.scenario.events.append("mqtt_stop")

    def emit_message(self, *message: Any) -> None:
        self.message_callback(*message)

    def emit_connection_state(self, connected: bool) -> None:
        self.connection_state_callback(connected)


_ACTIVE_HASS: FakeHass | None = None


class _Schema:
    def __init__(self, schema: Any) -> None:
        self.schema = schema


def _identity_key(key: Any, **_kwargs: Any) -> Any:
    return key


def _any_validator(*_validators: Any) -> object:
    return object()


def _install_stubs(package_name: str) -> None:
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Schema = _Schema
    voluptuous.Required = _identity_key
    voluptuous.Optional = _identity_key
    voluptuous.Any = _any_validator
    sys.modules["voluptuous"] = voluptuous

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    exceptions = types.ModuleType("homeassistant.exceptions")
    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    core.ServiceCall = object
    exceptions.ConfigEntryError = ConfigEntryError
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    exceptions.HomeAssistantError = HomeAssistantError
    homeassistant.config_entries = config_entries
    homeassistant.core = core
    homeassistant.exceptions = exceptions
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions

    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules[package_name] = package

    api_module = types.ModuleType(f"{package_name}.api")
    api_module.GritHubApiClient = FakeApi
    api_module.GritHubApiError = GritHubApiError
    sys.modules[api_module.__name__] = api_module

    coordinator_module = types.ModuleType(f"{package_name}.coordinator")
    coordinator_module.GritHubCoordinator = FakeCoordinator
    sys.modules[coordinator_module.__name__] = coordinator_module

    mqtt_module = types.ModuleType(f"{package_name}.mqtt_live")
    mqtt_module.GritLiveMqtt = FakeMqtt
    sys.modules[mqtt_module.__name__] = mqtt_module


def _load_runtime_module() -> types.ModuleType:
    package_name = "_grit_runtime_tests"
    _install_stubs(package_name)

    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", COMPONENT_ROOT / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)

    runtime_spec = importlib.util.spec_from_file_location(
        package_name, COMPONENT_ROOT / "__init__.py"
    )
    runtime_module = importlib.util.module_from_spec(runtime_spec)
    sys.modules[package_name] = runtime_module
    runtime_spec.loader.exec_module(runtime_module)
    return runtime_module


RUNTIME_MODULE = _load_runtime_module()


class LoopProxy:
    """Record and optionally hold thread-safe callback scheduling."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self.hold_callbacks = False
        self.queued: list[tuple[Callable[..., None], tuple[Any, ...]]] = []
        self.scheduling_thread_ids: list[int] = []

    def create_future(self) -> asyncio.Future[Any]:
        return self._loop.create_future()

    def call_soon_threadsafe(
        self,
        callback: Callable[..., None],
        *args: Any,
    ) -> Any:
        with self._lock:
            self.scheduling_thread_ids.append(threading.get_ident())
            if self.hold_callbacks:
                self.queued.append((callback, args))
                return None
        return self._loop.call_soon_threadsafe(callback, *args)

    def flush(self) -> None:
        with self._lock:
            queued = list(self.queued)
            self.queued.clear()
        for callback, args in queued:
            callback(*args)


class FakeServices:
    """Service registry stand-in; existing registration avoids schema work."""

    def has_service(self, _domain: str, _service: str) -> bool:
        return True

    def async_register(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("services should already be registered in tests")


class FakeConfigEntries:
    def __init__(self, hass: FakeHass) -> None:
        self.hass = hass
        self.forward_calls = 0
        self.unload_calls = 0
        self.forwarded_platforms: list[list[str]] = []
        self.unloaded_platforms: list[list[str]] = []

    async def async_forward_entry_setups(
        self,
        _entry: FakeEntry,
        _platforms: list[str],
    ) -> None:
        self.forward_calls += 1
        self.forwarded_platforms.append(list(_platforms))
        self.hass.scenario.events.append("forward_platforms")
        if self.hass.scenario.forward_hook is not None:
            self.hass.scenario.forward_hook()
        self.hass.scenario.forward_entered.set()
        if self.hass.scenario.forward_release is not None:
            await self.hass.scenario.forward_release.wait()
        if self.hass.scenario.forward_error is not None:
            raise self.hass.scenario.forward_error

    async def async_unload_platforms(
        self,
        _entry: FakeEntry,
        _platforms: list[str],
    ) -> bool:
        self.unload_calls += 1
        self.unloaded_platforms.append(list(_platforms))
        self.hass.scenario.events.append("unload_platforms")
        if self.hass.scenario.unload_error is not None:
            raise self.hass.scenario.unload_error
        return self.hass.scenario.unload_result


class FakeHass:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._real_loop = asyncio.get_running_loop()
        self.loop = LoopProxy(self._real_loop)
        self.data: dict[str, Any] = {}
        self.config_entries = FakeConfigEntries(self)
        self.services = FakeServices()

    async def async_add_executor_job(
        self,
        target: Callable[..., Any],
        *args: Any,
    ) -> Any:
        call = functools.partial(target, *args)
        return await self._real_loop.run_in_executor(None, call)


class FakeEntry:
    def __init__(
        self,
        data: dict[str, Any],
        *,
        fail_runtime_assignment: bool = False,
    ) -> None:
        self.data = data
        self.options: dict[str, Any] = {}
        self.entry_id = "entry-fabricated"
        self._runtime_data: Any | None = None
        self.fail_runtime_assignment = fail_runtime_assignment

    @property
    def runtime_data(self) -> Any | None:
        return self._runtime_data

    @runtime_data.setter
    def runtime_data(self, value: Any | None) -> None:
        if value is not None and self.fail_runtime_assignment:
            raise RuntimeError("fabricated runtime assignment failure")
        self._runtime_data = value


def valid_entry_data() -> dict[str, Any]:
    return {
        RUNTIME_MODULE.CONF_BASE_URL: FABRICATED_BASE_URL,
        RUNTIME_MODULE.CONF_TOKEN: FABRICATED_REST_TOKEN,
        RUNTIME_MODULE.CONF_VERIFY_SSL: True,
        RUNTIME_MODULE.CONF_SCAN_INTERVAL: 45,
        RUNTIME_MODULE.CONF_MQTT_HOST: FABRICATED_MQTT_HOST,
        RUNTIME_MODULE.CONF_MQTT_PORT: 8883,
        RUNTIME_MODULE.CONF_MQTT_HUB_ID: FABRICATED_MQTT_HUB,
        RUNTIME_MODULE.CONF_MQTT_USERNAME: FABRICATED_MQTT_USERNAME,
        RUNTIME_MODULE.CONF_MQTT_PASSWORD: FABRICATED_MQTT_PASSWORD,
        RUNTIME_MODULE.CONF_MQTT_USE_TLS: True,
        RUNTIME_MODULE.CONF_MQTT_VERIFY_TLS: True,
        RUNTIME_MODULE.CONF_MQTT_KEEPALIVE: 90,
    }


class RuntimeMqttTests(unittest.IsolatedAsyncioTestCase):
    """Exercise setup, callbacks, readiness, and unload without network I/O."""

    def setUp(self) -> None:
        connect_patch = mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_ex_patch = mock.patch.object(
            socket.socket,
            "connect_ex",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connection_patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        connect_patch.start()
        connect_ex_patch.start()
        connection_patch.start()
        self.addCleanup(connect_patch.stop)
        self.addCleanup(connect_ex_patch.stop)
        self.addCleanup(connection_patch.stop)

    async def asyncSetUp(self) -> None:
        self.scenario = Scenario()
        self.hass = FakeHass(self.scenario)
        global _ACTIVE_HASS
        _ACTIVE_HASS = self.hass

    async def asyncTearDown(self) -> None:
        for mqtt in self.scenario.mqtt_clients:
            if not mqtt.stopped:
                await self.hass.async_add_executor_job(mqtt.stop)
        global _ACTIVE_HASS
        _ACTIVE_HASS = None

    async def setup_entry(
        self,
        data: dict[str, Any] | None = None,
        *,
        fail_runtime_assignment: bool = False,
    ) -> FakeEntry:
        entry = FakeEntry(
            valid_entry_data() if data is None else data,
            fail_runtime_assignment=fail_runtime_assignment,
        )
        result = await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertTrue(result)
        return entry

    async def test_valid_config_ordering_readiness_and_storage(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        mqtt = runtime.mqtt
        coordinator = runtime.coordinator

        self.assertEqual(
            self.scenario.events[:7],
            [
                "api_construct",
                "coordinator_construct",
                "rest_refresh",
                "mqtt_construct",
                "mqtt_start",
                "mqtt_state_connected",
                "forward_platforms",
            ],
        )
        self.assertTrue(coordinator.mqtt_connected)
        self.assertEqual(coordinator.reconciliation_starts, 1)
        self.assertEqual(
            self.hass.config_entries.forwarded_platforms,
            [list(RUNTIME_MODULE.PLATFORMS)],
        )
        self.assertEqual(
            set(RUNTIME_MODULE.PLATFORMS),
            {
                "sensor",
                "binary_sensor",
                "switch",
                "cover",
                "button",
                "lock",
                "number",
            },
        )
        self.assertEqual(coordinator.expected_mqtt_hub_id, FABRICATED_MQTT_HUB)
        self.assertEqual(mqtt.host, FABRICATED_MQTT_HOST)
        self.assertEqual(mqtt.port, 8883)
        self.assertEqual(mqtt.username, FABRICATED_MQTT_USERNAME)
        self.assertEqual(mqtt.password, FABRICATED_MQTT_PASSWORD)
        self.assertEqual(mqtt.keepalive, 90)
        self.assertTrue(mqtt.use_tls)
        self.assertTrue(mqtt.verify_tls)
        self.assertNotEqual(mqtt.start_thread_id, self.scenario.main_thread_id)
        self.assertIs(
            self.hass.data[RUNTIME_MODULE.DOMAIN][entry.entry_id]["coordinator"],
            coordinator,
        )
        self.assertNotIn(
            "api", self.hass.data[RUNTIME_MODULE.DOMAIN][entry.entry_id]
        )
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_duplicate_successful_setup_reuses_active_runtime(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data

        self.assertTrue(
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        )

        self.assertIs(entry.runtime_data, runtime)
        self.assertEqual(len(self.scenario.apis), 1)
        self.assertEqual(len(self.scenario.coordinators), 1)
        self.assertEqual(len(self.scenario.mqtt_clients), 1)
        self.assertEqual(runtime.mqtt.start_calls, 1)
        self.assertEqual(runtime.coordinator.reconciliation_starts, 1)
        self.assertEqual(self.hass.config_entries.forward_calls, 1)
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_provisional_defaults_apply_without_stored_overrides(
        self,
    ) -> None:
        data = valid_entry_data()
        data.pop(RUNTIME_MODULE.CONF_MQTT_USERNAME)
        data.pop(RUNTIME_MODULE.CONF_MQTT_PASSWORD)
        original = deepcopy(data)

        entry = await self.setup_entry(data)
        mqtt = entry.runtime_data.mqtt

        self.assertEqual(
            mqtt.username,
            RUNTIME_MODULE.DEFAULT_MQTT_USERNAME,
        )
        self.assertEqual(
            mqtt.password,
            RUNTIME_MODULE.DEFAULT_MQTT_PASSWORD,
        )
        self.assertEqual(entry.data, original)
        self.assertNotIn(
            RUNTIME_MODULE.DEFAULT_MQTT_USERNAME,
            repr(entry.data),
        )
        self.assertNotIn(
            RUNTIME_MODULE.DEFAULT_MQTT_USERNAME,
            repr(entry.runtime_data.coordinator.__dict__),
        )
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_message_callback_is_marshaled_to_event_loop(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        self.hass.loop.hold_callbacks = True
        message = (
            FABRICATED_MQTT_HUB,
            "gate",
            FABRICATED_DEVICE,
            "status/detail",
            {"online": True},
        )
        with self.assertNoLogs(RUNTIME_MODULE._LOGGER, level="DEBUG"):
            thread = threading.Thread(
                target=runtime.mqtt.emit_message, args=message
            )
            thread.start()
            thread.join(THREAD_TIMEOUT)
            self.assertFalse(
                thread.is_alive(), "fake callback thread did not finish"
            )
            self.assertEqual(runtime.coordinator.messages, [])
            self.assertEqual(len(self.hass.loop.queued), 1)
            self.hass.loop.flush()

        self.assertEqual(runtime.coordinator.messages, [message])
        self.assertEqual(
            runtime.coordinator.message_thread_ids,
            [self.scenario.main_thread_id],
        )
        self.assertNotEqual(
            self.hass.loop.scheduling_thread_ids[-1],
            self.scenario.main_thread_id,
        )
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_connection_changes_notify_without_mutating_device_data(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        coordinator = runtime.coordinator
        original_data = deepcopy(coordinator.data)
        initial_updates = coordinator.listener_updates
        self.hass.loop.hold_callbacks = True

        runtime.mqtt.emit_connection_state(False)
        self.hass.loop.flush()
        self.assertFalse(coordinator.mqtt_connected)
        self.assertEqual(coordinator.listener_updates, initial_updates + 1)
        runtime.mqtt.emit_connection_state(False)
        self.hass.loop.flush()
        self.assertEqual(coordinator.listener_updates, initial_updates + 1)
        runtime.mqtt.emit_connection_state(True)
        self.hass.loop.flush()
        self.assertTrue(coordinator.mqtt_connected)
        self.assertEqual(coordinator.listener_updates, initial_updates + 2)
        self.assertEqual(coordinator.reconciliation_starts, 2)
        self.assertEqual(coordinator.data, original_data)
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_message_queued_after_disconnect_is_ignored(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        self.hass.loop.hold_callbacks = True

        runtime.mqtt.emit_connection_state(False)
        runtime.mqtt.emit_message(
            FABRICATED_MQTT_HUB,
            "gate",
            FABRICATED_DEVICE,
            "status",
            {"online": True},
        )
        self.hass.loop.flush()

        self.assertFalse(runtime.coordinator.mqtt_connected)
        self.assertEqual(runtime.coordinator.messages, [])
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)
    async def test_start_false_is_retryable_and_fully_cleaned(self) -> None:
        self.scenario.start_result = False
        self.scenario.start_state = None
        entry = FakeEntry(valid_entry_data())
        with self.assertRaises(ConfigEntryNotReady):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        mqtt = self.scenario.mqtt_clients[0]
        self.assertTrue(mqtt.stopped)
        self.assertEqual(mqtt.stop_calls, 1)
        self.assertEqual(
            self.scenario.coordinators[0].reconciliation_stops,
            1,
        )
        self.assertIsNone(entry.runtime_data)
        self.assertEqual(self.hass.config_entries.forward_calls, 0)
        self.assertNotIn(entry.entry_id, self.hass.data.get("grit_hub", {}))

    async def test_start_exception_is_retryable_and_fully_cleaned(self) -> None:
        self.scenario.start_error = RuntimeError("fabricated start failure")
        self.scenario.start_state = None
        entry = FakeEntry(valid_entry_data())
        with self.assertRaises(ConfigEntryNotReady) as captured:
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertNotIn(FABRICATED_MQTT_HOST, str(captured.exception))
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertEqual(self.hass.config_entries.forward_calls, 0)
    async def test_connection_rejection_is_retryable_and_cleaned(self) -> None:
        self.scenario.start_state = False
        entry = FakeEntry(valid_entry_data())
        with self.assertRaisesRegex(ConfigEntryNotReady, "not ready"):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertTrue(self.scenario.mqtt_clients[0].stopped)
        self.assertEqual(self.hass.config_entries.forward_calls, 0)

    async def test_subscription_failure_state_is_retryable_and_cleaned(self) -> None:
        self.scenario.start_state = False
        entry = FakeEntry(valid_entry_data())
        with self.assertRaises(ConfigEntryNotReady):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertFalse(self.scenario.coordinators[0].mqtt_connected)

    async def test_readiness_timeout_is_retryable_and_cleaned(self) -> None:
        self.scenario.start_state = None
        entry = FakeEntry(valid_entry_data())
        with mock.patch.object(RUNTIME_MODULE, "MQTT_READY_TIMEOUT", 0.01):
            with self.assertRaises(ConfigEntryNotReady):
                await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertEqual(self.hass.config_entries.forward_calls, 0)

    async def test_invalid_stored_mqtt_values_fail_before_client_creation(self) -> None:
        cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
            ("missing host", lambda data: data.pop(RUNTIME_MODULE.CONF_MQTT_HOST)),
            ("missing hub", lambda data: data.pop(RUNTIME_MODULE.CONF_MQTT_HUB_ID)),
            (
                "malformed port",
                lambda data: data.__setitem__(RUNTIME_MODULE.CONF_MQTT_PORT, "8883"),
            ),
            (
                "password without username",
                lambda data: data.__setitem__(RUNTIME_MODULE.CONF_MQTT_USERNAME, " "),
            ),
            (
                "invalid hub component",
                lambda data: data.__setitem__(RUNTIME_MODULE.CONF_MQTT_HUB_ID, "bad/hub"),
            ),
        ]
        for label, mutate in cases:
            with self.subTest(label=label):
                scenario = Scenario()
                hass = FakeHass(scenario)
                global _ACTIVE_HASS
                _ACTIVE_HASS = hass
                data = valid_entry_data()
                mutate(data)
                entry = FakeEntry(data)
                with self.assertNoLogs(RUNTIME_MODULE._LOGGER, level="DEBUG"):
                    with self.assertRaises(ConfigEntryError) as captured:
                        await RUNTIME_MODULE.async_setup_entry(hass, entry)
                self.assertEqual(scenario.apis, [])
                self.assertEqual(scenario.mqtt_clients, [])
                error_text = str(captured.exception)
                for value in (
                    FABRICATED_MQTT_HOST,
                    FABRICATED_MQTT_HUB,
                    FABRICATED_MQTT_USERNAME,
                    FABRICATED_MQTT_PASSWORD,
                ):
                    self.assertNotIn(value, error_text)
        _ACTIVE_HASS = self.hass

    async def test_rest_discovery_failure_prevents_mqtt_construction(self) -> None:
        self.scenario.rest_error = RuntimeError("fabricated discovery failure")
        entry = FakeEntry(valid_entry_data())
        with self.assertRaises(RuntimeError):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertEqual(self.scenario.mqtt_clients, [])
        self.assertEqual(self.hass.config_entries.forward_calls, 0)

    async def test_runtime_assignment_failure_stops_partial_runtime(self) -> None:
        entry = FakeEntry(valid_entry_data(), fail_runtime_assignment=True)
        with self.assertRaisesRegex(RuntimeError, "runtime assignment"):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertIsNone(entry.runtime_data)
        self.assertEqual(self.hass.config_entries.forward_calls, 0)

    async def test_platform_forward_failure_stops_and_ignores_queued_callback(self) -> None:
        self.scenario.forward_error = RuntimeError("fabricated forward failure")

        def queue_message() -> None:
            self.hass.loop.hold_callbacks = True
            self.scenario.mqtt_clients[0].emit_message(
                FABRICATED_MQTT_HUB,
                "gate",
                FABRICATED_DEVICE,
                "status",
                {"online": True},
            )

        self.scenario.forward_hook = queue_message
        entry = FakeEntry(valid_entry_data())
        with self.assertRaisesRegex(RuntimeError, "forward failure"):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        coordinator = self.scenario.coordinators[0]
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertIsNone(entry.runtime_data)
        self.assertNotIn(entry.entry_id, self.hass.data.get("grit_hub", {}))
        self.assertEqual(self.hass.config_entries.unload_calls, 1)
        self.assertEqual(
            self.hass.config_entries.unloaded_platforms,
            [list(RUNTIME_MODULE.PLATFORMS)],
        )
        self.hass.loop.flush()
        self.assertEqual(coordinator.messages, [])

    async def test_cancelled_platform_rollback_still_stops_runtime(self) -> None:
        self.scenario.forward_error = RuntimeError(
            "fabricated forward failure"
        )
        self.scenario.unload_error = asyncio.CancelledError()
        entry = FakeEntry(valid_entry_data())

        with self.assertRaises(asyncio.CancelledError):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)

        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertIsNone(entry.runtime_data)
        self.assertNotIn(entry.entry_id, self.hass.data.get("grit_hub", {}))

    async def test_successful_unload_stops_off_loop_after_platforms(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        self.scenario.runtime_for_stop = runtime
        result = await RUNTIME_MODULE.async_unload_entry(self.hass, entry)
        self.assertTrue(result)
        self.assertLess(
            self.scenario.events.index("unload_platforms"),
            self.scenario.events.index("mqtt_stop"),
        )
        self.assertEqual(runtime.mqtt.stop_calls, 1)
        self.assertEqual(runtime.coordinator.reconciliation_stops, 1)
        self.assertEqual(
            self.hass.config_entries.unloaded_platforms,
            [list(RUNTIME_MODULE.PLATFORMS)],
        )
        self.assertNotEqual(
            runtime.mqtt.stop_thread_ids[0], self.scenario.main_thread_id
        )
        self.assertEqual(self.scenario.stop_active_values, [False])
        self.assertFalse(runtime.active)
        self.assertTrue(runtime.unloading)
        self.assertIsNone(entry.runtime_data)
        self.assertNotIn(entry.entry_id, self.hass.data["grit_hub"])

    async def test_reconciliation_cleanup_error_still_stops_mqtt(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        self.scenario.reconciliation_stop_error = RuntimeError(
            "fabricated reconciliation cleanup failure"
        )

        with self.assertRaisesRegex(RuntimeError, "cleanup failure"):
            await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

        self.assertEqual(runtime.coordinator.reconciliation_stops, 1)
        self.assertEqual(runtime.mqtt.stop_calls, 1)
        self.assertTrue(runtime.mqtt.stopped)
        self.assertIsNone(entry.runtime_data)
        self.assertNotIn(entry.entry_id, self.hass.data["grit_hub"])
    async def test_unload_then_reload_creates_one_replacement_runtime(self) -> None:
        entry = await self.setup_entry()
        original_runtime = entry.runtime_data
        self.assertTrue(
            await RUNTIME_MODULE.async_unload_entry(self.hass, entry)
        )

        self.assertTrue(
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        )
        replacement_runtime = entry.runtime_data
        self.assertIsNot(replacement_runtime, original_runtime)
        self.assertEqual(len(self.scenario.mqtt_clients), 2)
        self.assertEqual(self.hass.config_entries.forward_calls, 2)
        self.assertEqual(self.hass.config_entries.unload_calls, 1)
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_failed_setup_can_retry_same_entry_cleanly(self) -> None:
        self.scenario.start_result = False
        self.scenario.start_state = None
        entry = FakeEntry(valid_entry_data())
        with self.assertRaises(ConfigEntryNotReady):
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)

        self.scenario.start_result = True
        self.scenario.start_state = True
        self.assertTrue(
            await RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        )
        self.assertEqual(len(self.scenario.mqtt_clients), 2)
        self.assertTrue(self.scenario.mqtt_clients[0].stopped)
        self.assertTrue(entry.runtime_data.active)
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_failed_platform_unload_leaves_runtime_active(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        self.scenario.unload_result = False
        self.assertFalse(await RUNTIME_MODULE.async_unload_entry(self.hass, entry))
        self.assertTrue(runtime.active)
        self.assertFalse(runtime.unloading)
        self.assertEqual(runtime.mqtt.stop_calls, 0)
        self.assertIs(entry.runtime_data, runtime)
        self.assertIn(entry.entry_id, self.hass.data["grit_hub"])
        self.scenario.unload_result = True
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)

    async def test_repeated_unload_does_not_stop_twice(self) -> None:
        entry = await self.setup_entry()
        mqtt = entry.runtime_data.mqtt
        self.assertTrue(await RUNTIME_MODULE.async_unload_entry(self.hass, entry))
        self.assertTrue(await RUNTIME_MODULE.async_unload_entry(self.hass, entry))
        self.assertEqual(mqtt.stop_calls, 1)

    async def test_callbacks_queued_before_unload_are_ignored_after_deactivation(self) -> None:
        entry = await self.setup_entry()
        runtime = entry.runtime_data
        coordinator = runtime.coordinator
        self.hass.loop.hold_callbacks = True
        runtime.mqtt.emit_message(
            FABRICATED_MQTT_HUB,
            "gate",
            FABRICATED_DEVICE,
            "status",
            {"online": True},
        )
        runtime.mqtt.emit_connection_state(False)
        self.assertEqual(len(self.hass.loop.queued), 2)
        await RUNTIME_MODULE.async_unload_entry(self.hass, entry)
        self.hass.loop.flush()
        self.assertEqual(coordinator.messages, [])
        self.assertTrue(coordinator.mqtt_connected)

    async def test_cancellation_during_start_cleans_up_and_propagates(self) -> None:
        self.scenario.start_state = None
        self.scenario.start_release = threading.Event()
        entry = FakeEntry(valid_entry_data())
        task = asyncio.create_task(
            RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        )
        started = await asyncio.to_thread(
            self.scenario.start_entered.wait, THREAD_TIMEOUT
        )
        self.assertTrue(started, "fake MQTT start was not reached")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        finished = await asyncio.to_thread(
            self.scenario.start_finished.wait, THREAD_TIMEOUT
        )
        self.assertTrue(finished, "fake MQTT start did not finish")
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertIsNone(entry.runtime_data)

    async def test_cancellation_during_platform_forward_cleans_runtime(self) -> None:
        self.scenario.forward_release = asyncio.Event()
        entry = FakeEntry(valid_entry_data())
        task = asyncio.create_task(
            RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        )
        forwarded = await asyncio.to_thread(
            self.scenario.forward_entered.wait, THREAD_TIMEOUT
        )
        self.assertTrue(forwarded, "platform forwarding was not reached")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertIsNone(entry.runtime_data)
        self.assertNotIn(entry.entry_id, self.hass.data.get("grit_hub", {}))
        self.assertEqual(self.hass.config_entries.unload_calls, 1)
        self.assertEqual(
            self.hass.config_entries.unloaded_platforms,
            [list(RUNTIME_MODULE.PLATFORMS)],
        )

    async def test_setup_cancellation_cleans_up_and_propagates(self) -> None:
        self.scenario.start_state = None
        entry = FakeEntry(valid_entry_data())
        task = asyncio.create_task(
            RUNTIME_MODULE.async_setup_entry(self.hass, entry)
        )
        started = await asyncio.to_thread(
            self.scenario.start_entered.wait, THREAD_TIMEOUT
        )
        self.assertTrue(started, "fake MQTT start was not reached")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.scenario.mqtt_clients[0].stop_calls, 1)
        self.assertIsNone(entry.runtime_data)
        self.assertEqual(self.hass.config_entries.forward_calls, 0)


if __name__ == "__main__":
    unittest.main()
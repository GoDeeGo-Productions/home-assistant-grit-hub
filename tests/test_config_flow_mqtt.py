"""Network-free tests for GRIT installation and MQTT configuration flows."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
import json
import logging
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
PACKAGE_NAME = "_grit_config_flow_tests"

FABRICATED_BASE_URL = "https://api.config-test.invalid"
FABRICATED_TOKEN = "fabricated-api-token"
FABRICATED_LEGACY_TOKEN = (
    "eyJhbGciOiJmYWJyaWNhdGVkIn0."
    + ("A" * 5_000)
    + ".fabricated-signature"
)
FABRICATED_MQTT_HOST = "192.0.2.44"
FABRICATED_HUB_ID = "0123456789abcdef0123456789abcdef"
FABRICATED_OTHER_HUB_ID = "fedcba9876543210fedcba9876543210"
FABRICATED_USERNAME = "fabricated-mqtt-user"
FABRICATED_PASSWORD = "fabricated-mqtt-password"


class _Undefined:
    pass


UNDEFINED = _Undefined()


class Marker:
    def __init__(self, schema, default=UNDEFINED):
        self.schema = schema
        self.default = default


class Required(Marker):
    pass


class Optional(Marker):
    pass


class Schema:
    def __init__(self, schema):
        self.schema = schema


class Range:
    def __init__(self, *, min=None, max=None):
        self.min = min
        self.max = max


class All:
    def __init__(self, *validators):
        self.validators = validators


class TextSelectorType:
    PASSWORD = "password"


class TextSelectorConfig:
    def __init__(self, *, type=None):
        self.type = type


class TextSelector:
    def __init__(self, config):
        self.config = config


class FakeEntry:
    def __init__(self, data, options=None):
        self.data = deepcopy(data)
        self.options = deepcopy(options or {})
        self.entry_id = "fabricated-entry-id"
        self.unique_id = "fabricated-stable-identity"
        self.entity_id = "lock.fabricated_reader"
        self.device_id = "fabricated-device-registry-id"


class FakeConfigEntries:
    def __init__(self):
        self.update_calls = []
        self.reload_calls = []

    def async_update_entry(self, entry, *, data=None, options=None):
        self.update_calls.append(
            {
                "entry": entry,
                "data": deepcopy(data),
                "options": deepcopy(options),
            }
        )
        if data is not None:
            entry.data = deepcopy(data)
        if options is not None:
            entry.options = deepcopy(options)


class FakeHass:
    def __init__(self):
        self.executor_calls = []
        self.config_entries = FakeConfigEntries()

    async def async_add_executor_job(self, function, *args):
        self.executor_calls.append((function, args))
        return function(*args)


class _FlowBase:
    def __init__(self):
        self.hass = FakeHass()
        self.created_entries = []
        self.updated_entries = []
        self._reconfigure_entry = None
        self.unique_id = None

    def async_show_form(
        self,
        *,
        step_id,
        data_schema,
        errors=None,
        description_placeholders=None,
    ):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders or {},
        }

    def async_create_entry(self, *, title, data):
        self.created_entries.append((title, deepcopy(data)))
        return {"type": "create_entry", "title": title, "data": data}


class ConfigFlow(_FlowBase):
    def __init_subclass__(cls, *, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        return None

    def _get_reconfigure_entry(self):
        if self._reconfigure_entry is None:
            raise AssertionError("reconfigure entry was not supplied")
        return self._reconfigure_entry

    def async_update_reload_and_abort(
        self,
        entry,
        *,
        data_updates,
    ):
        self.hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, **deepcopy(data_updates)},
        )
        self.hass.config_entries.reload_calls.append(entry.entry_id)
        self.updated_entries.append(entry)
        return {"type": "abort", "reason": "reconfigure_successful"}


class OptionsFlow(_FlowBase):
    pass


class FakeApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status


class FakeApi:
    health_calls = 0
    hub_calls = 0
    constructor_tokens = []
    health_error = False
    hub_error = False
    hub_status = None
    hub_values = {}
    read_events = []

    def __init__(self, _hass, _base_url, token, _verify_ssl):
        type(self).constructor_tokens.append(token)

    async def health_check(self):
        type(self).health_calls += 1
        type(self).read_events.append("health")
        if type(self).health_error:
            raise FakeApiError("fabricated health failure")
        return {"status": "ok"}

    async def get_hub(self):
        type(self).hub_calls += 1
        type(self).read_events.append("hub")
        if type(self).hub_error:
            raise FakeApiError(
                "fabricated hub failure",
                http_status=type(self).hub_status,
            )
        return deepcopy(type(self).hub_values)


def _install_stubs():
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Required = Required
    voluptuous.Optional = Optional
    voluptuous.Schema = Schema
    voluptuous.Range = Range
    voluptuous.All = All
    sys.modules["voluptuous"] = voluptuous

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow

    core = types.ModuleType("homeassistant.core")
    core.callback = lambda function: function

    helpers = types.ModuleType("homeassistant.helpers")
    selector = types.ModuleType("homeassistant.helpers.selector")
    selector.TextSelector = TextSelector
    selector.TextSelectorConfig = TextSelectorConfig
    selector.TextSelectorType = TextSelectorType
    helpers.selector = selector

    homeassistant.config_entries = config_entries
    homeassistant.helpers = helpers
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.selector"] = selector

    api = types.ModuleType(f"{PACKAGE_NAME}.api")
    api.GritHubApiClient = FakeApi
    api.GritHubApiError = FakeApiError
    sys.modules[api.__name__] = api


def _load_config_flow():
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules[PACKAGE_NAME] = package
    _install_stubs()

    const_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.const", COMPONENT_ROOT / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)

    flow_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.config_flow", COMPONENT_ROOT / "config_flow.py"
    )
    flow_module = importlib.util.module_from_spec(flow_spec)
    sys.modules[flow_spec.name] = flow_module
    flow_spec.loader.exec_module(flow_module)
    return flow_module


FLOW_MODULE = _load_config_flow()


def _run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise AssertionError("fake config-flow coroutine unexpectedly suspended")


def _schema_fields(schema):
    return {
        marker.schema: (marker, validator)
        for marker, validator in schema.schema.items()
    }


class ConfigFlowMqttTests(unittest.TestCase):
    def setUp(self):
        FakeApi.health_calls = 0
        FakeApi.hub_calls = 0
        FakeApi.constructor_tokens = []
        FakeApi.health_error = False
        FakeApi.hub_status = None
        FakeApi.hub_error = False
        FakeApi.hub_values = {
            "id": FABRICATED_HUB_ID,
            "ipAddressEthernet": FABRICATED_MQTT_HOST,
        }
        FakeApi.read_events = []
        self.probe_result = types.SimpleNamespace(
            connected=True,
            hub_id=FABRICATED_HUB_ID,
            ambiguous=False,
        )
        self.probe_calls = []
        self.probe_error = None

        def fake_probe(host, port, **kwargs):
            self.probe_calls.append(
                {"host": host, "port": port, **kwargs}
            )
            if self.probe_error is not None:
                raise self.probe_error
            if self.probe_result.connected:
                return types.SimpleNamespace(
                    connected=True,
                    hub_id=kwargs["expected_hub_id"],
                    ambiguous=False,
                )
            return self.probe_result

        probe_patch = mock.patch.object(
            FLOW_MODULE,
            "passive_mqtt_discover",
            side_effect=fake_probe,
        )
        socket_patch = mock.patch.object(
            socket,
            "socket",
            side_effect=AssertionError("network socket creation is forbidden"),
        )
        connection_patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network connection is forbidden"),
        )
        probe_patch.start()
        socket_patch.start()
        connection_patch.start()
        self.addCleanup(probe_patch.stop)
        self.addCleanup(socket_patch.stop)
        self.addCleanup(connection_patch.stop)

    def api_input(self):
        return {
            FLOW_MODULE.CONF_BASE_URL: FABRICATED_BASE_URL,
            FLOW_MODULE.CONF_TOKEN: FABRICATED_TOKEN,
            FLOW_MODULE.CONF_VERIFY_SSL: True,
        }

    def advanced_input(self):
        return {
            FLOW_MODULE.CONF_SCAN_INTERVAL: 30,
            FLOW_MODULE.CONF_MQTT_HOST: FABRICATED_MQTT_HOST,
            FLOW_MODULE.CONF_MQTT_PORT: 1883,
            FLOW_MODULE.CONF_MQTT_HUB_ID: FABRICATED_HUB_ID,
            FLOW_MODULE.CONF_MQTT_USERNAME: FABRICATED_USERNAME,
            FLOW_MODULE.CONF_MQTT_PASSWORD: FABRICATED_PASSWORD,
            FLOW_MODULE.CONF_MQTT_USE_TLS: False,
            FLOW_MODULE.CONF_MQTT_VERIFY_TLS: True,
            FLOW_MODULE.CONF_MQTT_KEEPALIVE: 60,
        }

    def valid_config(self):
        return {**self.api_input(), **self.advanced_input()}

    def existing_entry(self):
        return FakeEntry(
            self.valid_config(),
            {FLOW_MODULE.CONF_SCAN_INTERVAL: 45},
        )

    def submit_api(self, overrides=None):
        user_input = self.api_input()
        user_input.update(overrides or {})
        flow = FLOW_MODULE.GritHubConfigFlow()
        return flow, _run_immediate(flow.async_step_user(user_input))

    def manual_flow(self):
        self.probe_result = types.SimpleNamespace(
            connected=False,
            hub_id=None,
            ambiguous=False,
        )
        flow, result = self.submit_api()
        self.assertEqual(result["step_id"], "advanced")
        self.probe_result = types.SimpleNamespace(
            connected=True,
            hub_id=FABRICATED_HUB_ID,
            ambiguous=False,
        )
        return flow, result

    def broker_fallback(self, ethernet_address=""):
        FakeApi.hub_values = {
            "id": FABRICATED_HUB_ID,
            "ipAddressEthernet": ethernet_address,
        }
        flow, result = self.submit_api()
        self.assertEqual(result["step_id"], "mqtt_broker")
        return flow, result

    def complete_discovered(self):
        flow, result = self.submit_api()
        self.assertEqual(result["step_id"], "confirm")
        result = _run_immediate(
            flow.async_step_confirm(
                {FLOW_MODULE._CONF_SHOW_ADVANCED: False}
            )
        )
        return flow, result

    def reconfigure_input(self, entry):
        data = deepcopy(entry.data)
        data.pop(FLOW_MODULE.CONF_TOKEN, None)
        data.pop(FLOW_MODULE.CONF_MQTT_PASSWORD, None)
        data[FLOW_MODULE.CONF_SCAN_INTERVAL] = entry.options.get(
            FLOW_MODULE.CONF_SCAN_INTERVAL,
            data[FLOW_MODULE.CONF_SCAN_INTERVAL],
        )
        return data

    def reconfigure(self, entry, user_input):
        flow = FLOW_MODULE.GritHubConfigFlow()
        flow._reconfigure_entry = entry
        result = _run_immediate(flow.async_step_reconfigure(user_input))
        return flow, result

    def assert_advanced_error(self, field, value, code):
        flow, _result = self.manual_flow()
        user_input = self.advanced_input()
        user_input[field] = value
        result = _run_immediate(flow.async_step_advanced(user_input))
        self.assertEqual(result["errors"], {field: code})
        self.assertEqual(flow.created_entries, [])

    def test_broker_fallback_localization_is_exact_and_host_only(self):
        translations = json.loads(
            (
                COMPONENT_ROOT
                / "translations"
                / "en.json"
            ).read_text(encoding="utf-8")
        )
        step = translations["config"]["step"]["mqtt_broker"]

        self.assertEqual(
            step["description"],
            "The GRIT Hub identity was discovered, but its local network "
            "address was not returned by the GRIT API. Enter the GRIT Hub\u2019s "
            "LAN hostname or IP address.",
        )
        self.assertEqual(set(step["data"]), {FLOW_MODULE.CONF_MQTT_HOST})

    def test_initial_page_contains_only_api_fields(self):
        result = _run_immediate(
            FLOW_MODULE.GritHubConfigFlow().async_step_user()
        )
        fields = _schema_fields(result["data_schema"])
        self.assertEqual(
            set(fields),
            {
                FLOW_MODULE.CONF_BASE_URL,
                FLOW_MODULE.CONF_TOKEN,
                FLOW_MODULE.CONF_VERIFY_SSL,
            },
        )
        self.assertTrue(
            all(
                isinstance(marker, Required)
                for marker, _validator in fields.values()
            )
        )

    def test_api_token_and_advanced_password_use_password_selectors(self):
        result = _run_immediate(
            FLOW_MODULE.GritHubConfigFlow().async_step_user()
        )
        api_fields = _schema_fields(result["data_schema"])
        self.assertIsInstance(
            api_fields[FLOW_MODULE.CONF_TOKEN][1], TextSelector
        )

        _flow, result = self.manual_flow()
        advanced_fields = _schema_fields(result["data_schema"])
        validator = advanced_fields[FLOW_MODULE.CONF_MQTT_PASSWORD][1]
        self.assertIsInstance(validator, TextSelector)
        self.assertEqual(
            validator.config.type,
            TextSelectorType.PASSWORD,
        )

    def test_successful_rest_discovery_is_confirmed_then_stored(self):
        flow, result = self.submit_api()
        self.assertEqual(result["step_id"], "confirm")
        self.assertEqual(
            result["description_placeholders"],
            {
                "mqtt_host": FABRICATED_MQTT_HOST,
                "mqtt_hub_id": FABRICATED_HUB_ID,
            },
        )
        result = _run_immediate(
            flow.async_step_confirm(
                {FLOW_MODULE._CONF_SHOW_ADVANCED: False}
            )
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(
            result["data"][FLOW_MODULE.CONF_MQTT_HOST],
            FABRICATED_MQTT_HOST,
        )
        self.assertEqual(
            result["data"][FLOW_MODULE.CONF_MQTT_HUB_ID],
            FABRICATED_HUB_ID,
        )
        self.assertIsNone(result["data"][FLOW_MODULE.CONF_MQTT_USERNAME])
        self.assertIsNone(result["data"][FLOW_MODULE.CONF_MQTT_PASSWORD])
        self.assertNotIn(FLOW_MODULE.DEFAULT_MQTT_USERNAME, repr(result))

    def test_long_legacy_token_reaches_authenticated_hub_validation(self):
        flow, result = self.submit_api(
            {FLOW_MODULE.CONF_TOKEN: FABRICATED_LEGACY_TOKEN}
        )

        self.assertEqual(result["step_id"], "confirm")
        self.assertEqual(
            FakeApi.constructor_tokens,
            [FABRICATED_LEGACY_TOKEN],
        )
        self.assertEqual(FakeApi.hub_calls, 1)
        self.assertNotIn(FABRICATED_LEGACY_TOKEN, repr(result))
        self.assertIsNotNone(flow._pending_api)

    def test_unsafe_tokens_are_rejected_before_api_construction(self):
        invalid_tokens = (
            "",
            "fabricated\ncontrol",
            "fabricated-\u20ac-header",
            "A" * 65_537,
        )
        for index, token in enumerate(invalid_tokens):
            with self.subTest(case=index):
                flow, result = self.submit_api(
                    {FLOW_MODULE.CONF_TOKEN: token}
                )
                self.assertEqual(result["step_id"], "user")
                self.assertEqual(
                    result["errors"],
                    {FLOW_MODULE.CONF_TOKEN: "invalid_token"},
                )
                self.assertEqual(FakeApi.constructor_tokens, [])
                self.assertEqual(FakeApi.hub_calls, 0)
                self.assertEqual(self.probe_calls, [])
                self.assertIsNone(flow._pending_api)

    def test_authenticated_hub_failure_stays_on_initial_form(self):
        FakeApi.hub_error = True

        flow, result = self.submit_api()

        self.assertEqual(result["step_id"], "user")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        self.assertEqual(FakeApi.health_calls, 0)
        self.assertEqual(FakeApi.hub_calls, 1)
        self.assertEqual(self.probe_calls, [])
        self.assertEqual(flow.hass.executor_calls, [])
        self.assertIsNone(flow._pending_api)
        self.assertEqual(flow._advanced_defaults, {})
        self.assertNotIn(FABRICATED_TOKEN, repr(result))

    def test_http_401_is_invalid_auth_and_never_probes_mqtt(self):
        FakeApi.hub_error = True
        FakeApi.hub_status = 401

        flow, result = self.submit_api()

        self.assertEqual(result["step_id"], "user")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertEqual(FakeApi.hub_calls, 1)
        self.assertEqual(FakeApi.health_calls, 0)
        self.assertEqual(self.probe_calls, [])
        self.assertEqual(flow.hass.executor_calls, [])
        self.assertNotIn(FABRICATED_TOKEN, repr(result))

    def test_empty_authenticated_hub_response_fails_before_mqtt(self):
        FakeApi.hub_values = {}

        flow, result = self.submit_api()

        self.assertEqual(result["step_id"], "user")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        self.assertEqual(FakeApi.hub_calls, 1)
        self.assertEqual(self.probe_calls, [])
        self.assertIsNone(flow._pending_api)

    def test_failed_retry_clears_prior_authenticated_discovery_state(self):
        flow, first = self.submit_api()
        self.assertEqual(first["step_id"], "confirm")
        self.assertIsNotNone(flow._pending_api)
        initial_probe_count = len(self.probe_calls)

        FakeApi.hub_error = True
        FakeApi.hub_status = 401
        failed = _run_immediate(flow.async_step_user(self.api_input()))

        self.assertEqual(failed["step_id"], "user")
        self.assertEqual(failed["errors"], {"base": "invalid_auth"})
        self.assertIsNone(flow._pending_api)
        self.assertEqual(flow._advanced_defaults, {})
        self.assertEqual(len(self.probe_calls), initial_probe_count)
        confirm = _run_immediate(flow.async_step_confirm())
        self.assertEqual(confirm["step_id"], "user")
        self.assertEqual(flow.created_entries, [])

    def test_missing_or_malformed_hub_id_uses_advanced_without_probe(self):
        cases = (
            {"ipAddressEthernet": FABRICATED_MQTT_HOST},
            {
                "id": "malformed",
                "ipAddressEthernet": FABRICATED_MQTT_HOST,
            },
        )
        for values in cases:
            with self.subTest(values=values):
                FakeApi.hub_values = values
                self.probe_calls.clear()
                _flow, result = self.submit_api()
                self.assertEqual(result["step_id"], "advanced")
                self.assertEqual(self.probe_calls, [])

    def test_blank_or_invalid_ethernet_asks_only_for_broker(self):
        for ethernet_address in ("", "not-an-ip"):
            with self.subTest(ethernet_address=ethernet_address):
                self.probe_calls.clear()
                flow, result = self.broker_fallback(ethernet_address)
                fields = _schema_fields(result["data_schema"])

                self.assertEqual(set(fields), {FLOW_MODULE.CONF_MQTT_HOST})
                self.assertEqual(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_HUB_ID],
                    FABRICATED_HUB_ID,
                )
                self.assertEqual(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_PORT],
                    FLOW_MODULE.DEFAULT_MQTT_PORT,
                )
                self.assertEqual(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_KEEPALIVE],
                    FLOW_MODULE.DEFAULT_MQTT_KEEPALIVE,
                )
                self.assertFalse(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_USE_TLS]
                )
                self.assertTrue(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_VERIFY_TLS]
                )
                self.assertIsNone(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_USERNAME]
                )
                self.assertIsNone(
                    flow._advanced_defaults[FLOW_MODULE.CONF_MQTT_PASSWORD]
                )
                self.assertEqual(self.probe_calls, [])
                rendered = repr(result)
                for private_value in (
                    FABRICATED_TOKEN,
                    FABRICATED_HUB_ID,
                    FLOW_MODULE.DEFAULT_MQTT_USERNAME,
                    FLOW_MODULE.DEFAULT_MQTT_PASSWORD,
                ):
                    self.assertNotIn(private_value, rendered)

    def test_broker_entry_validates_defaults_and_completes_setup(self):
        flow, _result = self.broker_fallback()

        with self.assertNoLogs(level=logging.DEBUG):
            result = _run_immediate(
                flow.async_step_mqtt_broker(
                    {FLOW_MODULE.CONF_MQTT_HOST: FABRICATED_MQTT_HOST}
                )
            )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(len(self.probe_calls), 1)
        probe = self.probe_calls[0]
        self.assertEqual(probe["host"], FABRICATED_MQTT_HOST)
        self.assertEqual(probe["port"], FLOW_MODULE.DEFAULT_MQTT_PORT)
        self.assertEqual(probe["expected_hub_id"], FABRICATED_HUB_ID)
        self.assertEqual(
            probe["username"], FLOW_MODULE.DEFAULT_MQTT_USERNAME
        )
        self.assertEqual(
            probe["password"], FLOW_MODULE.DEFAULT_MQTT_PASSWORD
        )
        self.assertEqual(
            probe["timeout"], FLOW_MODULE.MQTT_DISCOVERY_TIMEOUT
        )
        self.assertFalse(probe["use_tls"])
        self.assertTrue(probe["verify_tls"])
        self.assertEqual(
            probe["keepalive"], FLOW_MODULE.DEFAULT_MQTT_KEEPALIVE
        )
        self.assertEqual(
            result["data"][FLOW_MODULE.CONF_MQTT_HUB_ID],
            FABRICATED_HUB_ID,
        )
        self.assertEqual(
            result["data"][FLOW_MODULE.CONF_MQTT_HOST],
            FABRICATED_MQTT_HOST,
        )
        self.assertIsNone(
            result["data"][FLOW_MODULE.CONF_MQTT_USERNAME]
        )
        self.assertIsNone(
            result["data"][FLOW_MODULE.CONF_MQTT_PASSWORD]
        )

    def test_malformed_broker_fails_before_probe(self):
        flow, _result = self.broker_fallback()
        for broker in (
            "",
            "invalid broker",
            "invalid/broker",
            "h" * (FLOW_MODULE.MAX_MQTT_HOST_LENGTH + 1),
        ):
            with self.subTest(broker=broker):
                result = _run_immediate(
                    flow.async_step_mqtt_broker(
                        {FLOW_MODULE.CONF_MQTT_HOST: broker}
                    )
                )
                self.assertEqual(result["step_id"], "mqtt_broker")
                self.assertEqual(
                    result["errors"],
                    {FLOW_MODULE.CONF_MQTT_HOST: "invalid_mqtt_host"},
                )
                self.assertEqual(self.probe_calls, [])
                self.assertEqual(flow.created_entries, [])

    def test_failed_broker_validation_is_generic_and_opens_advanced(self):
        flow, _result = self.broker_fallback()
        self.probe_result = types.SimpleNamespace(
            connected=False,
            hub_id=None,
            ambiguous=False,
        )

        with self.assertNoLogs(level=logging.DEBUG):
            result = _run_immediate(
                flow.async_step_mqtt_broker(
                    {FLOW_MODULE.CONF_MQTT_HOST: FABRICATED_MQTT_HOST}
                )
            )

        self.assertEqual(result["step_id"], "advanced")
        self.assertEqual(result["errors"], {"base": "mqtt_cannot_connect"})
        self.assertEqual(flow.created_entries, [])
        for private_value in (
            FABRICATED_TOKEN,
            FABRICATED_PASSWORD,
            FABRICATED_HUB_ID,
            FABRICATED_MQTT_HOST,
            FLOW_MODULE.DEFAULT_MQTT_USERNAME,
            FLOW_MODULE.DEFAULT_MQTT_PASSWORD,
        ):
            self.assertNotIn(private_value, repr(result["errors"]))

    def test_advanced_fallback_contains_no_api_or_mqtt_secret(self):
        FakeApi.hub_values = {"name": "Fabricated Hub"}

        _flow, result = self.submit_api()

        self.assertEqual(result["step_id"], "advanced")
        rendered = repr(result)
        for secret in (
            FABRICATED_TOKEN,
            FLOW_MODULE.DEFAULT_MQTT_USERNAME,
            FLOW_MODULE.DEFAULT_MQTT_PASSWORD,
        ):
            self.assertNotIn(secret, rendered)

    def test_mqtt_timeout_is_bounded_and_shows_manual_fallback(self):
        _flow, result = self.manual_flow()
        self.assertEqual(result["step_id"], "advanced")
        self.assertEqual(len(self.probe_calls), 1)
        self.assertEqual(
            self.probe_calls[0]["timeout"],
            FLOW_MODULE.MQTT_DISCOVERY_TIMEOUT,
        )

    def test_manual_fallback_creates_complete_entry(self):
        flow, _result = self.manual_flow()
        result = _run_immediate(
            flow.async_step_advanced(self.advanced_input())
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], self.valid_config())

    def test_advanced_overrides_replace_discovered_values(self):
        flow, result = self.submit_api()
        self.assertEqual(result["step_id"], "confirm")
        result = _run_immediate(
            flow.async_step_confirm(
                {FLOW_MODULE._CONF_SHOW_ADVANCED: True}
            )
        )
        self.assertEqual(result["step_id"], "advanced")
        fields = _schema_fields(result["data_schema"])
        self.assertEqual(
            fields[FLOW_MODULE.CONF_MQTT_HOST][0].default,
            FABRICATED_MQTT_HOST,
        )
        values = self.advanced_input()
        values[FLOW_MODULE.CONF_MQTT_HOST] = "override.config-test.invalid"
        values[FLOW_MODULE.CONF_MQTT_HUB_ID] = FABRICATED_OTHER_HUB_ID
        values[FLOW_MODULE.CONF_MQTT_PORT] = 8883
        created = _run_immediate(flow.async_step_advanced(values))
        self.assertEqual(
            created["data"][FLOW_MODULE.CONF_MQTT_HOST],
            "override.config-test.invalid",
        )
        self.assertEqual(
            created["data"][FLOW_MODULE.CONF_MQTT_HUB_ID],
            FABRICATED_OTHER_HUB_ID,
        )
        self.assertEqual(
            created["data"][FLOW_MODULE.CONF_MQTT_PORT],
            8883,
        )

    def test_public_health_endpoint_is_not_used_for_credential_validation(self):
        FakeApi.health_error = True

        _flow, result = self.submit_api()

        self.assertEqual(result["step_id"], "confirm")
        self.assertEqual(FakeApi.health_calls, 0)
        self.assertEqual(FakeApi.hub_calls, 1)

    def test_discovery_performs_one_read_sequence_and_one_probe(self):
        flow, result = self.submit_api()
        self.assertEqual(result["step_id"], "confirm")
        self.assertEqual(FakeApi.read_events, ["hub"])
        self.assertEqual(FakeApi.health_calls, 0)
        self.assertEqual(len(self.probe_calls), 1)
        self.assertEqual(len(flow.hass.executor_calls), 1)
        self.assertEqual(
            self.probe_calls[0]["username"],
            FLOW_MODULE.DEFAULT_MQTT_USERNAME,
        )
        self.assertEqual(
            self.probe_calls[0]["password"],
            FLOW_MODULE.DEFAULT_MQTT_PASSWORD,
        )

    def test_cancelled_discovery_signals_executor_probe_cleanup(self):
        self.probe_error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.submit_api()
        self.assertEqual(len(self.probe_calls), 1)
        self.assertTrue(self.probe_calls[0]["cancel_event"].is_set())

    def test_api_token_is_stored_and_passed_without_logging(self):
        with self.assertNoLogs(level=logging.DEBUG):
            _flow, result = self.complete_discovered()
        self.assertEqual(
            result["data"][FLOW_MODULE.CONF_TOKEN], FABRICATED_TOKEN
        )
        self.assertEqual(FakeApi.constructor_tokens, [FABRICATED_TOKEN])

    def test_invalid_api_url_is_rejected_before_authentication(self):
        for value in (" ", "broker.invalid", "ftp://api.invalid"):
            with self.subTest(value=value):
                flow, result = self.submit_api(
                    {FLOW_MODULE.CONF_BASE_URL: value}
                )
                self.assertEqual(
                    result["errors"],
                    {FLOW_MODULE.CONF_BASE_URL: "invalid_base_url"},
                )
                self.assertEqual(flow.created_entries, [])
        self.assertEqual(FakeApi.health_calls, 0)

    def test_blank_host_is_rejected(self):
        self.assert_advanced_error(
            FLOW_MODULE.CONF_MQTT_HOST,
            " ",
            "invalid_mqtt_host",
        )

    def test_invalid_ports_are_rejected(self):
        for value in (0, 65536, True, "1883"):
            with self.subTest(value=value):
                self.assert_advanced_error(
                    FLOW_MODULE.CONF_MQTT_PORT,
                    value,
                    "invalid_mqtt_port",
                )

    def test_invalid_keepalive_values_are_rejected(self):
        for value in (0, 65536, True, "60"):
            with self.subTest(value=value):
                self.assert_advanced_error(
                    FLOW_MODULE.CONF_MQTT_KEEPALIVE,
                    value,
                    "invalid_mqtt_keepalive",
                )

    def test_blank_hub_id_is_rejected(self):
        self.assert_advanced_error(
            FLOW_MODULE.CONF_MQTT_HUB_ID,
            " ",
            "invalid_mqtt_hub_id",
        )

    def test_oversized_connection_identifiers_are_rejected(self):
        cases = (
            (
                FLOW_MODULE.CONF_MQTT_HOST,
                "h" * (FLOW_MODULE.MAX_MQTT_HOST_LENGTH + 1),
                "invalid_mqtt_host",
            ),
            (
                FLOW_MODULE.CONF_MQTT_USERNAME,
                "u" * (FLOW_MODULE.MAX_MQTT_USERNAME_LENGTH + 1),
                "invalid_mqtt_username",
            ),
            (
                FLOW_MODULE.CONF_MQTT_HUB_ID,
                "i" * (FLOW_MODULE.MAX_MQTT_HUB_ID_LENGTH + 1),
                "invalid_mqtt_hub_id",
            ),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                self.assert_advanced_error(field, value, code)

    def test_password_without_username_is_rejected(self):
        flow, _result = self.manual_flow()
        values = self.advanced_input()
        values[FLOW_MODULE.CONF_MQTT_USERNAME] = " "
        result = _run_immediate(flow.async_step_advanced(values))
        self.assertEqual(
            result["errors"],
            {
                FLOW_MODULE.CONF_MQTT_PASSWORD:
                    "mqtt_password_requires_username"
            },
        )

    def test_blank_username_and_password_normalize_to_none(self):
        flow, _result = self.manual_flow()
        values = self.advanced_input()
        values[FLOW_MODULE.CONF_MQTT_USERNAME] = " "
        values[FLOW_MODULE.CONF_MQTT_PASSWORD] = " "
        result = _run_immediate(flow.async_step_advanced(values))
        self.assertIsNone(result["data"][FLOW_MODULE.CONF_MQTT_USERNAME])
        self.assertIsNone(result["data"][FLOW_MODULE.CONF_MQTT_PASSWORD])

    def test_tls_verification_is_safely_normalized(self):
        flow, _result = self.manual_flow()
        values = self.advanced_input()
        values[FLOW_MODULE.CONF_MQTT_USE_TLS] = False
        values[FLOW_MODULE.CONF_MQTT_VERIFY_TLS] = False
        result = _run_immediate(flow.async_step_advanced(values))
        self.assertFalse(result["data"][FLOW_MODULE.CONF_MQTT_USE_TLS])
        self.assertTrue(result["data"][FLOW_MODULE.CONF_MQTT_VERIFY_TLS])

        flow, _result = self.manual_flow()
        values[FLOW_MODULE.CONF_MQTT_USE_TLS] = True
        result = _run_immediate(flow.async_step_advanced(values))
        self.assertTrue(result["data"][FLOW_MODULE.CONF_MQTT_USE_TLS])
        self.assertFalse(result["data"][FLOW_MODULE.CONF_MQTT_VERIFY_TLS])

    def test_unknown_advanced_fields_are_not_stored(self):
        flow, _result = self.manual_flow()
        values = self.advanced_input()
        values["unexpected_field"] = "fabricated-unexpected-value"
        result = _run_immediate(flow.async_step_advanced(values))
        self.assertNotIn("unexpected_field", result["data"])

    def test_reconfigure_prefills_only_non_secret_fields(self):
        entry = self.existing_entry()
        flow = FLOW_MODULE.GritHubConfigFlow()
        flow._reconfigure_entry = entry
        result = _run_immediate(flow.async_step_reconfigure())
        fields = _schema_fields(result["data_schema"])
        self.assertEqual(
            fields[FLOW_MODULE.CONF_BASE_URL][0].default,
            FABRICATED_BASE_URL,
        )
        self.assertEqual(
            fields[FLOW_MODULE.CONF_MQTT_HOST][0].default,
            FABRICATED_MQTT_HOST,
        )
        self.assertEqual(
            fields[FLOW_MODULE.CONF_SCAN_INTERVAL][0].default,
            45,
        )
        self.assertIs(fields[FLOW_MODULE.CONF_TOKEN][0].default, UNDEFINED)
        self.assertIs(
            fields[FLOW_MODULE.CONF_MQTT_PASSWORD][0].default,
            UNDEFINED,
        )

        self.assertIs(
            fields[FLOW_MODULE.CONF_MQTT_USERNAME][0].default,
            UNDEFINED,
        )
    def test_blank_reconfigure_secrets_preserve_stored_values(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_TOKEN] = " "
        user_input[FLOW_MODULE.CONF_MQTT_PASSWORD] = ""
        _flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.data[FLOW_MODULE.CONF_TOKEN], FABRICATED_TOKEN)
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_MQTT_PASSWORD],
            FABRICATED_PASSWORD,
        )


    def test_reconfigure_rejects_empty_authenticated_hub_response(self):
        entry = self.existing_entry()
        original_data = deepcopy(entry.data)
        FakeApi.hub_values = {}

        flow, result = self.reconfigure(
            entry,
            self.reconfigure_input(entry),
        )

        self.assertEqual(result["step_id"], "reconfigure")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        self.assertEqual(entry.data, original_data)
        self.assertEqual(flow.updated_entries, [])
        self.assertEqual(self.probe_calls, [])

    def test_reconfigure_blank_rest_address_preserves_existing_overrides(self):
        entry = self.existing_entry()
        override_host = "override.config-test.invalid"
        entry.data[FLOW_MODULE.CONF_MQTT_HOST] = override_host
        entry.data[FLOW_MODULE.CONF_MQTT_HUB_ID] = FABRICATED_OTHER_HUB_ID
        FakeApi.hub_values = {
            "id": FABRICATED_HUB_ID,
            "ipAddressEthernet": "",
        }

        flow, result = self.reconfigure(
            entry,
            self.reconfigure_input(entry),
        )

        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(FakeApi.hub_calls, 1)
        self.assertEqual(len(self.probe_calls), 1)
        self.assertEqual(self.probe_calls[0]["host"], override_host)
        self.assertEqual(
            self.probe_calls[0]["expected_hub_id"],
            FABRICATED_OTHER_HUB_ID,
        )
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_MQTT_HOST],
            override_host,
        )
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_MQTT_HUB_ID],
            FABRICATED_OTHER_HUB_ID,
        )

    def test_reconfigure_401_preserves_entry_and_exposes_no_secret(self):
        entry = self.existing_entry()
        original_data = deepcopy(entry.data)
        original_options = deepcopy(entry.options)
        user_input = self.reconfigure_input(entry)
        rejected_token = "fabricated-rejected-token"
        user_input[FLOW_MODULE.CONF_TOKEN] = rejected_token
        FakeApi.hub_error = True
        FakeApi.hub_status = 401

        flow, result = self.reconfigure(entry, user_input)

        self.assertEqual(result["step_id"], "reconfigure")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertEqual(entry.data, original_data)
        self.assertEqual(entry.options, original_options)
        self.assertEqual(flow.updated_entries, [])
        self.assertEqual(flow.hass.config_entries.update_calls, [])
        self.assertEqual(flow.hass.config_entries.reload_calls, [])
        self.assertEqual(FakeApi.hub_calls, 1)
        self.assertEqual(self.probe_calls, [])
        self.assertNotIn(rejected_token, repr(result))

    def test_supplied_reconfigure_secrets_replace_stored_values(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        new_token = "fabricated-replacement-token"
        new_password = "fabricated-replacement-password"
        user_input[FLOW_MODULE.CONF_TOKEN] = new_token
        user_input[FLOW_MODULE.CONF_MQTT_PASSWORD] = new_password
        _flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.data[FLOW_MODULE.CONF_TOKEN], new_token)
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_MQTT_PASSWORD], new_password
        )

    def test_changing_username_without_password_clears_old_password(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_MQTT_USERNAME] = (
            "fabricated-replacement-user"
        )
        _flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_MQTT_USERNAME],
            "fabricated-replacement-user",
        )
        self.assertIsNone(entry.data[FLOW_MODULE.CONF_MQTT_PASSWORD])

    def test_clearing_username_also_clears_password(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_MQTT_USERNAME] = " "
        user_input[FLOW_MODULE.CONF_MQTT_PASSWORD] = " "
        _flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertIsNone(entry.data[FLOW_MODULE.CONF_MQTT_USERNAME])
        self.assertIsNone(entry.data[FLOW_MODULE.CONF_MQTT_PASSWORD])

    def test_reconfigure_updates_existing_entry_without_duplicate(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_MQTT_PORT] = 8883
        flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.data[FLOW_MODULE.CONF_MQTT_PORT], 8883)
        self.assertEqual(len(flow.updated_entries), 1)
        self.assertEqual(flow.created_entries, [])

    def test_reconfigure_uses_supported_helper_and_reloads_exactly_once(self):
        entry = self.existing_entry()
        entry.options["fabricated_unrelated_option"] = "preserved"
        original_entry_id = entry.entry_id
        original_unique_id = entry.unique_id
        original_entity_id = entry.entity_id
        original_device_id = entry.device_id
        mqtt_fields = (
            FLOW_MODULE.CONF_MQTT_HOST,
            FLOW_MODULE.CONF_MQTT_PORT,
            FLOW_MODULE.CONF_MQTT_HUB_ID,
            FLOW_MODULE.CONF_MQTT_USERNAME,
            FLOW_MODULE.CONF_MQTT_PASSWORD,
            FLOW_MODULE.CONF_MQTT_USE_TLS,
            FLOW_MODULE.CONF_MQTT_VERIFY_TLS,
            FLOW_MODULE.CONF_MQTT_KEEPALIVE,
        )
        original_mqtt = {
            field: entry.data[field] for field in mqtt_fields
        }
        replacement_token = "fabricated-supported-helper-token"
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_TOKEN] = replacement_token

        flow, result = self.reconfigure(entry, user_input)

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.data[FLOW_MODULE.CONF_TOKEN], replacement_token)
        self.assertEqual(FakeApi.constructor_tokens, [replacement_token])
        self.assertEqual(
            {field: entry.data[field] for field in mqtt_fields},
            original_mqtt,
        )
        self.assertEqual(entry.entry_id, original_entry_id)
        self.assertEqual(entry.unique_id, original_unique_id)
        self.assertEqual(entry.entity_id, original_entity_id)
        self.assertEqual(entry.device_id, original_device_id)
        self.assertEqual(entry.options[FLOW_MODULE.CONF_SCAN_INTERVAL], 45)
        self.assertEqual(
            entry.options["fabricated_unrelated_option"],
            "preserved",
        )
        self.assertEqual(flow.created_entries, [])
        self.assertEqual(flow.updated_entries, [entry])
        self.assertEqual(
            flow.hass.config_entries.reload_calls,
            [entry.entry_id],
        )
        self.assertEqual(len(flow.hass.config_entries.update_calls), 2)
        options_call, data_call = flow.hass.config_entries.update_calls
        self.assertIs(options_call["entry"], entry)
        self.assertIsNone(options_call["data"])
        self.assertEqual(options_call["options"], entry.options)
        self.assertIs(data_call["entry"], entry)
        self.assertIsNone(data_call["options"])
        self.assertEqual(
            data_call["data"][FLOW_MODULE.CONF_TOKEN],
            replacement_token,
        )

    def test_reconfigure_changed_scan_interval_updates_option_once(self):
        entry = self.existing_entry()
        entry.options["fabricated_unrelated_option"] = "preserved"
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_SCAN_INTERVAL] = 90

        flow, result = self.reconfigure(entry, user_input)

        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.options[FLOW_MODULE.CONF_SCAN_INTERVAL], 90)
        self.assertEqual(entry.data[FLOW_MODULE.CONF_SCAN_INTERVAL], 90)
        self.assertEqual(
            entry.options["fabricated_unrelated_option"],
            "preserved",
        )
        self.assertEqual(
            flow.hass.config_entries.reload_calls,
            [entry.entry_id],
        )

    def test_reconfigure_mqtt_failure_changes_nothing_and_does_not_reload(self):
        entry = self.existing_entry()
        entry.options["fabricated_unrelated_option"] = "preserved"
        original_data = deepcopy(entry.data)
        original_options = deepcopy(entry.options)
        self.probe_result = types.SimpleNamespace(
            connected=False,
            hub_id=None,
            ambiguous=False,
        )

        flow, result = self.reconfigure(
            entry,
            self.reconfigure_input(entry),
        )

        self.assertEqual(result["step_id"], "reconfigure")
        self.assertEqual(result["errors"], {"base": "mqtt_cannot_connect"})
        self.assertEqual(entry.data, original_data)
        self.assertEqual(entry.options, original_options)
        self.assertEqual(flow.updated_entries, [])
        self.assertEqual(flow.hass.config_entries.update_calls, [])
        self.assertEqual(flow.hass.config_entries.reload_calls, [])
        self.assertEqual(len(self.probe_calls), 1)

    def test_reconfigure_unexpected_api_error_is_bounded_without_mutation(self):
        entry = self.existing_entry()
        original_data = deepcopy(entry.data)
        original_options = deepcopy(entry.options)

        with mock.patch.object(
            FakeApi,
            "get_hub",
            mock.AsyncMock(side_effect=RuntimeError("fabricated failure")),
        ):
            flow, result = self.reconfigure(
                entry,
                self.reconfigure_input(entry),
            )

        self.assertEqual(result["step_id"], "reconfigure")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        self.assertEqual(entry.data, original_data)
        self.assertEqual(entry.options, original_options)
        self.assertEqual(flow.updated_entries, [])
        self.assertEqual(flow.hass.config_entries.update_calls, [])
        self.assertEqual(flow.hass.config_entries.reload_calls, [])
        self.assertEqual(self.probe_calls, [])

    def test_scan_interval_options_flow_remains_available(self):
        entry = self.existing_entry()
        flow = FLOW_MODULE.GritHubOptionsFlow(entry)
        flow.created_entries = []

        result = _run_immediate(flow.async_step_init())
        fields = _schema_fields(result["data_schema"])
        self.assertEqual(
            fields[FLOW_MODULE.CONF_SCAN_INTERVAL][0].default,
            45,
        )

        result = _run_immediate(
            flow.async_step_init({FLOW_MODULE.CONF_SCAN_INTERVAL: 75})
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(
            result["data"],
            {FLOW_MODULE.CONF_SCAN_INTERVAL: 75},
        )

    def test_reconfigure_result_and_logs_exclude_supplied_secrets(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        new_token = "fabricated-private-token"
        new_password = "fabricated-private-password"
        user_input[FLOW_MODULE.CONF_TOKEN] = new_token
        user_input[FLOW_MODULE.CONF_MQTT_PASSWORD] = new_password
        with self.assertNoLogs(level=logging.DEBUG):
            _flow, result = self.reconfigure(entry, user_input)
        result_text = repr(result)
        self.assertNotIn(new_token, result_text)
        self.assertNotIn(new_password, result_text)

    def test_rest_only_entry_can_open_reconfigure_form(self):
        data = self.api_input()
        entry = FakeEntry(data)
        flow = FLOW_MODULE.GritHubConfigFlow()
        flow._reconfigure_entry = entry
        result = _run_immediate(flow.async_step_reconfigure())
        fields = _schema_fields(result["data_schema"])
        self.assertEqual(fields[FLOW_MODULE.CONF_MQTT_HOST][0].default, "")
        self.assertEqual(fields[FLOW_MODULE.CONF_MQTT_HUB_ID][0].default, "")
        self.assertEqual(
            fields[FLOW_MODULE.CONF_MQTT_PORT][0].default,
            FLOW_MODULE.DEFAULT_MQTT_PORT,
        )


if __name__ == "__main__":
    unittest.main()

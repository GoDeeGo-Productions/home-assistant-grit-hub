"""Network-free tests for GRIT installation and MQTT configuration flows."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
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
FABRICATED_MQTT_HOST = "192.0.2.44"
FABRICATED_HUB_ID = "0123456789abcdef0123456789abcdef"
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


class FakeHass:
    def __init__(self):
        self.executor_calls = []

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
        options_updates,
    ):
        entry.data.update(deepcopy(data_updates))
        entry.options.update(deepcopy(options_updates))
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

    def test_missing_documented_fields_do_not_probe_api_hostname(self):
        cases = (
            {"ipAddressEthernet": FABRICATED_MQTT_HOST},
            {"id": FABRICATED_HUB_ID},
            {
                "id": "malformed",
                "ipAddressEthernet": FABRICATED_MQTT_HOST,
            },
            {
                "id": FABRICATED_HUB_ID,
                "ipAddressEthernet": "not-an-ip",
            },
        )
        for values in cases:
            with self.subTest(values=values):
                FakeApi.hub_values = values
                self.probe_calls.clear()
                _flow, result = self.submit_api()
                self.assertEqual(result["step_id"], "advanced")
                self.assertEqual(self.probe_calls, [])

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
        values[FLOW_MODULE.CONF_MQTT_HUB_ID] = "hub-override"
        values[FLOW_MODULE.CONF_MQTT_PORT] = 8883
        created = _run_immediate(flow.async_step_advanced(values))
        self.assertEqual(
            created["data"][FLOW_MODULE.CONF_MQTT_HOST],
            "override.config-test.invalid",
        )
        self.assertEqual(
            created["data"][FLOW_MODULE.CONF_MQTT_HUB_ID],
            "hub-override",
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

    def test_reconfigure_401_preserves_entry_and_exposes_no_secret(self):
        entry = self.existing_entry()
        original_data = deepcopy(entry.data)
        user_input = self.reconfigure_input(entry)
        rejected_token = "fabricated-rejected-token"
        user_input[FLOW_MODULE.CONF_TOKEN] = rejected_token
        FakeApi.hub_error = True
        FakeApi.hub_status = 401

        flow, result = self.reconfigure(entry, user_input)

        self.assertEqual(result["step_id"], "reconfigure")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertEqual(entry.data, original_data)
        self.assertEqual(flow.updated_entries, [])
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

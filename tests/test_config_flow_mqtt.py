"""Network-free tests for GRIT MQTT configuration flows."""
from __future__ import annotations

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

FABRICATED_BASE_URL = "https://api.config-test.invalid"
FABRICATED_TOKEN = "fabricated-api-token"
FABRICATED_MQTT_HOST = "broker.config-test.invalid"
FABRICATED_HUB_ID = "hub-config-test"
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


class _FlowBase:
    def __init__(self):
        self.hass = types.SimpleNamespace()
        self.created_entries = []
        self.updated_entries = []
        self._reconfigure_entry = None
        self.unique_id = None

    def async_show_form(self, *, step_id, data_schema, errors=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
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
    pass


class FakeApi:
    health_calls = 0
    constructor_tokens = []

    def __init__(self, _hass, _base_url, token, _verify_ssl):
        type(self).constructor_tokens.append(token)

    async def health_check(self):
        type(self).health_calls += 1
        return {"status": "ok"}


def _install_stubs(package_name):
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

    api = types.ModuleType(f"{package_name}.api")
    api.GritHubApiClient = FakeApi
    api.GritHubApiError = FakeApiError
    sys.modules[api.__name__] = api


def _load_config_flow():
    package_name = "_grit_config_flow_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules[package_name] = package
    _install_stubs(package_name)

    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", COMPONENT_ROOT / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)

    flow_spec = importlib.util.spec_from_file_location(
        f"{package_name}.config_flow", COMPONENT_ROOT / "config_flow.py"
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
        FakeApi.constructor_tokens = []
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
        socket_patch.start()
        connection_patch.start()
        self.addCleanup(socket_patch.stop)
        self.addCleanup(connection_patch.stop)

    def valid_input(self):
        return {
            FLOW_MODULE.CONF_BASE_URL: FABRICATED_BASE_URL,
            FLOW_MODULE.CONF_TOKEN: FABRICATED_TOKEN,
            FLOW_MODULE.CONF_VERIFY_SSL: True,
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

    def existing_entry(self):
        data = self.valid_input()
        return FakeEntry(
            data,
            {FLOW_MODULE.CONF_SCAN_INTERVAL: 45},
        )

    def submit_user(self, overrides=None):
        user_input = self.valid_input()
        user_input.update(overrides or {})
        flow = FLOW_MODULE.GritHubConfigFlow()
        return flow, _run_immediate(flow.async_step_user(user_input))

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

    def assert_field_error(self, field, value, code):
        flow, result = self.submit_user({field: value})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {field: code})
        self.assertEqual(flow.created_entries, [])
        self.assertEqual(FakeApi.health_calls, 0)

    def test_new_entry_schema_contains_all_configuration_fields(self):
        flow = FLOW_MODULE.GritHubConfigFlow()
        result = _run_immediate(flow.async_step_user())
        fields = _schema_fields(result["data_schema"])
        expected = {
            FLOW_MODULE.CONF_BASE_URL,
            FLOW_MODULE.CONF_TOKEN,
            FLOW_MODULE.CONF_VERIFY_SSL,
            FLOW_MODULE.CONF_SCAN_INTERVAL,
            FLOW_MODULE.CONF_MQTT_HOST,
            FLOW_MODULE.CONF_MQTT_PORT,
            FLOW_MODULE.CONF_MQTT_HUB_ID,
            FLOW_MODULE.CONF_MQTT_USERNAME,
            FLOW_MODULE.CONF_MQTT_PASSWORD,
            FLOW_MODULE.CONF_MQTT_USE_TLS,
            FLOW_MODULE.CONF_MQTT_VERIFY_TLS,
            FLOW_MODULE.CONF_MQTT_KEEPALIVE,
        }
        self.assertEqual(set(fields), expected)
        required = {
            name
            for name, (marker, _validator) in fields.items()
            if isinstance(marker, Required)
        }
        self.assertTrue(
            {
                FLOW_MODULE.CONF_BASE_URL,
                FLOW_MODULE.CONF_TOKEN,
                FLOW_MODULE.CONF_VERIFY_SSL,
                FLOW_MODULE.CONF_SCAN_INTERVAL,
                FLOW_MODULE.CONF_MQTT_HOST,
                FLOW_MODULE.CONF_MQTT_PORT,
                FLOW_MODULE.CONF_MQTT_HUB_ID,
            }.issubset(required)
        )

    def test_api_token_and_mqtt_password_use_password_selectors(self):
        result = _run_immediate(
            FLOW_MODULE.GritHubConfigFlow().async_step_user()
        )
        fields = _schema_fields(result["data_schema"])
        for field in (
            FLOW_MODULE.CONF_TOKEN,
            FLOW_MODULE.CONF_MQTT_PASSWORD,
        ):
            with self.subTest(field=field):
                validator = fields[field][1]
                self.assertIsInstance(validator, TextSelector)
                self.assertEqual(
                    validator.config.type, TextSelectorType.PASSWORD
                )

    def test_blank_host_is_rejected(self):
        self.assert_field_error(
            FLOW_MODULE.CONF_MQTT_HOST,
            " ",
            "invalid_mqtt_host",
        )

    def test_invalid_ports_are_rejected(self):
        for value in (0, 65536, True, "1883"):
            with self.subTest(value=value):
                self.assert_field_error(
                    FLOW_MODULE.CONF_MQTT_PORT,
                    value,
                    "invalid_mqtt_port",
                )

    def test_invalid_keepalive_values_are_rejected(self):
        for value in (0, 65536, True, "60"):
            with self.subTest(value=value):
                self.assert_field_error(
                    FLOW_MODULE.CONF_MQTT_KEEPALIVE,
                    value,
                    "invalid_mqtt_keepalive",
                )

    def test_blank_hub_id_is_rejected(self):
        self.assert_field_error(
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
                self.assert_field_error(field, value, code)

    def test_password_without_username_is_rejected(self):
        flow, result = self.submit_user(
            {FLOW_MODULE.CONF_MQTT_USERNAME: " "}
        )
        self.assertEqual(
            result["errors"],
            {FLOW_MODULE.CONF_MQTT_PASSWORD: "mqtt_password_requires_username"},
        )
        self.assertEqual(flow.created_entries, [])

    def test_blank_username_and_password_normalize_to_none(self):
        flow, result = self.submit_user(
            {
                FLOW_MODULE.CONF_MQTT_USERNAME: " ",
                FLOW_MODULE.CONF_MQTT_PASSWORD: " ",
            }
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(len(flow.created_entries), 1)
        self.assertIsNone(result["data"][FLOW_MODULE.CONF_MQTT_USERNAME])
        self.assertIsNone(result["data"][FLOW_MODULE.CONF_MQTT_PASSWORD])

    def test_tls_verification_is_safely_normalized(self):
        _flow, result = self.submit_user(
            {
                FLOW_MODULE.CONF_MQTT_USE_TLS: False,
                FLOW_MODULE.CONF_MQTT_VERIFY_TLS: False,
            }
        )
        self.assertFalse(result["data"][FLOW_MODULE.CONF_MQTT_USE_TLS])
        self.assertTrue(result["data"][FLOW_MODULE.CONF_MQTT_VERIFY_TLS])

        _flow, result = self.submit_user(
            {
                FLOW_MODULE.CONF_MQTT_USE_TLS: True,
                FLOW_MODULE.CONF_MQTT_VERIFY_TLS: False,
            }
        )
        self.assertTrue(result["data"][FLOW_MODULE.CONF_MQTT_USE_TLS])
        self.assertFalse(result["data"][FLOW_MODULE.CONF_MQTT_VERIFY_TLS])

    def test_api_token_is_stored_and_passed_without_logging(self):
        with self.assertNoLogs(level=logging.DEBUG):
            _flow, result = self.submit_user()
        self.assertEqual(
            result["data"][FLOW_MODULE.CONF_TOKEN], FABRICATED_TOKEN
        )
        self.assertEqual(FakeApi.constructor_tokens, [FABRICATED_TOKEN])

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
        self.assertIs(
            fields[FLOW_MODULE.CONF_TOKEN][0].default,
            UNDEFINED,
        )
        self.assertIs(
            fields[FLOW_MODULE.CONF_MQTT_PASSWORD][0].default,
            UNDEFINED,
        )

    def test_blank_reconfigure_secrets_preserve_stored_values(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_TOKEN] = " "
        user_input[FLOW_MODULE.CONF_MQTT_PASSWORD] = ""
        _flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_TOKEN], FABRICATED_TOKEN
        )
        self.assertEqual(
            entry.data[FLOW_MODULE.CONF_MQTT_PASSWORD],
            FABRICATED_PASSWORD,
        )

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

    def test_clearing_username_also_clears_password(self):
        entry = self.existing_entry()
        user_input = self.reconfigure_input(entry)
        user_input[FLOW_MODULE.CONF_MQTT_USERNAME] = " "
        user_input[FLOW_MODULE.CONF_MQTT_PASSWORD] = " "
        _flow, result = self.reconfigure(entry, user_input)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertIsNone(
            entry.data[FLOW_MODULE.CONF_MQTT_USERNAME]
        )
        self.assertIsNone(
            entry.data[FLOW_MODULE.CONF_MQTT_PASSWORD]
        )

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
        data = self.valid_input()
        for field in (
            FLOW_MODULE.CONF_MQTT_HOST,
            FLOW_MODULE.CONF_MQTT_PORT,
            FLOW_MODULE.CONF_MQTT_HUB_ID,
            FLOW_MODULE.CONF_MQTT_USERNAME,
            FLOW_MODULE.CONF_MQTT_PASSWORD,
            FLOW_MODULE.CONF_MQTT_USE_TLS,
            FLOW_MODULE.CONF_MQTT_VERIFY_TLS,
            FLOW_MODULE.CONF_MQTT_KEEPALIVE,
        ):
            data.pop(field, None)
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

    def test_unknown_submission_fields_are_not_stored(self):
        user_input = self.valid_input()
        user_input["unexpected_field"] = "fabricated-unexpected-value"
        flow = FLOW_MODULE.GritHubConfigFlow()
        result = _run_immediate(flow.async_step_user(user_input))
        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("unexpected_field", result["data"])
        self.assertEqual(len(flow.created_entries), 1)



if __name__ == "__main__":
    unittest.main()

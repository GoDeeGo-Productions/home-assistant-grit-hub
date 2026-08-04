"""Network-free tests for documented hub API methods and sanitization."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components" / "grit_hub"
HUB_ID = "0123456789abcdef0123456789abcdef"
BROKER_IP = "192.0.2.44"
FABRICATED_LEGACY_TOKEN = (
    "eyJhbGciOiJmYWJyaWNhdGVkIn0."
    + ("A" * 5_000)
    + ".fabricated-signature"
)


def _load_api():
    package_name = "_grit_api_discovery_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_ROOT)]

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientTimeout = lambda **kwargs: kwargs
    aiohttp.ClientError = OSError
    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType(
        "homeassistant.helpers.aiohttp_client"
    )
    aiohttp_client.async_get_clientsession = lambda *_args, **_kwargs: object()
    helpers.aiohttp_client = aiohttp_client
    homeassistant.helpers = helpers
    stubs = {
        package_name: package,
        "aiohttp": aiohttp,
        "homeassistant": homeassistant,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
    }
    loaded = {}
    with mock.patch.dict(sys.modules, stubs):
        for module_name in ("const", "hub", "api"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{module_name}",
                COMPONENT_ROOT / f"{module_name}.py",
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            loaded[spec.name] = module
    sys.modules.update(loaded)
    return loaded[f"{package_name}.api"]


API = _load_api()


class ApiHubTests(unittest.TestCase):
    def client(self):
        return API.GritHubApiClient(
            object(),
            "https://api.fabricated.invalid",
            "fabricated-api-token",
            True,
        )

    def test_current_hub_uses_documented_existing_request_and_allowlist(self):
        client = self.client()
        calls = []

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {
                "id": HUB_ID,
                "displayName": "Fabricated Hub",
                "name": "Fallback Name",
                "hubVersion": "1.1.test",
                "ipAddressEthernet": BROKER_IP,
                "connectedToInternet": True,
                "branch": "fabricated",
                "systemLedBrightness": 42,
                "disableHubButtons": False,
                "automaticGritLockTime": None,
                "wifiSSID": "discarded-network",
                "wifiPassword": "discarded-password",
                "emailSettings": "discarded-email",
                "subscriptionCode": "discarded-subscription",
                "tokens": ["discarded-token"],
                "arbitrary": {"discarded": True},
            }

        client.request = request
        result = asyncio.run(client.get_hub())
        self.assertEqual(
            calls,
            [
                (
                    "GET",
                    "/api/hub",
                    {"timeout": API.REST_DISCOVERY_TIMEOUT},
                )
            ],
        )
        self.assertEqual(len(calls), 1)
        self.assertFalse(
            any(path == "/api/hub/1" for _method, path, _kwargs in calls)
        )
        self.assertEqual(
            set(result),
            {
                "id",
                "displayName",
                "name",
                "hubVersion",
                "ipAddressEthernet",
                "connectedToInternet",
                "branch",
                "systemLedBrightness",
                "disableHubButtons",
                "automaticGritLockTime",
            },
        )
        for sensitive in (
            "wifiSSID",
            "wifiPassword",
            "emailSettings",
            "subscriptionCode",
            "tokens",
            "arbitrary",
        ):
            self.assertNotIn(sensitive, result)
        self.assertEqual(
            client.headers["Authorization"],
            "Bearer fabricated-api-token",
        )

    def test_long_legacy_token_reaches_mocked_http_request_unchanged(self):
        calls = []

        class FakeResponse:
            status = 204
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def text(self):
                return ""

        class FakeSession:
            def request(self, method, url, **kwargs):
                calls.append((method, url, kwargs))
                return FakeResponse()

        client = API.GritHubApiClient(
            object(),
            "https://api.fabricated.invalid",
            FABRICATED_LEGACY_TOKEN,
            True,
        )
        client.session = FakeSession()

        result = asyncio.run(client.request("GET", "/api/hub"))

        self.assertIsNone(result)
        self.assertEqual(len(calls), 1)
        method, url, kwargs = calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.fabricated.invalid/api/hub")
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            f"Bearer {FABRICATED_LEGACY_TOKEN}",
        )
        self.assertNotIn(FABRICATED_LEGACY_TOKEN, url)

    def test_malformed_hub_values_are_not_retained(self):
        client = self.client()

        async def request(_method, _path, **_kwargs):
            return {
                "id": "not-a-documented-id",
                "ipAddressEthernet": "not-an-ip",
                "connectedToInternet": "yes",
                "systemLedBrightness": 101,
                "disableHubButtons": 1,
                "hubVersion": {"raw": True},
            }

        client.request = request
        result = asyncio.run(client.get_hub())
        self.assertEqual(result, {})

    def test_http_401_retains_only_status_and_never_reads_error_body(self):
        client = self.client()
        calls = []
        private_body = "fabricated-private-error-body"

        class FakeResponse:
            status = 401
            headers = {"Content-Type": "application/json"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def text(self):
                raise AssertionError(private_body)

        class FakeSession:
            def request(self, method, url, **kwargs):
                calls.append((method, url, kwargs))
                return FakeResponse()

        client.session = FakeSession()
        with self.assertRaises(API.GritHubApiError) as captured:
            asyncio.run(
                client.request(
                    "GET",
                    "/api/hub",
                    timeout=API.REST_DISCOVERY_TIMEOUT,
                )
            )

        self.assertEqual(captured.exception.http_status, 401)
        self.assertEqual(
            str(captured.exception),
            "GET /api/hub failed: HTTP 401",
        )
        self.assertNotIn(private_body, repr(captured.exception))
        method, url, kwargs = calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.fabricated.invalid/api/hub")
        self.assertNotIn("fabricated-api-token", url)
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer fabricated-api-token",
        )

    def test_device_collections_are_sanitized_before_return(self):
        client = self.client()
        private_values = (
            "fabricated-person-name",
            "fabricated-card-number",
            "fabricated-diagnostic-payload",
        )

        async def request(_method, _path, **_kwargs):
            return {
                "items": [
                    {
                        "id": "device-fabricated",
                        "name": "Fabricated Reader",
                        "state": False,
                        "lockout": False,
                        "gritLockEnabled": True,
                        "gritLockState": False,
                        "users": [{"name": private_values[0]}],
                        "cardNumber": private_values[1],
                        "diagnostics": {"raw": private_values[2]},
                    }
                ]
            }

        client.request = request
        result = asyncio.run(client.get_collection("rfid"))

        self.assertEqual(
            result,
            [
                {
                    "id": "device-fabricated",
                    "name": "Fabricated Reader",
                    "gritLockEnabled": True,
                    "gritLockState": False,
                }
            ],
        )
        rendered = repr(result)
        for private in private_values:
            self.assertNotIn(private, rendered)

    def test_rfid_collection_drops_unproven_state_and_lockout(self):
        for state in (True, False, 1, "false"):
            with self.subTest(state=state):
                rfid = API.sanitize_device_data(
                    {
                        "id": "reader-test",
                        "state": state,
                        "lockout": False,
                    },
                    device_type="rfid",
                )
                self.assertNotIn("state", rfid)
                self.assertNotIn("lockout", rfid)

    def test_individual_rfid_get_is_bounded_encoded_and_sanitized(self):
        client = self.client()
        calls = []
        private_value = "fabricated-private-reader-data"

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {
                "id": "reader/id",
                "state": False,
                "lockout": False,
                "onlineStatus": True,
                "displayName": "Fabricated Reader",
                "version": "1.2.3-test",
                "users": [{"name": private_value}],
            }

        client.request = request
        result = asyncio.run(client.get_rfid_device("reader/id"))

        self.assertEqual(
            result,
            {
                "id": "reader/id",
                "state": False,
                "onlineStatus": True,
                "displayName": "Fabricated Reader",
                "version": "1.2.3-test",
            },
        )
        self.assertEqual(
            calls,
            [
                (
                    "GET",
                    "/api/rfid/reader%2Fid",
                    {"timeout": API.REST_DISCOVERY_TIMEOUT},
                )
            ],
        )
        self.assertNotIn(private_value, repr(result))
        self.assertNotIn("lockout", result)

    def test_individual_rfid_state_and_online_are_strict_booleans(self):
        for value in (1, 0, "true", None, [], {}):
            with self.subTest(value=value):
                result = API.sanitize_rfid_device_data(
                    {
                        "id": "reader-test",
                        "state": value,
                        "onlineStatus": value,
                    }
                )
                self.assertEqual(result, {"id": "reader-test"})

    def test_individual_rfid_identifier_validation_fails_closed(self):
        client = self.client()
        client.request = mock.AsyncMock()
        for value in (None, True, 42, "", " ", ".", "..", "line\nbreak", "x" * 129):
            with self.subTest(value=value):
                with self.assertRaises(API.GritHubApiError):
                    asyncio.run(client.get_rfid_device(value))
        client.request.assert_not_awaited()

    def test_collector_collection_drops_unproven_state(self):
        for state in (True, False, 1, "false"):
            with self.subTest(state=state):
                collector = API.sanitize_device_data(
                    {"id": "collector-test", "state": state},
                    device_type="collector",
                )
                self.assertNotIn("state", collector)

    def test_individual_collector_get_is_encoded_bounded_and_sanitized(self):
        client = self.client()
        calls = []
        private_value = "fabricated-private-collector-data"

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {
                "id": "collector/id",
                "state": True,
                "stateChanging": False,
                "stateChangingTo": True,
                "isOnline": True,
                "onlineStatus": True,
                "displayName": "Fabricated Collector",
                "version": "1.2.3-test",
                "diagnostics": {"private": private_value},
            }

        client.request = request
        result = asyncio.run(client.get_collector_device("collector/id"))

        self.assertEqual(
            result,
            {
                "id": "collector/id",
                "state": True,
                "stateChanging": False,
                "stateChangingTo": True,
                "isOnline": True,
                "onlineStatus": True,
                "displayName": "Fabricated Collector",
                "version": "1.2.3-test",
            },
        )
        self.assertEqual(
            calls,
            [
                (
                    "GET",
                    "/api/collector/collector%2Fid",
                    {"timeout": API.REST_DISCOVERY_TIMEOUT},
                )
            ],
        )
        self.assertNotIn(private_value, repr(result))

    def test_individual_collector_values_are_strict_and_id_is_validated(self):
        for value in (1, 0, "true", None, [], {}):
            with self.subTest(value=value):
                result = API.sanitize_collector_device_data(
                    {
                        "id": "collector-test",
                        "state": value,
                        "stateChanging": value,
                        "stateChangingTo": value,
                        "isOnline": value,
                        "onlineStatus": value,
                    }
                )
                self.assertEqual(result, {"id": "collector-test"})

        client = self.client()
        client.request = mock.AsyncMock()
        for value in (
            None,
            True,
            42,
            "",
            " ",
            ".",
            "..",
            "line\nbreak",
            "x" * 129,
        ):
            with self.subTest(identifier=value):
                with self.assertRaises(API.GritHubApiError):
                    asyncio.run(client.get_collector_device(value))
        client.request.assert_not_awaited()
    def test_targeted_telemetry_refresh_uses_documented_bounded_endpoint(self):
        client = self.client()
        calls = []

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"success": True, "message": "fabricated success"}

        client.request = request
        asyncio.run(client.request_device_telemetry("gate", "gate/id"))
        asyncio.run(client.request_device_telemetry("rfid", "42"))

        timeout = API.REST_DISCOVERY_TIMEOUT
        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/api/device/mesh-telemetry/refresh/gate/gate%2Fid",
                    {"timeout": timeout},
                ),
                (
                    "POST",
                    "/api/device/mesh-telemetry/refresh/rfid/42",
                    {"timeout": timeout},
                ),
            ],
        )

    def test_targeted_telemetry_refresh_fails_closed(self):
        client = self.client()
        client.request = mock.AsyncMock(
            return_value={"success": False, "message": "fabricated failure"}
        )
        with self.assertRaises(API.GritHubApiError) as captured:
            asyncio.run(client.request_device_telemetry("gate", "gate-1"))
        self.assertEqual(
            str(captured.exception),
            "Telemetry refresh request failed",
        )
        self.assertNotIn("fabricated failure", str(captured.exception))

        client.request.reset_mock()
        invalid = (
            ("solenoid", "device-1"),
            ("gate", ""),
            ("gate", "."),
            ("gate", ".."),
            ("rfid", True),
            ("rfid", 42),
            ("rfid", "line\nbreak"),
            ("gate", "x" * 129),
        )
        for device_type, device_id in invalid:
            with self.subTest(device_type=device_type, device_id=type(device_id)):
                with self.assertRaises(API.GritHubApiError):
                    asyncio.run(
                        client.request_device_telemetry(device_type, device_id)
                    )
        client.request.assert_not_awaited()

    def test_explicit_hub_commands_use_documented_paths_and_bodies(self):
        client = self.client()
        calls = []

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return None

        client.request = request
        asyncio.run(client.set_gritlock(True))
        asyncio.run(client.set_gritlock(False))
        asyncio.run(client.set_system_led_brightness(HUB_ID, 60))
        asyncio.run(client.restart_service())
        asyncio.run(client.reboot_hub())

        timeout = API.REST_DISCOVERY_TIMEOUT
        self.assertEqual(
            calls,
            [
                (
                    "PUT",
                    "/api/hub/lockout",
                    {"json": {"state": True}, "timeout": timeout},
                ),
                (
                    "PUT",
                    "/api/hub/lockout",
                    {"json": {"state": False}, "timeout": timeout},
                ),
                (
                    "PUT",
                    f"/api/hub/{HUB_ID}/settings",
                    {
                        "json": {"systemLedBrightness": 60},
                        "timeout": timeout,
                    },
                ),
                ("PUT", "/api/hub/restart", {"timeout": timeout}),
                ("PUT", "/api/hub/reboot", {"timeout": timeout}),
            ],
        )

    def test_invalid_command_inputs_fail_before_request(self):
        client = self.client()
        client.request = mock.AsyncMock()

        with self.assertRaises(API.GritHubApiError):
            asyncio.run(client.set_gritlock("true"))
        for hub_id, brightness in (
            ("invalid", 50),
            (HUB_ID, -1),
            (HUB_ID, 101),
            (HUB_ID, True),
        ):
            with self.subTest(hub_id=hub_id, brightness=brightness):
                with self.assertRaises(API.GritHubApiError):
                    asyncio.run(
                        client.set_system_led_brightness(
                            hub_id,
                            brightness,
                        )
                    )
        client.request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

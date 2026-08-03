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
                    "/api/hub/1",
                    {"timeout": API.REST_DISCOVERY_TIMEOUT},
                )
            ],
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

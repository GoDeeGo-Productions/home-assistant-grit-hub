"""Tests for the redacted current-hub response diagnostic."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock


FABRICATED_LEGACY_TOKEN = (
    "eyJhbGciOiJmYWJyaWNhdGVkIn0."
    + ("A" * 5_000)
    + ".fabricated-signature"
)
SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "diagnose_hub_response.py"
)
SPEC = importlib.util.spec_from_file_location(
    "grit_hub_diagnose_hub_response",
    SCRIPT_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("diagnostic module could not be loaded")
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTIC)


class HubResponseDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hub_id = "0123456789abcdef0123456789abcdef"
        self.ip_address = "192.0.2.44"
        self.private_values = (
            "fabricated-bearer-token",
            "fabricated-wifi-password",
            "fabricated-email@example.invalid",
            "fabricated-subscription-value",
        )

    def hub(self) -> dict[str, object]:
        return {
            "id": self.hub_id,
            "ipAddressEthernet": self.ip_address,
            "wifiPassword": self.private_values[1],
            "email": self.private_values[2],
            "subscription": self.private_values[3],
        }

    def assert_redacted(self, summary: dict[str, object]) -> None:
        rendered = repr(summary)
        self.assertNotIn(self.hub_id, rendered)
        self.assertNotIn(self.ip_address, rendered)
        for value in self.private_values:
            self.assertNotIn(value, rendered)

    def test_direct_object_reports_only_allowlisted_metadata(self) -> None:
        summary = DIAGNOSTIC.summarize_response(self.hub(), 200)

        self.assertEqual(summary["http_status"], 200)
        self.assertEqual(summary["response_type"], "object")
        self.assertIsNone(summary["known_wrapper"])
        self.assertTrue(summary["id_exists"])
        self.assertEqual(summary["id_type"], "string")
        self.assertEqual(summary["id_length"], 32)
        self.assertTrue(summary["ipAddressEthernet_exists"])
        self.assertTrue(summary["ipAddressEthernet_syntactically_valid"])
        self.assert_redacted(summary)

    def test_one_element_list_reports_shape_without_values(self) -> None:
        summary = DIAGNOSTIC.summarize_response([self.hub()], 200)

        self.assertEqual(summary["response_type"], "array")
        self.assertEqual(summary["known_wrapper"], "one_element_list")
        self.assertTrue(summary["id_exists"])
        self.assertTrue(summary["ipAddressEthernet_exists"])
        self.assert_redacted(summary)

    def test_known_wrapper_reports_wrapper_without_values(self) -> None:
        for wrapper in ("data", "hub", "item", "result"):
            with self.subTest(wrapper=wrapper):
                summary = DIAGNOSTIC.summarize_response(
                    {wrapper: self.hub()},
                    200,
                )
                self.assertEqual(summary["known_wrapper"], wrapper)
                self.assertTrue(summary["id_exists"])
                self.assertTrue(summary["ipAddressEthernet_exists"])
                self.assert_redacted(summary)

    def test_malformed_fields_report_type_and_validity_not_values(self) -> None:
        summary = DIAGNOSTIC.summarize_response(
            {"id": 123, "ipAddressEthernet": "not-an-address"},
            200,
        )

        self.assertTrue(summary["id_exists"])
        self.assertEqual(summary["id_type"], "number")
        self.assertIsNone(summary["id_length"])
        self.assertTrue(summary["ipAddressEthernet_exists"])
        self.assertFalse(summary["ipAddressEthernet_syntactically_valid"])
        self.assertNotIn("not-an-address", repr(summary))

    def test_fetch_uses_bearer_header_without_exposing_token(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def getcode():
                return 200

            def read(self, _maximum):
                return json.dumps(self_hub).encode("utf-8")

        self_hub = self.hub()
        token = self.private_values[0]
        with mock.patch.object(
            DIAGNOSTIC,
            "_open_request",
            return_value=FakeResponse(),
        ) as opened:
            summary = DIAGNOSTIC.fetch_summary(
                "https://api.diagnostic-test.invalid",
                token,
            )

        request = opened.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            f"Bearer {token}",
        )
        self.assertNotIn(token, repr(summary))
        self.assert_redacted(summary)

    def test_long_legacy_token_reaches_mocked_request_unchanged(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def getcode():
                return 200

            def read(self, _maximum):
                return json.dumps(self_hub).encode("utf-8")

        self_hub = self.hub()
        with mock.patch.object(
            DIAGNOSTIC,
            "_open_request",
            return_value=FakeResponse(),
        ) as opened:
            summary = DIAGNOSTIC.fetch_summary(
                "https://api.diagnostic-test.invalid",
                FABRICATED_LEGACY_TOKEN,
            )

        self.assertIsNone(summary["generic_error_category"])
        request = opened.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            f"Bearer {FABRICATED_LEGACY_TOKEN}",
        )
        self.assertNotIn(FABRICATED_LEGACY_TOKEN, repr(summary))

    def test_only_actual_http_401_maps_to_invalid_auth(self) -> None:
        with mock.patch.object(DIAGNOSTIC, "_open_request") as opened:
            blank = DIAGNOSTIC.fetch_summary(
                "https://api.diagnostic-test.invalid",
                "",
            )
        self.assertEqual(blank["generic_error_category"], "invalid_token")
        opened.assert_not_called()

        for status, expected in (
            (401, "invalid_auth"),
            (403, "hub_request_failed"),
        ):
            with self.subTest(status=status):
                error = DIAGNOSTIC.HTTPError(
                    "https://api.diagnostic-test.invalid/api/hub/1",
                    status,
                    "fabricated HTTP error",
                    {},
                    None,
                )
                with mock.patch.object(
                    DIAGNOSTIC,
                    "_open_request",
                    side_effect=error,
                ) as opened:
                    summary = DIAGNOSTIC.fetch_summary(
                        "https://api.diagnostic-test.invalid",
                        FABRICATED_LEGACY_TOKEN,
                    )
                error.close()
                opened.assert_called_once()
                self.assertEqual(summary["generic_error_category"], expected)
                self.assertEqual(summary["http_status"], status)
                self.assertNotIn(FABRICATED_LEGACY_TOKEN, repr(summary))

    def test_arbitrary_top_level_key_names_are_not_disclosed(self) -> None:
        private_key = "fabricated-person@example.invalid"
        summary = DIAGNOSTIC.summarize_response(
            {
                "id": self.hub_id,
                private_key: {"payload": self.private_values[3]},
                "wifiPassword": self.private_values[1],
            },
            200,
        )

        self.assertEqual(summary["top_level_key_names"], ["id"])
        self.assertTrue(summary["top_level_key_names_truncated"])
        self.assertNotIn(private_key, repr(summary))
        self.assert_redacted(summary)

    def test_open_request_installs_fail_closed_redirect_handler(self) -> None:
        request = DIAGNOSTIC.Request(
            "https://api.diagnostic-test.invalid/api/hub/1",
            headers={"Authorization": f"Bearer {self.private_values[0]}"},
        )
        opener = mock.Mock()
        opener.open.return_value = mock.sentinel.response
        with mock.patch.object(
            DIAGNOSTIC,
            "build_opener",
            return_value=opener,
        ) as build_opener:
            result = DIAGNOSTIC._open_request(
                request,
                timeout=1,
                context=None,
            )

        self.assertIs(result, mock.sentinel.response)
        self.assertTrue(
            any(
                isinstance(handler, DIAGNOSTIC._NoRedirectHandler)
                for handler in build_opener.call_args.args
            )
        )
        handler = DIAGNOSTIC._NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://redirect.fabricated.invalid/api/hub/1",
            )
        )

    def test_error_summary_contains_no_request_details(self) -> None:
        summary = DIAGNOSTIC._error_summary(
            "hub_request_failed",
            http_status=403,
        )

        self.assertEqual(summary["http_status"], 403)
        self.assertEqual(
            summary["generic_error_category"],
            "hub_request_failed",
        )
        self.assert_redacted(summary)


if __name__ == "__main__":
    unittest.main()

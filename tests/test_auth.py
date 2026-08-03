"""Tests for opaque GRIT bearer-token validation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


AUTH_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "grit_hub"
    / "auth.py"
)
SPEC = importlib.util.spec_from_file_location("grit_hub_auth_test", AUTH_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("authentication helper could not be loaded")
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)

FABRICATED_LEGACY_TOKEN = (
    "eyJhbGciOiJmYWJyaWNhdGVkIn0."
    + ("A" * 5_000)
    + ".fabricated-signature"
)


class BearerTokenValidationTests(unittest.TestCase):
    def test_long_legacy_shaped_token_is_preserved_exactly(self) -> None:
        self.assertGreater(len(FABRICATED_LEGACY_TOKEN), 4_096)
        self.assertEqual(
            AUTH.validate_bearer_token(FABRICATED_LEGACY_TOKEN),
            FABRICATED_LEGACY_TOKEN,
        )
        self.assertEqual(
            AUTH.bearer_authorization_value(FABRICATED_LEGACY_TOKEN),
            f"Bearer {FABRICATED_LEGACY_TOKEN}",
        )

    def test_printable_opaque_characters_are_not_format_validated(self) -> None:
        token = "fabricated_opaque.+/~=$:@!%&'()*,-;?[]{}"
        self.assertEqual(AUTH.validate_bearer_token(token), token)

    def test_only_unsafe_or_unbounded_local_values_are_rejected(self) -> None:
        invalid_values = (
            None,
            "",
            "   ",
            "fabricated\nvalue",
            "fabricated\x00value",
            "fabricated\x85value",
            "fabricated-\u20ac-value",
            "A" * (AUTH.MAX_BEARER_TOKEN_BYTES + 1),
        )
        for value in invalid_values:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(AUTH.InvalidBearerToken):
                    AUTH.validate_bearer_token(value)


if __name__ == "__main__":
    unittest.main()

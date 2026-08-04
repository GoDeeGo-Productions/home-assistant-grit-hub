"""Network-free tests for the bounded GRIT log redactor."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "grit_log_redactor_under_test",
    ROOT / "scripts" / "redact_grit_log.py",
)
REDACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REDACTOR)


class RedactGritLogTests(unittest.TestCase):
    def test_sensitive_shapes_are_redacted(self) -> None:
        source = (
            "Authorization: Bearer fabricated-secret\n"
            "bearer second-secret\n"
            "url?auth_token=query-secret&safe=yes\n"
            "token=grit_fabricatedOpaqueToken123\n"
            "host=203.0.113.44\n"
            "contact=person@example.invalid\n"
            "keep=this-safe-line\n"
        )
        result = REDACTOR.redact_text(source)
        for secret in (
            "fabricated-secret",
            "second-secret",
            "query-secret",
            "grit_fabricatedOpaqueToken123",
            "203.0.113.44",
            "person@example.invalid",
        ):
            self.assertNotIn(secret, result)
        self.assertIn("Authorization: Bearer [REDACTED]", result)
        self.assertIn("[REDACTED-GRIT-TOKEN]", result)
        self.assertIn("[REDACTED-IPV4]", result)
        self.assertIn("[REDACTED-EMAIL]", result)
        self.assertIn("keep=this-safe-line", result)

    def test_redact_file_writes_distinct_new_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.log"
            target = root / "redacted.log"
            source.write_bytes(
                b"Authorization: Bearer fabricated-secret\r\nsafe\r\n"
            )
            REDACTOR.redact_file(source, target)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "Authorization: Bearer [REDACTED]\nsafe\n",
            )
            self.assertIn("fabricated-secret", source.read_text(encoding="utf-8"))

    def test_same_file_and_existing_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.log"
            target = root / "existing.log"
            source.write_text("safe", encoding="utf-8")
            target.write_text("do not overwrite", encoding="utf-8")
            with self.assertRaises(ValueError):
                REDACTOR.redact_file(source, source)
            with self.assertRaises(FileExistsError):
                REDACTOR.redact_file(source, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "do not overwrite")

    def test_oversized_input_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.log"
            target = root / "redacted.log"
            with source.open("wb") as source_file:
                source_file.truncate(REDACTOR.MAX_INPUT_BYTES + 1)
            with self.assertRaises(ValueError):
                REDACTOR.redact_file(source, target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

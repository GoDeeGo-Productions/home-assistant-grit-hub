"""Manifest validation tests for the GRIT Hub integration."""
from __future__ import annotations

import json
from pathlib import Path
import unittest


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "grit_hub"
    / "manifest.json"
)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_manifest_json_is_valid_object(self):
        self.assertIsInstance(self.manifest, dict)

    def test_paho_requirement_is_exactly_pinned(self):
        self.assertEqual(
            self.manifest["requirements"],
            ["paho-mqtt==2.1.0"],
        )

    def test_home_assistant_mqtt_dependency_is_not_declared(self):
        self.assertNotIn("mqtt", self.manifest.get("dependencies", []))

    def test_integration_domain_is_unchanged(self):
        self.assertEqual(self.manifest["domain"], "grit_hub")


if __name__ == "__main__":
    unittest.main()

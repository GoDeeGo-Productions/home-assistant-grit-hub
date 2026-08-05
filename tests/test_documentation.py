"""Release-documentation consistency checks."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
    ROOT / "CONTRIBUTING.md",
    *(ROOT / "docs").glob("*.md"),
)
REQUIRED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "docs/INSTALLATION.md",
    "docs/ENTITIES.md",
    "docs/ARCHITECTURE.md",
    "docs/TROUBLESHOOTING.md",
    "docs/ACCEPTANCE_REPORT_v0.1.0.md",
    "docs/ACCEPTANCE_REPORT_v0.1.1.md",
    "docs/RELEASE_CHECKLIST.md",
    "docs/RELEASE_CHECKLIST_v0.1.1.md",
    "docs/REPOSITORY_TRANSFER.md",
    "docs/REPOSITORY_METADATA.md",
)
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
PRIVATE_IPV4_PATTERN = re.compile(
    r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)"
)
EMAIL_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9-]+(?:\.[A-Z0-9-]+)+\b"
)
TOKEN_PATTERN = re.compile(r"\bgrit_[A-Za-z0-9._~+/=-]{20,}\b")
LIVE_ID_PATTERN = re.compile(r"(?i)\b[0-9a-f]{32}\b")


class DocumentationTests(unittest.TestCase):
    def test_required_release_documents_exist(self) -> None:
        for relative in REQUIRED_FILES:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_relative_markdown_links_resolve(self) -> None:
        for document in PUBLIC_DOCUMENTS:
            text = document.read_text(encoding="utf-8")
            for target in LINK_PATTERN.findall(text):
                with self.subTest(document=document.name, target=target):
                    clean = target.strip("<>").split("#", 1)[0]
                    if not clean or re.match(r"^[a-z]+://", clean, re.I):
                        continue
                    self.assertTrue((document.parent / clean).is_file())

    def test_public_documents_contain_no_private_installation_shapes(self) -> None:
        for document in PUBLIC_DOCUMENTS:
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.name):
                self.assertIsNone(PRIVATE_IPV4_PATTERN.search(text))
                self.assertIsNone(EMAIL_PATTERN.search(text))
                self.assertIsNone(TOKEN_PATTERN.search(text))
                self.assertIsNone(LIVE_ID_PATTERN.search(text))

    def test_release_status_and_version_are_consistent(self) -> None:
        manifest = json.loads(
            (ROOT / "custom_components/grit_hub/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_flat = " ".join(readme.replace(">", "").split())
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        acceptance_v011 = (
            ROOT / "docs/ACCEPTANCE_REPORT_v0.1.1.md"
        ).read_text(encoding="utf-8")
        checklist_v011 = (
            ROOT / "docs/RELEASE_CHECKLIST_v0.1.1.md"
        ).read_text(encoding="utf-8")
        release_url = (
            "https://github.com/GoDeeGo-Productions/"
            "home-assistant-grit-hub/releases/tag/v0.1.1"
        )

        self.assertEqual(manifest["version"], "0.1.1")
        self.assertIn(
            "a `v0.1.2` corrective patch candidate is in development",
            readme_flat,
        )
        self.assertIn("The `v0.1.1` release was published", readme_flat)
        self.assertIn("remains the latest published release", readme_flat)
        self.assertIn(release_url, readme)
        self.assertIn("0.1.0 — 2026-08-04", changelog)
        self.assertIn("0.1.1 — 2026-08-05", changelog)
        self.assertIn(release_url, changelog)
        self.assertIn(
            "Corrected the end-to-end GRITLock state pipeline",
            changelog,
        )

        acceptance_flat = " ".join(acceptance_v011.split())
        self.assertIn(
            "Published v0.1.1 is superseded; v0.1.2 remains blocked "
            "pending live acceptance on Dion's and Jeff's installations.",
            acceptance_flat,
        )
        for evidence_item in (
            "- [x] All-`gte=0` Lock and Unlock passed on Jeff's installation",
            "- [x] Mixed-`gte` participant regression reproduced on Dion's "
            "installation",
            "- [x] PR #26 corrected command-generation settlement",
            "- [x] Exact merged PR #26 build reproduced wrong startup and "
            "post-command state on Dion's installation",
            "- [x] End-to-end state-pipeline cause identified and corrected "
            "offline",
        ):
            self.assertIn(evidence_item, checklist_v011)
        for pending_item in (
            "- [ ] Corrective v0.1.2 Lock, Unlock, confirmation, and "
            "immediate entity state pass on both installations",
            "- [ ] HACS validation green for the corrective branch",
            "- [ ] Hassfest validation green for the corrective branch",
            "- [ ] Jeff GRITLock Lock succeeds with all-`gte=0`, `gls=1`",
            "- [ ] Jeff GRITLock Unlock succeeds with all-`gte=0`, `gls=0`",
            "- [ ] Dion startup all-`gte=0`, `gls=0` displays Unlocked and "
            "offers Lock",
            "- [ ] Tag `v0.1.2` created",
            "- [ ] GitHub release v0.1.2 created",
            "- [ ] Final HACS install completed from published `v0.1.2`",
        ):
            self.assertIn(pending_item, checklist_v011)
        self.assertNotIn("0.1.2 — 2026-", changelog)
        self.assertNotIn("- [x] Tag `v0.1.2` created", checklist_v011)
        self.assertNotIn("- [x] GitHub release v0.1.2 created", checklist_v011)

    def test_published_release_and_remaining_decisions_are_consistent(
        self,
    ) -> None:
        final_url = (
            "https://github.com/GoDeeGo-Productions/"
            "home-assistant-grit-hub"
        )
        release_url = f"{final_url}/releases/tag/v0.1.0"
        release_commit = "9464dbab1798cae3b2d0f538d0db3ed64d510884"
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        security_flat = " ".join(security.split())
        checklist = (ROOT / "docs/RELEASE_CHECKLIST.md").read_text(
            encoding="utf-8"
        )
        transfer = (ROOT / "docs/REPOSITORY_TRANSFER.md").read_text(
            encoding="utf-8"
        )
        metadata = (ROOT / "docs/REPOSITORY_METADATA.md").read_text(
            encoding="utf-8"
        )
        acceptance = (
            ROOT / "docs/ACCEPTANCE_REPORT_v0.1.0.md"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs/INSTALLATION.md").read_text(
            encoding="utf-8"
        )
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        manifest = json.loads(
            (ROOT / "custom_components/grit_hub/manifest.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("Copyright (c) 2026 GoDeeGo Productions", license_text)
        self.assertIn(
            "GitHub Private Vulnerability Reporting", security_flat
        )
        self.assertIn("Security > Report a vulnerability", security_flat)
        self.assertNotIn("no approved private security", security)
        self.assertIn(
            "- [x] Organisation display name and namespace verified",
            checklist,
        )
        self.assertIn("- [x] MIT licence approved and present", checklist)
        self.assertIn(
            "- [x] Security reporting channel approved", checklist
        )
        self.assertIn("- [x] Repository transferred", checklist)
        self.assertIn(
            "- [x] Final repository URL confirmed after transfer", checklist
        )
        self.assertIn(
            "- [x] Local Git remote updated to the final repository URL",
            checklist,
        )
        for completed_item in (
            "- [x] GitHub Private Vulnerability Reporting enabled and verified",
            "- [x] Dependency graph enabled",
            "- [x] Dependabot alerts enabled",
            "- [x] GitHub description set",
            "- [x] GitHub topics set",
            "- [x] Full CI green",
            "- [x] Full unit suite green",
            "- [x] Markdown links valid",
            "- [x] JSON/YAML valid",
            "- [x] `git diff --check` clean",
            "- [x] Manifest version confirmed as 0.1.0",
            "- [x] Changelog finalised",
            "- [x] Acceptance report signed off",
            "- [x] issue templates checked",
            "- [x] workflow badge decision checked",
            "- [x] Git history exposure reviewed",
            "- [x] HACS custom install retested against final organisation URL",
            "- [x] Final release commit selected: " + f"`{release_commit}`",
            "- [x] Tag `v0.1.0`",
            "- [x] GitHub release created:",
            "- [x] Release notes published",
        ):
            self.assertIn(completed_item, checklist)
        for live_item in (
            "Clean HACS install",
            "Initial API authentication",
            "MQTT connection and exact subscription",
            "Gate startup state",
            "Gate HA command",
            "Gate GRIT app update",
            "Mixed RFID startup states",
            "RFID HA lock/unlock",
            "RFID GRIT app update responsiveness",
            "Offline RFID unavailable",
            "GRITLock lock/unlock",
            "Collector on/off",
            "Collector delayed shutdown",
            "LED/other implemented controls",
            "Token rotation/Reconfigure",
            "No duplicate devices/entities",
            "Home Assistant restart",
            "Normal uninstall",
            "Deterministic clean reinstall",
        ):
            self.assertIn(f"- [x] {live_item}", checklist)
        for pending_item in (
            "- [ ] Maintainer ownership confirmed",
            "- [ ] Future commit identity policy confirmed",
            "- [ ] CODEOWNERS checked",
            "- [ ] Official GRIT webpage link published",
            "- [ ] HACS default catalogue submission decision made",
        ):
            self.assertIn(pending_item, checklist)
        acceptance_flat = " ".join(acceptance.split())
        self.assertIn(
            "Final acceptance completed; `v0.1.0` was published on "
            "2026-08-04.",
            acceptance_flat,
        )
        self.assertIn(release_commit, acceptance)
        self.assertIn(release_url, acceptance)
        self.assertIn(
            "- [x] Complete-history exposure review accepted.", acceptance
        )
        self.assertIn(
            "- [x] HACS custom installation accepted against the final "
            "repository URL.",
            acceptance,
        )
        for document in (
            transfer,
            metadata,
            acceptance,
            readme,
            installation,
            agents,
        ):
            self.assertIn("GoDeeGo Productions", document)
            self.assertIn("GoDeeGo-Productions", document)
            self.assertIn(final_url, document)
        self.assertEqual(manifest["documentation"], final_url)
        self.assertEqual(manifest["issue_tracker"], f"{final_url}/issues")
        self.assertEqual(manifest["codeowners"], ["@dionweisler-ux"])
        self.assertNotIn("has not yet been transferred", readme)
        self.assertNotIn(
            "final-URL verification remain pending", installation
        )

    def test_documented_platforms_match_const_and_modules(self) -> None:
        const_tree = ast.parse(
            (ROOT / "custom_components/grit_hub/const.py").read_text(
                encoding="utf-8"
            )
        )
        platforms = None
        for node in const_tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "PLATFORMS"
                for target in node.targets
            ):
                platforms = ast.literal_eval(node.value)
        self.assertIsNotNone(platforms)
        entities = (ROOT / "docs/ENTITIES.md").read_text(encoding="utf-8")
        for platform in platforms:
            with self.subTest(platform=platform):
                self.assertTrue(
                    (ROOT / f"custom_components/grit_hub/{platform}.py").is_file()
                )
                self.assertIn(f"`{platform}`", entities)

    def test_state_authority_and_publish_boundaries_are_documented(self) -> None:
        architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "Gate | MQTT live state",
            "RFID | Strict individual `GET /api/rfid/{id}`",
            "GRITLock | Settled unanimous MQTT `/gl` generation",
            "Collector | Strict individual `GET /api/collector/{id}` detail",
            "Production code contains no MQTT publish path.",
        ):
            self.assertIn(expected, architecture)

    def test_gritlock_dual_participant_modes_are_documented(self) -> None:
        architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(
            encoding="utf-8"
        )
        entities = (ROOT / "docs/ENTITIES.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs/TROUBLESHOOTING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("`gls` is the live lock state", architecture)
        self.assertIn("REST `gritLockEnabled` participant set", architecture)
        self.assertIn(
            "A complete REST list containing no enabled participant",
            architecture,
        )
        self.assertIn("observations have `gte=1`", architecture)
        self.assertIn("Timeout handling never settles active or", architecture)
        self.assertIn(
            "MQTT-derived participants are not persisted",
            architecture,
        )
        self.assertIn("all-`gte=0` generation", entities)
        self.assertIn("two firmware patterns are", troubleshooting)
        self.assertIn("mixed burst uses exactly", troubleshooting)
        self.assertIn("`gls=0` is unlocked (`False`)", architecture)
        self.assertIn("exact `False` is authority, not", entities)
        self.assertIn("entity is Unknown and unavailable", entities)
        self.assertIn("fails that generation without erasing", troubleshooting)
        self.assertNotIn("provisional REST startup state", entities)

    def test_mqtt_topic_scopes_and_safe_diagnostic_command_are_accurate(self) -> None:
        architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(
            encoding="utf-8"
        )
        troubleshooting = (ROOT / "docs/TROUBLESHOOTING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("`grit/<configured-hub-id>/+/+/#`", architecture)
        self.assertIn("`grit/+/+/+/#`", architecture)
        self.assertIn("uses `connect_async()`", architecture)
        self.assertIn(
            "runtime `GritLiveMqtt` client uses bounded `connect()`",
            architecture,
        )
        self.assertIn(
            'diagnose_hub_response.py --base-url "https://your-grit-server.example"',
            troubleshooting,
        )
        self.assertNotIn("diagnose_hub_response.py --url", troubleshooting)
        self.assertNotIn("diagnose_hub_response.py --token", troubleshooting)

    def test_clean_removal_targets_only_grit_hub_component(self) -> None:
        installation = (ROOT / "docs/INSTALLATION.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("/config/custom_components/grit_hub", installation)
        self.assertIn("Do not edit `/config/.storage`", installation)
        self.assertNotRegex(
            installation,
            r"(?:remove|delete).*?/config/custom_components(?:[\s`]|$)",
        )


if __name__ == "__main__":
    unittest.main()

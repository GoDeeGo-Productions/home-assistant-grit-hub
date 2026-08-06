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
    "docs/ACCEPTANCE_REPORT_v0.1.2.md",
    "docs/RELEASE_CHECKLIST.md",
    "docs/RELEASE_CHECKLIST_v0.1.1.md",
    "docs/RELEASE_CHECKLIST_v0.1.2.md",
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
        acceptance_v012 = (
            ROOT / "docs/ACCEPTANCE_REPORT_v0.1.2.md"
        ).read_text(encoding="utf-8")
        acceptance_v012_flat = " ".join(acceptance_v012.split())
        checklist_v011 = (
            ROOT / "docs/RELEASE_CHECKLIST_v0.1.1.md"
        ).read_text(encoding="utf-8")
        checklist_v012 = (
            ROOT / "docs/RELEASE_CHECKLIST_v0.1.2.md"
        ).read_text(encoding="utf-8")
        release_url = (
            "https://github.com/GoDeeGo-Productions/"
            "home-assistant-grit-hub/releases/tag/v0.1.1"
        )
        accepted_commit = "52d94f64a8ac570f187ffa4428d61a3db7163cf7"

        self.assertEqual(manifest["version"], "0.1.2")
        self.assertIn(
            "`v0.1.2` is the latest prepared release and is ready for "
            "publication after successful two-system live acceptance",
            readme_flat,
        )
        self.assertIn("It is not yet tagged or published", readme_flat)
        self.assertIn("published `v0.1.1` release is superseded", readme_flat)
        self.assertIn("remains a HACS Custom Repository", readme_flat)
        self.assertIn(release_url, readme)

        self.assertIn("## 0.1.2 — 2026-08-06", changelog)
        self.assertNotIn("## Unreleased", changelog)
        for expected in (
            "one continuous immutable observed-state channel",
            "fresh matching post-command `/gl` observation",
            "Dion's mixed `gte=1` Lock",
            "Jeff's all-`gte=0` Lock and Unlock pattern",
            "Preserved gate startup hydration and RFID startup/detail authority",
        ):
            self.assertIn(expected, changelog)

        self.assertIn(accepted_commit, acceptance_v012)
        self.assertIn("## Dion installation acceptance", acceptance_v012)
        self.assertIn("## Jeff installation acceptance", acceptance_v012)
        self.assertIn("406 unit tests passed", acceptance_v012)
        self.assertIn(
            "1 optional real-Paho smoke test was skipped as expected",
            acceptance_v012,
        )
        self.assertIn("HACS validation passed", acceptance_v012)
        self.assertIn("Hassfest validation passed", acceptance_v012)
        self.assertIn("manifest is prepared at version `0.1.2`", acceptance_v012)
        self.assertIn(
            "separate propagation-reliability issue",
            acceptance_v012_flat,
        )
        self.assertIn(
            "no `v0.1.2` tag or GitHub release exists yet",
            acceptance_v012_flat,
        )

        self.assertIn("Manifest version is exactly `0.1.2`", checklist_v012)
        self.assertIn(
            "- [ ] Working tree clean at the final release commit",
            checklist_v012,
        )
        self.assertIn("- [x] HACS validation passed", checklist_v012)
        self.assertIn("- [x] Hassfest validation passed", checklist_v012)
        for pending_item in (
            "- [ ] Final release commit selected and verified",
            "- [ ] `v0.1.2` tag pushed to the configured origin",
            "- [ ] GitHub release `v0.1.2` created",
            "- [ ] Post-release HACS Custom Repository install/update verified",
            "- [ ] Final corrective issue closeout completed",
        ):
            self.assertIn(pending_item, checklist_v012)

        self.assertIn("published but superseded", checklist_v011)
        self.assertIn("ACCEPTANCE_REPORT_v0.1.2.md", acceptance_v011)
        self.assertIn("RELEASE_CHECKLIST_v0.1.2.md", acceptance_v011)
        self.assertIn("52d94f64a8ac570f187ffa4428d61a3db7163cf7", checklist_v011)

        combined = "\n".join(
            (readme, changelog, acceptance_v011, acceptance_v012, checklist_v012)
        )
        for false_claim in (
            "v0.1.2 was published",
            "v0.1.2 has been published",
            "- [x] `v0.1.2` tag pushed",
            "- [x] GitHub release `v0.1.2` created",
            "releases/tag/v0.1.2",
        ):
            self.assertNotIn(false_claim, combined)

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
        architecture_flat = " ".join(architecture.split())
        for expected in (
            "Gate | MQTT live state",
            "RFID | Strict individual `GET /api/rfid/{id}`",
            "GRITLock | One latest immutable observation",
            "Collector | Strict individual `GET /api/collector/{id}` detail",
            "Production code contains no MQTT publish path.",
            "`POST /api/device/mesh-telemetry/refresh/{type}/{id}`",
            "`/req-tel` cannot hydrate or alter a gate",
            "`startup_status` source cannot confirm a command",
            "There are no command generation IDs, command-owned state model, "
            "or retained command-result map",
        ):
            self.assertIn(expected, architecture_flat)
    def test_startup_hydration_sources_and_boundaries_are_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        entities = (ROOT / "docs/ENTITIES.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs/TROUBLESHOOTING.md").read_text(
            encoding="utf-8"
        )
        readme_flat = " ".join(readme.split())
        entities_flat = " ".join(entities.split())
        for expected in (
            "exact runtime subscription is ready",
            "GRITLock instead opens one bounded",
            "messages without `gls` are ignored",
            "same displayed-state field",
            "The integration does not publish MQTT or operate equipment",
        ):
            self.assertIn(expected, readme_flat)
        for expected in (
            "assumption that a retained MQTT status exists",
            "Startup status is displayed-state authority only",
            "Malformed, incomplete, overflowing, or unsettled evidence "
            "preserves the last valid state",
        ):
            self.assertIn(expected, entities_flat)
        self.assertIn("does not depend on a retained message", troubleshooting)
        self.assertIn("`/req-tel` only shows", troubleshooting)
    def test_gritlock_dual_participant_modes_are_documented(self) -> None:
        architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(
            encoding="utf-8"
        )
        entities = (ROOT / "docs/ENTITIES.md").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "docs/TROUBLESHOOTING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("one latest immutable GRITLock state observation", architecture)
        self.assertIn("If one or more fresh observations have `gte=1`", architecture)
        self.assertIn(
            "every fresh observed trigger participates",
            " ".join(architecture.split()),
        )
        self.assertIn("sparse valid one-frame burst", architecture)
        self.assertIn(
            "only when every member is represented by current valid `gls`",
            " ".join(architecture.split()),
        )
        self.assertIn(
            "not fully represented, the latest valid observations",
            " ".join(architecture.split()),
        )
        self.assertIn(
            "Every valid observation restarts one 250 ms quiet", architecture
        )
        self.assertIn(
            "REST `gritLockEnabled` metadata does not mutate or redefine",
            architecture,
        )
        self.assertIn(
            "`gls=0` is unlocked (`False`)",
            " ".join(architecture.split()),
        )
        self.assertIn("exact `False` is authority, not", " ".join(entities.split()))
        self.assertIn("including a sparse one-frame burst", entities)
        self.assertIn("all-`gte=0` burst uses all fresh", troubleshooting)
        self.assertIn("mixed burst uses exactly", " ".join(troubleshooting.split()))
        self.assertIn("preserves an earlier valid state", troubleshooting)
        self.assertIn("No-op requests still send REST", entities)
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

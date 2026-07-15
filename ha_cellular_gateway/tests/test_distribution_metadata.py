from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
MANIFEST = REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "manifest.json"
HACS = REPO_ROOT / "hacs.json"
QUALITY_SCALE = (
    REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "quality_scale.yaml"
)
ICON = REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "brand" / "icon.png"
LOGO = REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "brand" / "logo.png"

BRONZE_RULES = {
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-triggers",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
}
SILVER_RULES = {
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
}
GOLD_RULES = {
    "devices",
    "diagnostics",
    "discovery-update-info",
    "discovery",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
}
PLATINUM_RULES = {
    "async-dependency",
    "inject-websession",
    "strict-typing",
}
ALL_RULES = BRONZE_RULES | SILVER_RULES | GOLD_RULES | PLATINUM_RULES


class DistributionMetadataTests(unittest.TestCase):
    def test_manifest_links_install_docs_and_issue_tracker(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["documentation"],
            "https://github.com/teh-hippo/haos-mobile-wan#optional-home-assistant-integration",
        )
        self.assertEqual(
            manifest["issue_tracker"],
            "https://github.com/teh-hippo/haos-mobile-wan/issues",
        )
        self.assertEqual(
            manifest["loggers"],
            ["custom_components.ha_cellular_gateway"],
        )
        self.assertNotIn("single_config_entry", manifest)

    def test_hacs_metadata_uses_minimal_supported_layout(self) -> None:
        metadata = json.loads(HACS.read_text(encoding="utf-8"))
        self.assertEqual(
            metadata,
            {
                "name": "HAOS Mobile WAN",
                "content_in_root": False,
            },
        )

    def test_brand_assets_exist_and_are_pngs(self) -> None:
        for path in (ICON, LOGO):
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 8)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_quality_scale_covers_every_current_rule(self) -> None:
        quality_scale = yaml.safe_load(QUALITY_SCALE.read_text(encoding="utf-8"))
        rules = quality_scale["rules"]
        self.assertEqual(set(rules), ALL_RULES)
        for rule in ALL_RULES:
            self.assertIn(rules[rule]["status"], {"done", "exempt"})
            self.assertTrue(rules[rule]["comment"])

    def test_quality_scale_states_no_formal_core_tier_claim(self) -> None:
        text = QUALITY_SCALE.read_text(encoding="utf-8")
        self.assertIn("not a formal Home Assistant Core Platinum", text)

    def test_readme_covers_distribution_docs_scope(self) -> None:
        text = README.read_text(encoding="utf-8")
        for heading in (
            "## Install the HAOS app",
            "## Remove the HAOS app",
            "## Optional Home Assistant integration",
            "### Install the optional Home Assistant integration",
            "### Remove the optional Home Assistant integration",
            "### Entity reference",
            "### Control reference",
            "### Function reference",
            "### Update behaviour",
            "### Use cases",
            "### Automation examples",
            "### Supported hardware",
            "### Unsupported hardware",
            "### Limitations",
            "### Repairs",
            "### Diagnostics",
            "### Troubleshooting",
        ):
            self.assertIn(heading, text)

    def test_readme_documents_actual_entities_and_controls(self) -> None:
        text = README.read_text(encoding="utf-8")
        for table_row in (
            "| Upstream healthy | `binary_sensor` |",
            "| Downstream interface present | `binary_sensor` |",
            "| Gateway rules applied | `binary_sensor` |",
            "| DHCP server running | `binary_sensor` |",
            "| Safety checks | `binary_sensor` |",
            "| Mobile connection | `sensor` |",
            "| Active connection | `sensor` |",
            "| USB pairing | `sensor` |",
            "| Public IP | `sensor` |",
            "| Enabled | `switch` |",
            "| Reapply gateway state | `button` |",
        ):
            self.assertIn(table_row, text)
        self.assertIn("every 30 seconds", text)

    def test_readme_uses_human_fallback_wan_language(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("provide a fallback Internet connection", text)
        self.assertIn("to your router during a fixed-line outage", text)
        self.assertIn("- a phone Wi-Fi hotspot;", text)
        self.assertIn("- iPhone USB tethering;", text)
        self.assertIn("- automatic USB-preferred Wi-Fi fallback;", text)
        self.assertNotIn("It does not know about or control", text)
        self.assertNotIn("The router only needs a WAN Ethernet port", text)
        self.assertNotIn("## Architecture", text)
        self.assertNotIn("## Network roles", text)

    def test_readme_keeps_ci_as_source_of_truth(self) -> None:
        text = README.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "[`.github/workflows/validate.yml`](.github/workflows/validate.yml)",
            text,
        )
        for snippet in (
            "python -m unittest discover -s ha_cellular_gateway/tests -v",
            'python -c "import app.main"',
        ):
            self.assertIn(snippet, text)
        for snippet in (
            "--cov-report=json",
            "coverage.json",
            "Each integration module must exceed",
            'python -c "import app.main"',
            'python -m mypy --config-file mypy.ini',
            'custom_components/ha_cellular_gateway/strings.json',
            "strings == runtime_translations",
            "apparmor_parser -QK ha_cellular_gateway/apparmor.txt",
            "docker buildx build",
        ):
            self.assertIn(snippet, workflow)


if __name__ == "__main__":
    unittest.main()

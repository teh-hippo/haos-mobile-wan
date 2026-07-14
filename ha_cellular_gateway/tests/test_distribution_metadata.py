import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
MANIFEST = REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "manifest.json"
HACS = REPO_ROOT / "hacs.json"
QUALITY_SCALE = (
    REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "quality_scale.yaml"
)
ICON = REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "icon.png"
LOGO = REPO_ROOT / "custom_components" / "ha_cellular_gateway" / "logo.png"


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

    def test_hacs_metadata_targets_optional_integration(self) -> None:
        metadata = json.loads(HACS.read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "HAOS Mobile WAN")
        self.assertEqual(metadata["domains"], ["ha_cellular_gateway"])
        self.assertFalse(metadata["content_in_root"])

    def test_quality_scale_lists_current_rules(self) -> None:
        text = QUALITY_SCALE.read_text(encoding="utf-8")
        for rule in (
            "docs-installation-instructions",
            "docs-removal-instructions",
            "docs-supported-functions",
            "docs-troubleshooting",
            "strict-typing",
        ):
            self.assertIn(rule, text)

    def test_brand_assets_exist(self) -> None:
        self.assertTrue(ICON.exists())
        self.assertTrue(LOGO.exists())

    def test_readme_covers_distribution_docs_scope(self) -> None:
        text = README.read_text(encoding="utf-8")
        for heading in (
            "## Install the HAOS app",
            "## Optional Home Assistant integration",
            "### Install the optional Home Assistant integration",
            "### Remove the optional Home Assistant integration",
            "### Entity reference",
            "### Function reference",
            "### Update behaviour",
            "### Use cases",
            "### Automation examples",
            "### Supported hardware",
            "### Unsupported hardware",
            "### Limitations",
            "### Troubleshooting",
        ):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "ha_cellular_gateway" / "DOCS.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
CONFIG = REPO_ROOT / "ha_cellular_gateway" / "config.yaml"


class DistributionMetadataTests(unittest.TestCase):
    def test_addon_config_uses_mqtt_service_without_supervisor_discovery(self) -> None:
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.assertIn("mqtt:need", config["services"])
        self.assertNotIn("discovery", config)

    def test_readme_covers_distribution_docs_scope(self) -> None:
        text = README.read_text(encoding="utf-8")
        for heading in (
            "## Install the HAOS app",
            "## Remove the HAOS app",
            "## Home Assistant entities (MQTT)",
            "### Entity reference",
            "### Control reference",
            "### Use cases",
            "### Automation examples",
            "### Supported hardware",
            "### Unsupported hardware",
            "### Limitations",
            "### Diagnostics",
            "### Troubleshooting",
        ):
            self.assertIn(heading, text)
        self.assertNotIn("## Optional Home Assistant integration", text)
        self.assertNotIn("HACS", text)

    def test_readme_documents_status_only_entities(self) -> None:
        text = README.read_text(encoding="utf-8")
        for table_row in (
            "| Gateway enabled | `binary_sensor` |",
            "| Internet available | `binary_sensor` |",
            "| Downstream interface present | `binary_sensor` |",
            "| Gateway rules applied | `binary_sensor` |",
            "| DHCP server running | `binary_sensor` |",
            "| Gateway state | `sensor` |",
            "| Health | `sensor` |",
            "| Connection method | `sensor` |",
            "| Connected via | `sensor` |",
            "| iPhone USB pairing | `sensor` |",
            "| Public IP | `sensor` |",
        ):
            self.assertIn(table_row, text)
        self.assertIn("MQTT discovery", text)
        self.assertIn("status-only", text)
        self.assertNotIn("| `switch` |", text)
        self.assertNotIn("| `select` |", text)
        self.assertNotIn("| `button` |", text)

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

    def test_docs_describe_mqtt_entities_section(self) -> None:
        text = DOCS.read_text(encoding="utf-8")
        self.assertIn("## Home Assistant entities (MQTT)", text)
        self.assertNotIn("## Optional Home Assistant integration", text)

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
            "python -m unittest discover -s ha_cellular_gateway/tests -v",
            'python -c "import app.main"',
            "apparmor_parser -QK ha_cellular_gateway/apparmor.txt",
            "docker buildx build",
        ):
            self.assertIn(snippet, workflow)
        for absent in (
            "custom_components",
            "--cov-report=json",
            "strings == runtime_translations",
            "python -m mypy",
        ):
            self.assertNotIn(absent, workflow)


if __name__ == "__main__":
    unittest.main()

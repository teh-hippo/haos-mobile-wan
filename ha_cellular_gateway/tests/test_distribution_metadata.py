from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "ha_cellular_gateway"
README = REPO_ROOT / "README.md"
DOCS = APP_DIR / "DOCS.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
CONFIG = APP_DIR / "config.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PYTHON_VERSION = REPO_ROOT / ".python-version"


class DistributionMetadataTests(unittest.TestCase):
    def test_addon_config_uses_mqtt_service_without_supervisor_discovery(self) -> None:
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["name"], "Mobile WAN")
        self.assertIn("mqtt:need", config["services"])
        self.assertNotIn("discovery", config)

    def test_addon_includes_native_artwork(self) -> None:
        for name in ("icon.svg", "logo.svg"):
            text = (APP_DIR / name).read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("<title>Mobile WAN</title>", text)
        for name in ("icon.png", "logo.png"):
            self.assertEqual((APP_DIR / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

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
            "## Pre-1.0 live acceptance",
        ):
            self.assertIn(heading, text)
        self.assertNotIn("## Optional Home Assistant integration", text)
        self.assertNotIn("HACS", text)

    def test_readme_documents_status_only_entities(self) -> None:
        text = README.read_text(encoding="utf-8")
        for table_row in (
            "| Internet available | `binary_sensor` |",
            "| Downstream interface present | `binary_sensor` |",
            "| Gateway rules applied | `binary_sensor` |",
            "| DHCP server running | `binary_sensor` |",
            "| Gateway state | `sensor` |",
            "| Health | `sensor` |",
            "| Connection method | `sensor` |",
            "| Connected via | `sensor` |",
            "| USB status | `sensor` |",
            "| Public IP | `sensor` |",
        ):
            self.assertIn(table_row, text)
        self.assertNotIn("Gateway enabled", text)
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
        self.assertIn(
            "- generic Android RNDIS, CDC and Ethernet-style USB tethering;", text
        )
        self.assertIn("- automatic USB-preferred Wi-Fi fallback;", text)
        self.assertNotIn("It does not know about or control", text)
        self.assertNotIn("The router only needs a WAN Ethernet port", text)
        self.assertNotIn("## Architecture", text)
        self.assertNotIn("## Network roles", text)

    def test_docs_describe_mqtt_entities_section(self) -> None:
        text = DOCS.read_text(encoding="utf-8")
        self.assertIn("## Home Assistant entities (MQTT)", text)
        self.assertNotIn("## Optional Home Assistant integration", text)
        for obsolete in (
            "## Prepare HAOS networking",
            "ha network update",
            "## Upgrade to 0.9.0",
            "## Upgrade to 0.4.0",
            "    name: Connection method",
        ):
            self.assertNotIn(obsolete, text)

    def test_docs_describe_interrupted_shutdown_repair(self) -> None:
        readme = README.read_text(encoding="utf-8")
        docs = DOCS.read_text(encoding="utf-8")
        self.assertIn(
            "Restart the add-on to run startup cleanup",
            readme,
        )
        self.assertIn(
            "Startup cleanup runs before new gateway state is applied",
            docs,
        )
        self.assertIn(
            "wait for the first reconciliation, then stop it",
            docs,
        )

    def test_readme_keeps_ci_as_source_of_truth(self) -> None:
        text = README.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "[`.github/workflows/validate.yml`](.github/workflows/validate.yml)",
            text,
        )
        for snippet in (
            "uv sync --frozen",
            "uv run coverage run -m unittest discover",
            "uv run ruff check .",
            "uv run mypy ha_cellular_gateway/rootfs/app tools",
            "uv run python tools/structure_contract.py",
            'uv run python -c "import app.main"',
        ):
            self.assertIn(snippet, text)
        for snippet in (
            "uv run coverage run -m unittest discover",
            "uv run ruff format --check .",
            "uv run mypy ha_cellular_gateway/rootfs/app tools",
            "uv run python tools/structure_contract.py",
            'uv run python -c "import app.main"',
            "apparmor_parser -QK ha_cellular_gateway/apparmor.txt",
            "docker buildx build",
        ):
            self.assertIn(snippet, workflow)
        for absent in (
            "custom_components",
            "--cov-report=json",
            "strings == runtime_translations",
        ):
            self.assertNotIn(absent, workflow)

    def test_python_compatibility_floor_is_consistent(self) -> None:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(PYTHON_VERSION.read_text(encoding="utf-8").strip(), "3.13")
        self.assertEqual(project["project"]["requires-python"], ">=3.13")
        self.assertEqual(project["tool"]["ruff"]["target-version"], "py313")
        self.assertEqual(project["tool"]["mypy"]["python_version"], "3.13")
        self.assertEqual(workflow.count('python-version: "3.13"'), 3)


if __name__ == "__main__":
    unittest.main()

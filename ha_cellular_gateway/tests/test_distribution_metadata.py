from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "ha_cellular_gateway"
README = REPO_ROOT / "README.md"
DOCS = APP_DIR / "DOCS.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
BUILDER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "builder.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RENOVATE = REPO_ROOT / "renovate.json"
NM_INTEGRATION_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "networkmanager-integration.yml"
)
NM_WIFI_INTEGRATION_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "networkmanager-wifi-integration.yml"
)
CONFIG = APP_DIR / "config.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PYTHON_VERSION = REPO_ROOT / ".python-version"


class DistributionMetadataTests(unittest.TestCase):
    def test_addon_config_uses_mqtt_service_without_supervisor_discovery(self) -> None:
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["name"], "Mobile WAN")
        self.assertEqual(config["image"], "ghcr.io/teh-hippo/haos-mobile-wan")
        self.assertIn("mqtt:need", config["services"])
        self.assertNotIn("discovery", config)

    def test_builder_publishes_and_verifies_signed_image(self) -> None:
        workflow = BUILDER_WORKFLOW.read_text(encoding="utf-8")
        for snippet in (
            "home-assistant/builder/actions/build-image@",
            "home-assistant/builder/actions/publish-multi-arch-manifest@",
            "home-assistant/builder/actions/cosign-verify@",
            "published-image-ok",
        ):
            self.assertIn(snippet, workflow)

    def test_builder_publishes_only_when_app_version_changes(self) -> None:
        workflow = BUILDER_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Determine whether to publish", workflow)
        self.assertIn("previous_version=", workflow)
        self.assertIn("push: ${{ needs.init.outputs.publish }}", workflow)
        self.assertIn("if: needs.init.outputs.publish == 'true'", workflow)
        self.assertIn("- beta", workflow)
        self.assertIn('if [ "$REF_NAME" = main ]; then', workflow)
        self.assertIn("image-tags: ${{ needs.init.outputs.tags }}", workflow)
        self.assertNotIn("- pyproject.toml", workflow)
        self.assertNotIn("- uv.lock", workflow)

    def test_renovate_keeps_the_supported_python_floor(self) -> None:
        config = json.loads(RENOVATE.read_text(encoding="utf-8"))
        matching = [
            rule
            for rule in config["packageRules"]
            if ".python-version" in rule.get("matchFileNames", [])
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["matchPackageNames"], ["python"])
        self.assertEqual(matching[0]["allowedVersions"], "3.13")

    def test_integration_labs_are_reusable_and_scheduled(self) -> None:
        nm_workflow = NM_INTEGRATION_WORKFLOW.read_text(encoding="utf-8")
        wifi_workflow = NM_WIFI_INTEGRATION_WORKFLOW.read_text(encoding="utf-8")
        for workflow in (nm_workflow, wifi_workflow):
            self.assertIn("workflow_call:", workflow)
            self.assertIn("workflow_dispatch:", workflow)
            self.assertIn("schedule:", workflow)
            self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("pull_request:", nm_workflow)
        self.assertNotIn("pull_request:", wifi_workflow)

    def test_release_workflow_is_manual_and_gates_each_channel(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        for snippet in (
            "workflow_dispatch:",
            "channel:",
            "version:",
            "acceptance_reference:",
            "Require matching release branch",
            "refs/heads/main",
            "refs/heads/beta",
            "Beta releases require a -beta.N version",
            "Stable releases require an acceptance reference",
            "prerelease",
            "release",
        ):
            self.assertIn(snippet, workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)

    def test_release_workflow_calls_integration_labs_at_exact_commit(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "uses: ./.github/workflows/networkmanager-integration.yml", workflow
        )
        self.assertIn(
            "uses: ./.github/workflows/networkmanager-wifi-integration.yml",
            workflow,
        )

    def test_release_workflow_verifies_exact_sha_and_signed_image(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        for snippet in (
            "workflows/builder.yml/runs?head_sha=",
            "workflows/validate.yml/runs?head_sha=",
            "home-assistant/builder/actions/cosign-verify@",
            "haos-mobile-wan-sbom-${{ github.sha }}",
            "tools/release_notes.py",
            "ACCEPTANCE_REFERENCE",
            "gh release create",
            "--prerelease",
            "--target",
        ):
            self.assertIn(snippet, workflow)
        self.assertNotIn("--generate-notes", workflow)

    def test_release_workflow_final_job_has_minimal_permissions(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        release_job = workflow.split("  release:", 1)[1]
        permissions_block = release_job.split("permissions:", 1)[1].split("env:", 1)[0]
        self.assertIn("contents: write", permissions_block)
        self.assertIn("actions: read", permissions_block)
        self.assertNotIn("packages: read", permissions_block)
        self.assertIn("packages: read", workflow.split("  candidate:", 1)[1])

    def test_readme_documents_release_process_as_source_of_truth(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn(
            "[`.github/workflows/release.yml`](.github/workflows/release.yml)",
            text,
        )
        for snippet in (
            "tools/release_notes.py",
            "acceptance_reference",
            "beta",
            "release",
            "v<version>",
        ):
            self.assertIn(snippet, text)

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
            "uv run ruff check --select C901",
            "uv run mypy ha_cellular_gateway/rootfs/app tools",
            "uv run python tools/structure_contract.py",
            'uv run python -c "import app.main"',
            "Home Assistant app linting",
            "HIGH/CRITICAL vulnerability scanning",
            "full-image SBOM",
        ):
            self.assertIn(snippet, text)
        for snippet in (
            "uv run coverage run -m unittest discover",
            "uv run ruff format --check .",
            "uv run ruff check --select C901",
            "uv run mypy ha_cellular_gateway/rootfs/app tools",
            "uv run python tools/structure_contract.py",
            'uv run python -c "import app.main"',
            "frenck/action-addon-linter@",
            "aquasecurity/trivy-action@",
            "trivy-sbom.cdx.json",
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
        self.assertGreaterEqual(
            project["tool"]["coverage"]["report"]["fail_under"],
            95,
        )
        self.assertEqual(workflow.count('python-version: "3.13"'), 3)


if __name__ == "__main__":
    unittest.main()

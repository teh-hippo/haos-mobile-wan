from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "ha_cellular_gateway"
CONFIG = APP_DIR / "config.yaml"
DOCS = APP_DIR / "DOCS.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PYTHON_VERSION = REPO_ROOT / ".python-version"
RENOVATE = REPO_ROOT / "renovate.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
BUILDER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "builder.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
NM_INTEGRATION_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "networkmanager-integration.yml"
)
NM_WIFI_INTEGRATION_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "networkmanager-wifi-integration.yml"
)


def dashboard_example() -> dict[str, object]:
    section = DOCS.read_text(encoding="utf-8").split(
        "### Dashboard example",
        1,
    )[1]
    block = section.split("```yaml", 1)[1].split("```", 1)[0]
    payload = yaml.safe_load(block)
    if not isinstance(payload, dict):
        raise AssertionError("dashboard example must be a YAML object")
    return payload


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
            "Determine whether to publish",
            "previous_version=",
            "push: ${{ needs.init.outputs.publish }}",
            "if: needs.init.outputs.publish == 'true'",
            "image-tags: ${{ needs.init.outputs.tags }}",
        ):
            self.assertIn(snippet, workflow)
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

    def test_integration_labs_remain_reusable_release_gates(self) -> None:
        nm_workflow = NM_INTEGRATION_WORKFLOW.read_text(encoding="utf-8")
        wifi_workflow = NM_WIFI_INTEGRATION_WORKFLOW.read_text(encoding="utf-8")
        for workflow in (nm_workflow, wifi_workflow):
            self.assertIn("workflow_call:", workflow)
            self.assertIn("workflow_dispatch:", workflow)
            self.assertIn("schedule:", workflow)
            self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("pull_request:", nm_workflow)
        self.assertNotIn("pull_request:", wifi_workflow)

        release = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "uses: ./.github/workflows/networkmanager-integration.yml",
            release,
        )
        self.assertIn(
            "uses: ./.github/workflows/networkmanager-wifi-integration.yml",
            release,
        )

    def test_release_workflow_preserves_integrity_gates(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        for snippet in (
            "workflow_dispatch:",
            "acceptance_reference:",
            "Require matching release branch",
            "refs/heads/main",
            "refs/heads/beta",
            "uv run python -m tools.release_dispatch",
            "workflows/builder.yml/runs?head_sha=",
            "workflows/validate.yml/runs?head_sha=",
            "home-assistant/builder/actions/cosign-verify@",
            "haos-mobile-wan-sbom-${{ github.sha }}",
            "uv run python -m tools.release_notes",
            "gh release create",
            "--prerelease",
            "--target",
        ):
            self.assertIn(snippet, workflow)
        self.assertNotIn("--generate-notes", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)

        release_job = workflow.split("  release:", 1)[1]
        permissions = release_job.split("permissions:", 1)[1].split("env:", 1)[0]
        self.assertIn("contents: write", permissions)
        self.assertIn("actions: read", permissions)
        self.assertNotIn("packages: read", permissions)
        self.assertIn("packages: read", workflow.split("  candidate:", 1)[1])

    def test_validation_workflow_keeps_required_gates(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for snippet in (
            "uv run coverage run -m unittest discover",
            "uv run ruff format --check .",
            "uv run ruff check --select C901",
            "uv run mypy ha_cellular_gateway/rootfs/app tools",
            "uv run python -m tools.distribution_contract",
            'uv run python -c "import app.main"',
            "frenck/action-addon-linter@",
            "aquasecurity/trivy-action@",
            "trivy-sbom.cdx.json",
            "apparmor_parser -QK ha_cellular_gateway/apparmor.txt",
            "docker buildx build",
        ):
            self.assertIn(snippet, workflow)

    def test_dashboard_example_contains_start_and_stop_actions(self) -> None:
        example = dashboard_example()
        self.assertEqual(example["type"], "vertical-stack")
        cards = example["cards"]
        self.assertIsInstance(cards, list)
        assert isinstance(cards, list)
        self.assertEqual(len(cards), 2)
        self.assertEqual(
            cards[0]["conditions"][0]["state_not"],
            ["unavailable", "unknown"],
        )
        self.assertEqual(
            cards[1]["conditions"][0]["state"],
            ["unavailable", "unknown"],
        )
        actions = [card["card"]["entities"][-1]["tap_action"] for card in cards]
        self.assertEqual(
            [action["perform_action"] for action in actions],
            ["hassio.addon_stop", "hassio.addon_start"],
        )
        self.assertEqual(
            [action["data"]["addon"] for action in actions],
            ["YOUR_ADDON_SLUG", "YOUR_ADDON_SLUG"],
        )

    def test_addon_includes_native_artwork(self) -> None:
        for name in ("icon.svg", "logo.svg"):
            text = (APP_DIR / name).read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("<title>Mobile WAN</title>", text)
        for name in ("icon.png", "logo.png"):
            self.assertEqual((APP_DIR / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_python_compatibility_floor_is_consistent(self) -> None:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(PYTHON_VERSION.read_text(encoding="utf-8").strip(), "3.13")
        self.assertEqual(project["project"]["requires-python"], ">=3.13")
        self.assertEqual(project["tool"]["ruff"]["target-version"], "py313")
        self.assertEqual(project["tool"]["mypy"]["python_version"], "3.13")
        self.assertGreaterEqual(
            project["tool"]["coverage"]["report"]["fail_under"],
            95.5,
        )
        self.assertEqual(workflow.count('python-version: "3.13"'), 3)


if __name__ == "__main__":
    unittest.main()

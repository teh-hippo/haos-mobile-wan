import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised in CI
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[2]
ADDON_DOCKERFILE = REPO_ROOT / "ha_cellular_gateway" / "Dockerfile"
LAB_DIR = REPO_ROOT / "ha_cellular_gateway" / "integration" / "networkmanager"


@unittest.skipIf(yaml is None, "pyyaml is required for integration lab checks")
class NetworkManagerIntegrationTests(unittest.TestCase):
    def test_lab_uses_the_addon_alpine_base_and_nmcli_family(self) -> None:
        addon = ADDON_DOCKERFILE.read_text(encoding="utf-8")
        lab = (LAB_DIR / "Dockerfile").read_text(encoding="utf-8")
        addon_base = re.search(r"^FROM (.+)$", addon, re.MULTILINE)

        self.assertIsNotNone(addon_base)
        assert addon_base is not None
        self.assertIn(
            f"ARG ADDON_BASE_IMAGE={addon_base.group(1)}",
            lab,
        )
        self.assertIn("networkmanager-cli", lab)
        self.assertIn("\n    networkmanager \\", lab)
        self.assertIn("COPY rootfs /", lab)
        self.assertIn(
            "COPY integration/networkmanager/nmcli_harness.py /integration/nmcli_harness.py",
            lab,
        )

    def test_compose_lab_is_single_service_and_host_isolated(self) -> None:
        compose = yaml.safe_load((LAB_DIR / "compose.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(compose["services"]), {"networkmanager"})
        service = compose["services"]["networkmanager"]
        self.assertEqual(service["network_mode"], "none")
        self.assertEqual(service["cap_add"], ["NET_ADMIN", "NET_RAW"])
        self.assertNotIn("privileged", service)
        self.assertNotIn("volumes", service)
        self.assertNotIn("ports", service)

    def test_lab_configuration_and_runner_stay_rootful_and_manual(self) -> None:
        config = (LAB_DIR / "nm.conf").read_text(encoding="utf-8")
        entrypoint = (LAB_DIR / "entrypoint.sh").read_text(encoding="utf-8")
        livetest = (LAB_DIR / "test_live_nm.py").read_text(encoding="utf-8")
        runner = (LAB_DIR / "run.sh").read_text(encoding="utf-8")
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "networkmanager-integration.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("plugins=keyfile", config)
        # HAOS does not set no-auto-default; neither may the lab, or its
        # realisation-gate controls would be masked and pass vacuously.
        self.assertNotIn("no-auto-default", config)
        self.assertIn("unmanaged-devices=interface-name:phone0", config)
        # NetworkManager starts before any test veth; the test realises the
        # carrier-up device itself after installing the intended profile.
        self.assertNotIn(
            'ip link add "$NM_DEVICE" type veth peer name "$PHONE_DEVICE"',
            entrypoint,
        )
        self.assertIn("NetworkManager --no-daemon", entrypoint)
        self.assertIn("python3 /integration/test_live_nm.py", entrypoint)
        self.assertIn(
            '"ip", "link", "add", DEVICE, "type", "veth"',
            livetest,
        )
        self.assertIn("trap cleanup EXIT INT TERM", entrypoint)
        self.assertIn("Rootful Docker", runner)
        self.assertIn("rootless Docker and Podman are not supported", runner)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("timeout-minutes: 15", workflow)

    def test_veth_virtualisation_is_documented_as_read_only(self) -> None:
        readme = (LAB_DIR / "README.md").read_text(encoding="utf-8")

        self.assertIn("synthesises only an enabled radio read", readme)
        self.assertIn("deterministic\nveth identity", readme)
        self.assertIn("All ownership mutations and every other\nread", readme)


if __name__ == "__main__":
    unittest.main()

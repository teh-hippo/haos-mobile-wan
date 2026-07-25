from __future__ import annotations

import unittest
from pathlib import Path

from tools import app_metadata, distribution_contract, release_dispatch
from tools.distribution_contract import (
    app_errors,
    image_errors,
    profile_errors,
    serialisation_errors,
    violations,
)
from tools.release_dispatch import (
    ACCEPTANCE_REQUIRED,
    BETA_REQUIRED,
    STABLE_REJECTS_BETA,
    dispatch_errors,
)

REPO = Path(__file__).resolve().parents[2]
VALID_APP: dict[str, object] = {
    "arch": ["aarch64"],
    "host_network": True,
    "host_dbus": True,
    "hassio_api": True,
    "hassio_role": "manager",
    "usb": True,
    "privileged": ["NET_ADMIN", "NET_RAW"],
}


class DistributionContractTests(unittest.TestCase):
    def test_the_shipped_repository_satisfies_the_contract(self) -> None:
        self.assertEqual(violations(REPO), [])

    def test_widened_privileges_are_rejected(self) -> None:
        app = VALID_APP | {"privileged": ["NET_ADMIN", "NET_RAW", "SYS_ADMIN"]}
        self.assertTrue(any("privileged" in error for error in app_errors(app)))

    def test_full_access_must_stay_off(self) -> None:
        self.assertEqual(app_errors(VALID_APP | {"full_access": False}), [])
        self.assertTrue(app_errors(VALID_APP | {"full_access": True}))

    def test_a_managed_apparmor_profile_is_rejected(self) -> None:
        self.assertTrue(app_errors(VALID_APP | {"apparmor": "profile"}))

    def test_missing_capability_is_reported(self) -> None:
        errors = profile_errors("capability net_admin,\n")
        self.assertTrue(any("net_raw" in error for error in errors))

    def test_broad_globs_are_rejected(self) -> None:
        profile = (REPO / "ha_cellular_gateway" / "apparmor.txt").read_text(
            encoding="utf-8"
        )
        self.assertEqual(profile_errors(profile), [])
        self.assertTrue(profile_errors(profile + "\n  /proc/** r,\n"))

    def test_complain_mode_is_rejected(self) -> None:
        self.assertTrue(profile_errors("complain"))

    def test_the_base_image_must_stay_pinned(self) -> None:
        self.assertEqual(image_errors("FROM ghcr.io/home-assistant/base:3.24@sha"), [])
        self.assertTrue(image_errors("ARG BUILD_FROM\nFROM ${BUILD_FROM}"))
        self.assertTrue(image_errors("FROM alpine:3.20"))

    def test_malformed_serialisation_is_reported(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.json").write_text("{", encoding="utf-8")
            errors = serialisation_errors(root)

        self.assertTrue(any("broken.json" in error for error in errors))


class AppMetadataTests(unittest.TestCase):
    def test_version_matches_the_published_config(self) -> None:
        declared = app_metadata.config()["version"]
        self.assertEqual(app_metadata.version(), declared)

    def test_a_missing_version_is_reported(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("name: example\n", encoding="utf-8")
            with self.assertRaises(app_metadata.MetadataError):
                app_metadata.version(path)


class ReleaseDispatchTests(unittest.TestCase):
    def test_matching_stable_inputs_are_accepted(self) -> None:
        self.assertEqual(
            dispatch_errors(
                channel="stable",
                requested="1.2.3",
                acceptance_reference="https://example.invalid/run",
                declared="1.2.3",
            ),
            [],
        )

    def test_stable_requires_acceptance_evidence(self) -> None:
        errors = dispatch_errors(
            channel="stable",
            requested="1.2.3",
            acceptance_reference="   ",
            declared="1.2.3",
        )
        self.assertIn(ACCEPTANCE_REQUIRED, errors)

    def test_stable_rejects_a_beta_version(self) -> None:
        errors = dispatch_errors(
            channel="stable",
            requested="1.2.3-beta.1",
            acceptance_reference="evidence",
            declared="1.2.3-beta.1",
        )
        self.assertIn(STABLE_REJECTS_BETA, errors)

    def test_beta_requires_a_beta_version(self) -> None:
        errors = dispatch_errors(
            channel="beta",
            requested="1.2.3",
            acceptance_reference="",
            declared="1.2.3",
        )
        self.assertIn(BETA_REQUIRED, errors)

    def test_beta_needs_no_acceptance_evidence(self) -> None:
        self.assertEqual(
            dispatch_errors(
                channel="beta",
                requested="1.2.3-beta.4",
                acceptance_reference="",
                declared="1.2.3-beta.4",
            ),
            [],
        )

    def test_a_version_that_disagrees_with_config_is_rejected(self) -> None:
        errors = dispatch_errors(
            channel="beta",
            requested="1.2.3-beta.4",
            acceptance_reference="",
            declared="1.2.2-beta.1",
        )
        self.assertTrue(any("does not match" in error for error in errors))

    def test_an_unparseable_version_is_reported_alone(self) -> None:
        errors = dispatch_errors(
            channel="beta",
            requested="not-a-version",
            acceptance_reference="",
            declared="1.2.3",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("Invalid semantic version", errors[0])

    def test_the_module_exposes_a_command_line_entry_point(self) -> None:
        self.assertTrue(callable(release_dispatch.main))
        self.assertTrue(callable(distribution_contract.main))


if __name__ == "__main__":
    unittest.main()

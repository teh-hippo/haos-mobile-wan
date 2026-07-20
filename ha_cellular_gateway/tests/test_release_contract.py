from __future__ import annotations

import unittest

from tools.release_contract import (
    ContractError,
    config_version,
    is_beta_version,
    is_release_file,
    parse_version,
    stable_release_errors,
    validate_contract,
)


class ReleaseContractTests(unittest.TestCase):
    def validate(
        self,
        *,
        base: str = "0.11.2",
        current: str = "0.11.2",
        changed: list[str] | None = None,
        changelog: str = "# Changelog\n",
        tags: set[str] | None = None,
    ) -> list[str]:
        return validate_contract(
            base_version=base,
            current_version=current,
            changed_files=changed or [],
            changelog=changelog,
            tags=tags or set(),
        )

    def test_release_payload_requires_version_increase(self) -> None:
        errors = self.validate(
            changed=["ha_cellular_gateway/rootfs/app/main.py"],
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("without increasing", errors[0])

    def test_release_version_requires_changelog_heading(self) -> None:
        errors = self.validate(
            current="0.11.3",
            changed=["ha_cellular_gateway/config.yaml"],
        )
        self.assertEqual(
            errors,
            ["ha_cellular_gateway/CHANGELOG.md needs a ## 0.11.3 heading"],
        )

    def test_valid_release_payload_change_passes(self) -> None:
        errors = self.validate(
            current="0.11.3",
            changed=[
                "ha_cellular_gateway/config.yaml",
                "ha_cellular_gateway/Dockerfile",
            ],
            changelog="# Changelog\n\n## 0.11.3\n",
        )
        self.assertEqual(errors, [])

    def test_existing_tag_cannot_be_reused(self) -> None:
        errors = self.validate(
            current="0.11.3",
            changed=["ha_cellular_gateway/config.yaml"],
            changelog="# Changelog\n\n## 0.11.3\n",
            tags={"v0.11.3"},
        )
        self.assertEqual(errors, ["Version v0.11.3 already has a Git tag"])

    def test_version_cannot_decrease(self) -> None:
        errors = self.validate(
            base="0.11.2",
            current="0.10.9",
            changed=["ha_cellular_gateway/config.yaml"],
        )
        self.assertEqual(
            errors,
            ["App version decreased from 0.11.2 to 0.10.9"],
        )

    def test_non_release_changes_do_not_require_a_version(self) -> None:
        errors = self.validate(
            changed=[
                "README.md",
                ".github/workflows/validate.yml",
                "ha_cellular_gateway/tests/test_gateway.py",
            ],
        )
        self.assertEqual(errors, [])

    def test_release_file_classification_is_explicit(self) -> None:
        self.assertTrue(is_release_file("ha_cellular_gateway/apparmor.txt"))
        self.assertTrue(is_release_file("ha_cellular_gateway/translations/en.yaml"))
        self.assertFalse(is_release_file("ha_cellular_gateway/integration/test_lab.py"))

    def test_config_version_requires_semver_string(self) -> None:
        self.assertEqual(config_version('version: "0.11.3"\n'), "0.11.3")
        self.assertTrue(is_beta_version("1.0.0-beta.1"))
        self.assertLess(
            parse_version("1.0.0-beta.1"),
            parse_version("1.0.0"),
        )
        self.assertGreater(
            parse_version("1.0.0-beta.2"),
            parse_version("1.0.0-beta.1"),
        )
        with self.assertRaises(ContractError):
            config_version("version: 12\n")
        with self.assertRaises(ContractError):
            parse_version("0.11")
        with self.assertRaises(ContractError):
            parse_version("1.0.0-rc.1")

    def test_pre_1_0_release_does_not_require_stable_metadata(self) -> None:
        self.assertEqual(
            stable_release_errors(
                {
                    "version": "0.12.0",
                    "stage": "experimental",
                }
            ),
            [],
        )

    def test_beta_release_does_not_require_stable_metadata(self) -> None:
        self.assertEqual(
            stable_release_errors(
                {
                    "version": "1.0.0-beta.1",
                    "stage": "experimental",
                    "image": "ghcr.io/teh-hippo/haos-mobile-wan",
                }
            ),
            [],
        )

    def test_stable_release_requires_stable_stage_and_signed_image(self) -> None:
        self.assertEqual(
            stable_release_errors(
                {
                    "version": "1.0.0",
                    "stage": "experimental",
                }
            ),
            [
                "Stable releases require stage: stable",
                "Stable releases require image: ghcr.io/teh-hippo/haos-mobile-wan",
            ],
        )
        self.assertEqual(
            stable_release_errors(
                {
                    "version": "1.0.0",
                    "stage": "stable",
                    "image": "ghcr.io/teh-hippo/haos-mobile-wan",
                }
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

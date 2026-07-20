from __future__ import annotations

import unittest

from tools.release_contract import (
    ContractError,
    config_version,
    is_release_file,
    parse_version,
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
        self.assertTrue(
            is_release_file("ha_cellular_gateway/translations/en.yaml")
        )
        self.assertFalse(
            is_release_file("ha_cellular_gateway/integration/test_lab.py")
        )

    def test_config_version_requires_semver_string(self) -> None:
        self.assertEqual(config_version('version: "0.11.3"\n'), "0.11.3")
        with self.assertRaises(ContractError):
            config_version("version: 12\n")
        with self.assertRaises(ContractError):
            parse_version("0.11")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from tools.release_notes import ReleaseNotesError, extract_section

CHANGELOG = """# Changelog

## 0.12.0

- Publish signed, pre-built aarch64 images to GHCR.
- Verify the published Cosign signature before release.

## 0.11.6

- Adopt the Home Assistant app linter's canonical metadata.
- Add required Home Assistant metadata linting.
"""


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_exact_heading_section(self) -> None:
        section = extract_section(CHANGELOG, "0.12.0")
        self.assertEqual(
            section,
            "- Publish signed, pre-built aarch64 images to GHCR.\n"
            "- Verify the published Cosign signature before release.",
        )

    def test_missing_version_raises(self) -> None:
        with self.assertRaises(ReleaseNotesError) as context:
            extract_section(CHANGELOG, "9.9.9")
        self.assertIn("## 9.9.9", str(context.exception))

    def test_stops_at_next_heading(self) -> None:
        section = extract_section(CHANGELOG, "0.11.6")
        self.assertNotIn("0.12.0", section)
        self.assertIn("Add required Home Assistant metadata linting.", section)

    def test_does_not_match_a_version_that_is_only_a_prefix(self) -> None:
        with self.assertRaises(ReleaseNotesError):
            extract_section(CHANGELOG, "0.12")

    def test_last_section_extends_to_end_of_file(self) -> None:
        changelog = "# Changelog\n\n## 1.0.0\n\n- Only entry.\n"
        section = extract_section(changelog, "1.0.0")
        self.assertEqual(section, "- Only entry.")


if __name__ == "__main__":
    unittest.main()

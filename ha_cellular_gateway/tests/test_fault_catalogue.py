from __future__ import annotations

import unittest
from pathlib import Path

from rootfs.app.faults import FaultSpec
from rootfs.app.status_issues import FAULTS

RUNTIME = Path(__file__).resolve().parents[1] / "rootfs" / "app"
CATALOGUE_PREFIXES = ("fault_", "status_", "faults")


def producer_sources() -> list[Path]:
    return [
        path
        for path in sorted(RUNTIME.glob("*.py"))
        if not path.name.startswith(CATALOGUE_PREFIXES)
    ]


class CatalogueOwnershipTests(unittest.TestCase):
    def test_reported_text_is_never_repeated_as_a_producer_literal(self) -> None:
        owned = {
            spec.template: spec.id
            for spec in FAULTS
            if spec.template and not spec.parameterised
        }
        for path in producer_sources():
            source = path.read_text(encoding="utf-8")
            for template, issue_id in owned.items():
                with self.subTest(module=path.name, issue=issue_id):
                    self.assertNotIn(
                        f'"{template}"',
                        source,
                        f"{path.name} repeats text owned by {issue_id}; "
                        "render it through the catalogue instead",
                    )

    def test_every_fault_is_reachable_by_the_text_it_describes(self) -> None:
        for spec in FAULTS:
            if not spec.template or spec.parameterised:
                continue
            with self.subTest(issue=spec.id):
                self.assertTrue(spec.matches(spec.text))

    def test_identifiers_and_texts_are_unique(self) -> None:
        templates = [spec.template for spec in FAULTS if spec.template]
        self.assertEqual(len(templates), len(set(templates)))

    def test_parameterised_faults_render_and_match_each_other(self) -> None:
        spec = FaultSpec(id="example", template="Broken on {interface} now")
        rendered = spec.render(interface="eth0")

        self.assertEqual(rendered, "Broken on eth0 now")
        self.assertTrue(spec.matches(rendered))
        self.assertFalse(spec.matches("Something else"))

    def test_a_parameterised_fault_refuses_a_plain_text_reading(self) -> None:
        spec = FaultSpec(id="example", template="Broken on {interface}")
        with self.assertRaisesRegex(ValueError, "needs values"):
            _ = spec.text

    def test_a_fault_must_have_text_before_its_first_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "no literal text"):
            FaultSpec(id="example", template="{interface} is broken")


if __name__ == "__main__":
    unittest.main()

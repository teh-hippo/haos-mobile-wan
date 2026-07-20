from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.structure_contract import BUDGETS, violations


class StructureContractTests(unittest.TestCase):
    def test_current_categories_have_distinct_budgets(self) -> None:
        budgets = {label: maximum for label, _path, _pattern, maximum in BUDGETS}
        self.assertEqual(budgets["runtime"], 250)
        self.assertEqual(budgets["unit test"], 400)
        self.assertEqual(budgets["NetworkManager lab"], 350)
        self.assertEqual(budgets["QEMU guest lab"], 300)

    def test_reports_only_files_over_their_category_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "ha_cellular_gateway" / "rootfs" / "app"
            app.mkdir(parents=True)
            (app / "valid.py").write_text("pass\n" * 250, encoding="utf-8")
            (app / "oversized.py").write_text("pass\n" * 251, encoding="utf-8")

            errors = violations(root)

        self.assertEqual(len(errors), 1)
        self.assertIn("oversized.py has 251 lines", errors[0])
        self.assertIn("runtime limit is 250", errors[0])


if __name__ == "__main__":
    unittest.main()

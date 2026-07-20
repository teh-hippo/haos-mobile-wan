"""Behavioural tests for :mod:`rootfs.app.api_token`."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from rootfs.app.api_token import load_or_create_token


class LoadOrCreateTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def _mode(self, path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    def test_creates_token_with_parent_dirs_and_locked_permissions(self) -> None:
        path = self.root / "nested" / "dir" / "token"

        token = load_or_create_token(path)

        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), token)
        self.assertGreater(len(token), 20)
        self.assertEqual(self._mode(path), 0o600)

    def test_two_freshly_created_tokens_are_not_equal(self) -> None:
        first = load_or_create_token(self.root / "a" / "token")
        second = load_or_create_token(self.root / "b" / "token")

        self.assertNotEqual(first, second)

    def test_reuses_existing_token_without_rewriting_it(self) -> None:
        path = self.root / "token"

        created = load_or_create_token(path)
        reloaded = load_or_create_token(path)

        self.assertEqual(created, reloaded)

    def test_existing_token_is_stripped_and_permissions_are_relocked(self) -> None:
        path = self.root / "token"
        path.write_text("  existing-token-value  \n", encoding="utf-8")
        path.chmod(0o644)

        token = load_or_create_token(path)

        self.assertEqual(token, "existing-token-value")
        self.assertEqual(self._mode(path), 0o600)

    @unittest.skipIf(os.geteuid() == 0, "root bypasses directory permissions")
    def test_unwritable_parent_directory_propagates_permission_error(self) -> None:
        locked_parent = self.root / "locked"
        locked_parent.mkdir(mode=0o500)
        self.addCleanup(locked_parent.chmod, 0o700)
        path = locked_parent / "sub" / "token"

        with self.assertRaises(PermissionError):
            load_or_create_token(path)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rootfs.app.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_auto_disable_state_persists_without_owned_network_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)

            store.save(
                owned=None,
                auto_disable={"deadline": 1900.0, "pending": True},
            )
            state, error = store.load()

        self.assertIsNone(error)
        self.assertEqual(
            state["auto_disable"],
            {"deadline": 1900.0, "pending": True},
        )

    def test_empty_state_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            store.save(owned={"downstream": "eth1"})

            store.save(owned=None, auto_disable=None)

            self.assertFalse(path.exists())

    def test_profile_journal_persists_without_gateway_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            profiles = {
                "phase": "acquiring",
                "owned": {"wifi_hotspot": "profile-uuid"},
            }

            store.save(owned=None, profiles=profiles)
            state, error = store.load()

        self.assertIsNone(error)
        self.assertEqual(state["profiles"], profiles)

    def test_management_identity_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)

            store.save(
                owned=None,
                management_interface="end0",
            )
            state, error = store.load()

        self.assertIsNone(error)
        self.assertEqual(state["management_interface"], "end0")


if __name__ == "__main__":
    unittest.main()

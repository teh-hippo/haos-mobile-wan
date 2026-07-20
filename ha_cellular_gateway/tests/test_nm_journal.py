"""Behavioural tests for :mod:`rootfs.app.nm_journal`."""

from __future__ import annotations

import unittest

from rootfs.app.nm_journal import NmOwnershipJournal
from rootfs.app.nm_profile_specs import usb_profile_spec

INVALID_MESSAGE = "Persistent NetworkManager profile ownership is invalid"


class LoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journal = NmOwnershipJournal()

    def _assert_unchanged(self) -> None:
        self.assertEqual(self.journal.phase, "disabled")
        self.assertEqual(self.journal.owned, {})

    def test_none_value_returns_none_and_keeps_defaults(self) -> None:
        self.assertIsNone(self.journal.load(None))
        self._assert_unchanged()

    def test_non_dict_value_is_invalid(self) -> None:
        self.assertEqual(self.journal.load("not-a-dict"), INVALID_MESSAGE)
        self._assert_unchanged()

    def test_legacy_flat_string_map_normalizes_to_active_phase(self) -> None:
        result = self.journal.load({"iphone_usb": "uuid-1234"})

        self.assertIsNone(result)
        self.assertEqual(self.journal.phase, "active")
        self.assertEqual(
            self.journal.owned,
            {"iphone_usb": {"uuid": "uuid-1234", "fingerprint": {}}},
        )

    def test_new_format_round_trip_copies_owned_entries(self) -> None:
        source_entry = {"uuid": "u1", "fingerprint": {"connection.uuid": "u1"}}
        value = {"phase": "reconciling", "owned": {"iphone_usb": source_entry}}

        result = self.journal.load(value)

        self.assertIsNone(result)
        self.assertEqual(self.journal.phase, "reconciling")
        self.assertEqual(self.journal.owned, {"iphone_usb": source_entry})
        self.assertIsNot(self.journal.owned["iphone_usb"], source_entry)

    def test_new_format_owned_not_a_dict_is_invalid(self) -> None:
        # A string "owned" value would satisfy the legacy flat-map shape (all
        # keys and values being strings), so use a non-string value to force
        # evaluation past that heuristic and into the new-format validation.
        result = self.journal.load({"phase": "active", "owned": ["nope"]})

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()

    def test_new_format_phase_not_a_string_is_invalid(self) -> None:
        result = self.journal.load({"phase": 7, "owned": {}})

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()

    def test_new_format_owned_entry_key_not_string_is_invalid(self) -> None:
        result = self.journal.load(
            {"phase": "active", "owned": {1: {"uuid": "u1", "fingerprint": {}}}}
        )

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()

    def test_new_format_owned_entry_value_not_dict_is_invalid(self) -> None:
        result = self.journal.load(
            {"phase": "active", "owned": {"iphone_usb": "not-a-dict"}}
        )

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()

    def test_new_format_owned_uuid_not_string_is_invalid(self) -> None:
        result = self.journal.load(
            {
                "phase": "active",
                "owned": {"iphone_usb": {"uuid": 123, "fingerprint": {}}},
            }
        )

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()

    def test_new_format_owned_fingerprint_not_dict_is_invalid(self) -> None:
        result = self.journal.load(
            {
                "phase": "active",
                "owned": {"iphone_usb": {"uuid": "u1", "fingerprint": "nope"}},
            }
        )

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()

    def test_new_format_owned_fingerprint_values_not_all_strings_is_invalid(
        self,
    ) -> None:
        result = self.journal.load(
            {
                "phase": "active",
                "owned": {
                    "iphone_usb": {
                        "uuid": "u1",
                        "fingerprint": {"connection.uuid": 1},
                    }
                },
            }
        )

        self.assertEqual(result, INVALID_MESSAGE)
        self._assert_unchanged()


class WriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journal = NmOwnershipJournal()

    def test_mutations_without_persist_configured_are_a_no_op(self) -> None:
        self.assertIsNone(self.journal.claim("iphone_usb", usb_profile_spec()))
        self.assertIsNone(self.journal.release("iphone_usb"))
        self.assertIsNone(self.journal.transition("active"))

    def test_successful_persist_is_invoked_by_claim_release_and_transition(
        self,
    ) -> None:
        calls: list[str] = []
        self.journal.set_persist(lambda: calls.append("persisted"))

        self.assertIsNone(self.journal.claim("iphone_usb", usb_profile_spec()))
        self.assertIsNone(self.journal.release("iphone_usb"))
        self.assertIsNone(self.journal.transition("active"))
        self.assertEqual(calls, ["persisted", "persisted", "persisted"])

    def test_persist_oserror_is_reported_as_journal_failure(self) -> None:
        def _fail() -> None:
            raise OSError("disk full")

        self.journal.set_persist(_fail)

        self.assertEqual(
            self.journal.transition("active"),
            "NetworkManager ownership journal failed: disk full",
        )

    def test_persist_valueerror_is_reported_as_journal_failure(self) -> None:
        def _fail() -> None:
            raise ValueError("bad state")

        self.journal.set_persist(_fail)

        self.assertEqual(
            self.journal.claim("iphone_usb", usb_profile_spec()),
            "NetworkManager ownership journal failed: bad state",
        )


if __name__ == "__main__":
    unittest.main()

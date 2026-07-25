from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from rootfs.app.status_issues import build_status_issues

MATRIX = json.loads(
    (Path(__file__).parent / "test_support" / "status_matrix.json").read_text(
        encoding="utf-8"
    )
)


def issues_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    if row["kind"] == "pairing":
        return build_status_issues([], None, {"upstream_pairing_state": row["input"]})
    return build_status_issues([row["input"]], None, {})


class ClassificationMatrixTests(unittest.TestCase):
    """Every classification the runtime performed at 1.0.1, frozen verbatim."""

    def test_matrix_covers_every_classification(self) -> None:
        kinds = {row["kind"] for row in MATRIX}
        self.assertEqual(kinds, {"exact", "rule", "pairing"})
        self.assertEqual(len(MATRIX), 85)

    def test_every_recorded_classification_is_unchanged(self) -> None:
        for row in MATRIX:
            with self.subTest(kind=row["kind"], value=row["input"]):
                result = issues_for(row)
                self.assertEqual(len(result), 1)
                issue = result[0]
                self.assertEqual(issue["id"], row["id"])
                self.assertEqual(issue["translation_key"], row["translation_key"])
                self.assertEqual(issue["repairable"], row["repairable"])
                self.assertEqual(issue["transient"], row["transient"])
                self.assertEqual(issue["message"], row["message"])
                self.assertTrue(issue["blocking"])

    def test_recorded_identities_are_internally_consistent(self) -> None:
        for row in MATRIX:
            with self.subTest(value=row["input"]):
                repairable = bool(row["translation_key"]) and not row["transient"]
                self.assertEqual(row["repairable"], repairable)


class ClassificationPrecedenceTests(unittest.TestCase):
    def test_earlier_rule_wins_over_a_later_overlapping_rule(self) -> None:
        hotspot = build_status_issues(
            ["Invalid app configuration: Hotspot password is too short"], None, {}
        )
        other = build_status_issues(
            ["Invalid app configuration: downstream_mac is malformed"], None, {}
        )

        self.assertEqual(hotspot[0]["id"], "hotspot_configuration_failed")
        self.assertEqual(other[0]["id"], "app_configuration_unavailable")

    def test_exact_match_wins_over_a_generic_fallthrough(self) -> None:
        exact = build_status_issues(["Upstream interface is unavailable"], None, {})
        self.assertEqual(exact[0]["id"], "upstream_interface_unavailable")
        self.assertTrue(exact[0]["transient"])

    def test_unrecognised_error_stays_visible_as_a_runtime_error(self) -> None:
        result = build_status_issues(["Totally unknown failure"], None, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "gateway_runtime_error")
        self.assertEqual(result[0]["message"], "Totally unknown failure")
        self.assertIsNone(result[0]["translation_key"])
        self.assertFalse(result[0]["repairable"])
        self.assertFalse(result[0]["transient"])
        self.assertTrue(result[0]["blocking"])

    def test_combined_messages_still_match_their_leading_rule(self) -> None:
        result = build_status_issues(
            ["Activation failed: first problem; second problem"], None, {}
        )

        self.assertEqual(result[0]["id"], "activation_failed")


class ClassificationAggregationTests(unittest.TestCase):
    def test_placeholder_safety_error_is_ignored(self) -> None:
        self.assertEqual(
            build_status_issues(["Safety checks have not run yet"], None, {}), []
        )

    def test_repeated_identity_is_reported_once(self) -> None:
        result = build_status_issues(
            [
                "Configured downstream NIC is not present",
                "USB Ethernet downstream is not present",
            ],
            None,
            {},
        )

        self.assertEqual([issue["id"] for issue in result], ["downstream_missing"])

    def test_last_error_is_used_only_without_safety_errors(self) -> None:
        alone = build_status_issues([], "Host IPv4 forwarding is not enabled", {})
        alongside = build_status_issues(
            ["Cannot verify host IPv4 forwarding"],
            "Host IPv4 forwarding is not enabled",
            {},
        )

        self.assertEqual([issue["id"] for issue in alone], ["ipv4_forwarding_disabled"])
        self.assertEqual(
            [issue["id"] for issue in alongside], ["ipv4_forwarding_unverified"]
        )

    def test_runtime_errors_are_always_appended(self) -> None:
        result = build_status_issues(
            ["Cannot verify host IPv4 forwarding"],
            None,
            {},
            runtime_errors=["Auto-stop request failed: supervisor refused"],
        )

        self.assertEqual(
            [issue["id"] for issue in result],
            ["ipv4_forwarding_unverified", "auto_stop_request_failed"],
        )

    def test_connection_warnings_are_reported_without_blocking(self) -> None:
        result = build_status_issues(
            [],
            None,
            {},
            connection_warnings=["Hotspot Wi-Fi adapter is disabled"],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "hotspot_adapter_disabled")
        self.assertFalse(result[0]["blocking"])

    def test_unrecognised_connection_warnings_are_dropped(self) -> None:
        self.assertEqual(
            build_status_issues([], None, {}, connection_warnings=["nothing known"]),
            [],
        )


class UpstreamPairingTests(unittest.TestCase):
    def test_inactive_driver_message_overrides_the_pairing_state(self) -> None:
        result = build_status_issues(
            [],
            None,
            {
                "upstream_pairing_state": "waiting_for_interface",
                "upstream_pairing_message": "The ipheth driver is not active",
            },
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "upstream_driver_inactive")
        self.assertEqual(result[0]["translation_key"], "upstream_configuration")

    def test_pairing_message_is_not_repeated_as_a_safety_error(self) -> None:
        message = "Hotspot Wi-Fi adapter is disabled"
        result = build_status_issues(
            [message],
            None,
            {
                "upstream_pairing_state": "pairing_failed",
                "upstream_pairing_message": message,
            },
        )

        self.assertEqual([issue["id"] for issue in result], ["upstream_pairing_failed"])

    def test_upstream_issue_is_reported_before_safety_errors(self) -> None:
        result = build_status_issues(
            ["Host IPv4 forwarding is not enabled"],
            None,
            {"upstream_pairing_state": "invalid_lease"},
        )

        self.assertEqual(
            [issue["id"] for issue in result],
            ["upstream_invalid_lease", "ipv4_forwarding_disabled"],
        )

    def test_unknown_pairing_state_produces_no_upstream_issue(self) -> None:
        self.assertEqual(
            build_status_issues([], None, {"upstream_pairing_state": "connected"}), []
        )


if __name__ == "__main__":
    unittest.main()

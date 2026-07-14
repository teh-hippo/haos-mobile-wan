import unittest

from rootfs.app.status_issues import build_status_issues


class StatusIssuesTests(unittest.TestCase):
    def test_no_errors_produces_empty_issues(self) -> None:
        result = build_status_issues([], None, {})
        self.assertEqual(result, [])

    def test_known_safety_error_produces_stable_issue(self) -> None:
        result = build_status_issues(
            ["Configured downstream NIC is not present"], None, {}
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "downstream_missing")
        self.assertEqual(issue["translation_key"], "downstream_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_unknown_safety_error_is_ignored(self) -> None:
        result = build_status_issues(["Some random unknown error"], None, {})
        self.assertEqual(result, [])

    def test_transient_upstream_state_produces_transient_issue(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "waiting_for_device"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_waiting_for_device")
        self.assertIsNone(issue["translation_key"])
        self.assertFalse(issue["repairable"])
        self.assertTrue(issue["transient"])

    def test_stable_upstream_pairing_state_produces_repairable_issue(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "ownership_conflict"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_ownership_conflict")
        self.assertEqual(issue["translation_key"], "upstream_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_safety_checks_not_run_sentinel_is_suppressed(self) -> None:
        result = build_status_issues(
            ["Safety checks have not run yet"], None, {}
        )
        self.assertEqual(result, [])

    def test_last_error_adds_issue_when_not_in_safety_errors(self) -> None:
        result = build_status_issues(
            [],
            "Configured downstream NIC is not present",
            {},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "downstream_missing")

    def test_last_error_not_duplicated_when_in_safety_errors(self) -> None:
        error = "Configured downstream NIC is not present"
        result = build_status_issues([error], error, {})
        self.assertEqual(len(result), 1)

    def test_prefix_match_strict_rp_filter(self) -> None:
        result = build_status_issues(
            ["Strict rp_filter is enabled on usb0"], None, {}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "strict_rp_filter_enabled")
        self.assertEqual(result[0]["translation_key"], "host_configuration")

    def test_prefix_match_policy_priority_conflict(self) -> None:
        result = build_status_issues(
            ["Policy priority 100 is already in use"], None, {}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "policy_priority_conflict")

    def test_upstream_driver_inactive_from_pairing_message(self) -> None:
        result = build_status_issues(
            [],
            None,
            {
                "upstream_pairing_state": "paired",
                "upstream_pairing_message": "iPhone is paired but the host ipheth driver is not active",
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "upstream_driver_inactive")

    def test_transient_upstream_error_not_duplicated_in_safety_errors(self) -> None:
        pairing_message = "ipheth driver is not active on this host"
        result = build_status_issues(
            [pairing_message],
            None,
            {
                "upstream_pairing_state": "paired",
                "upstream_pairing_message": pairing_message,
            },
        )
        # upstream_driver_inactive from pairing message; safety error suppressed
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "upstream_driver_inactive")

    def test_multiple_distinct_errors_produce_distinct_issues(self) -> None:
        result = build_status_issues(
            [
                "Configured downstream NIC is not present",
                "Host IPv4 forwarding is not enabled",
            ],
            None,
            {},
        )
        ids = {issue["id"] for issue in result}
        self.assertIn("downstream_missing", ids)
        self.assertIn("ipv4_forwarding_disabled", ids)

    def test_iphone_dry_run_blocked_is_repairable(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "dry_run_blocked"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_dry_run_blocked")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])


if __name__ == "__main__":
    unittest.main()

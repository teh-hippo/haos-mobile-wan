import unittest

from rootfs.app.status_issues import build_status_issues


class StatusIssuesAggregationTests(unittest.TestCase):
    def test_no_errors_produces_empty_issues(self) -> None:
        result = build_status_issues([], None, {})
        self.assertEqual(result, [])

    def test_runtime_stop_failure_is_actionable(self) -> None:
        result = build_status_issues(
            [],
            None,
            {},
            runtime_errors=[
                "Auto-stop request failed: Supervisor token is unavailable"
            ],
        )

        self.assertEqual(result[0]["id"], "auto_stop_request_failed")
        self.assertFalse(result[0]["transient"])

    def test_safety_checks_not_run_sentinel_is_suppressed(self) -> None:
        result = build_status_issues(["Safety checks have not run yet"], None, {})
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

    def test_aggregate_transient_last_error_is_not_actionable(self) -> None:
        pairing_message = (
            "Connect a single trusted iPhone with Personal Hotspot enabled"
        )
        errors = [pairing_message, "Upstream interface is unavailable"]

        result = build_status_issues(
            errors,
            "; ".join(errors),
            {
                "upstream_pairing_state": "waiting_for_device",
                "upstream_pairing_message": pairing_message,
            },
        )

        self.assertTrue(result)
        self.assertTrue(all(issue["transient"] for issue in result))
        self.assertNotIn(
            "gateway_runtime_error",
            {issue["id"] for issue in result},
        )

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

    def test_connection_warning_is_repairable(self) -> None:
        result = build_status_issues(
            [],
            None,
            {},
            ["Hotspot Wi-Fi provisioning failed: rejected"],
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "hotspot_configuration_failed")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])
        self.assertFalse(issue["blocking"])

    def test_radio_inspection_warning_is_actionable_but_non_blocking(self) -> None:
        result = build_status_issues(
            [],
            None,
            {},
            ["NetworkManager Wi-Fi radio inspection is unavailable"],
        )

        self.assertEqual(result[0]["id"], "wifi_radio_inspection_unavailable")
        self.assertFalse(result[0]["transient"])
        self.assertFalse(result[0]["blocking"])

    def test_hotspot_wifi_faults_are_distinct_issues(self) -> None:
        result = build_status_issues(
            [
                "Hotspot Wi-Fi adapter is disabled",
                "Hotspot Wi-Fi is enabled but not associated",
            ],
            None,
            {},
        )
        ids = {issue["id"] for issue in result}
        self.assertEqual(
            ids,
            {"hotspot_adapter_disabled", "hotspot_not_associated"},
        )


if __name__ == "__main__":
    unittest.main()

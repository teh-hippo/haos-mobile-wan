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

    def test_downstream_ownership_errors_are_repairable(self) -> None:
        expected = {
            "USB Ethernet downstream is not present": "downstream_missing",
            "Multiple USB Ethernet adapters detected; set downstream_mac": "downstream_ambiguous",
            "Downstream interface has host-managed IPv4 addresses": "downstream_host_managed",
            "App-owned downstream address is unavailable": "downstream_inactive",
            "Downstream interface has unexpected IPv4 addresses": "downstream_address_conflict",
        }
        for error, issue_id in expected.items():
            with self.subTest(error=error):
                result = build_status_issues([error], None, {})
                self.assertEqual(result[0]["id"], issue_id)
                self.assertEqual(
                    result[0]["translation_key"],
                    "downstream_configuration",
                )
                self.assertTrue(result[0]["repairable"])

    def test_unknown_safety_error_fails_visible(self) -> None:
        result = build_status_issues(["Some random unknown error"], None, {})
        self.assertEqual(result[0]["id"], "gateway_runtime_error")
        self.assertEqual(result[0]["message"], "Some random unknown error")
        self.assertFalse(result[0]["transient"])

    def test_configuration_load_error_is_repairable(self) -> None:
        result = build_status_issues(
            ["Cannot read app configuration: options.json is missing"],
            None,
            {},
        )
        self.assertEqual(result[0]["id"], "app_configuration_unavailable")
        self.assertEqual(
            result[0]["translation_key"],
            "host_configuration",
        )

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

    def test_waiting_for_personal_hotspot_is_transient(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "waiting_for_hotspot"},
        )

        self.assertEqual(result[0]["id"], "upstream_waiting_for_hotspot")
        self.assertTrue(result[0]["transient"])

    def test_missing_hotspot_is_a_transient_waiting_issue(self) -> None:
        result = build_status_issues(
            ["Hotspot Wi-Fi is enabled but not associated"],
            None,
            {},
        )

        self.assertEqual(result[0]["id"], "hotspot_not_associated")
        self.assertTrue(result[0]["transient"])

    def test_runtime_option_failure_is_actionable(self) -> None:
        result = build_status_issues(
            [],
            None,
            {},
            runtime_errors=[
                "Auto-disable option update failed: Supervisor unavailable"
            ],
        )

        self.assertEqual(result[0]["id"], "auto_disable_update_failed")
        self.assertFalse(result[0]["transient"])

    def test_stable_upstream_pairing_state_produces_repairable_issue(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "profile_conflict"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_profile_conflict")
        self.assertEqual(issue["translation_key"], "upstream_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_profile_setup_failure_produces_repairable_issue(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "profile_failed"},
        )

        self.assertEqual(result[0]["id"], "upstream_profile_failed")
        self.assertEqual(
            result[0]["translation_key"],
            "upstream_configuration",
        )
        self.assertTrue(result[0]["repairable"])

    def test_multiple_devices_is_repairable(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "multiple_devices"},
        )

        self.assertEqual(result[0]["id"], "upstream_multiple_devices")
        self.assertEqual(
            result[0]["translation_key"],
            "upstream_configuration",
        )
        self.assertTrue(result[0]["repairable"])

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

    def test_upstream_ipv6_active_maps_to_host_configuration_issue(self) -> None:
        result = build_status_issues(
            ["IPv6 is active on mobile upstream"], None, {}
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_ipv6_active")
        self.assertEqual(issue["translation_key"], "host_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_upstream_ipv6_unverified_maps_to_host_configuration_issue(self) -> None:
        result = build_status_issues(
            ["Cannot verify upstream IPv6 state"], None, {}
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_ipv6_unverified")
        self.assertEqual(issue["translation_key"], "host_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

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

    def test_required_command_unavailable_is_repairable(self) -> None:
        result = build_status_issues(
            ["Required command is unavailable: usbmuxd"],
            None,
            {},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_required_command_unavailable")
        self.assertEqual(issue["translation_key"], "upstream_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_waiting_for_profile_is_transient(self) -> None:
        result = build_status_issues(
            ["waiting for NetworkManager"],
            None,
            {
                "upstream_pairing_state": "waiting_for_profile",
                "upstream_pairing_message": "waiting for NetworkManager",
            },
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_waiting_for_profile")
        self.assertIsNone(issue["translation_key"])
        self.assertFalse(issue["repairable"])
        self.assertTrue(issue["transient"])

    def test_usb_access_unavailable_is_repairable(self) -> None:
        result = build_status_issues(
            ["USB device access is unavailable; enable the app usb permission"],
            None,
            {},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_usb_access_unavailable")
        self.assertEqual(issue["translation_key"], "upstream_configuration")
        self.assertTrue(issue["repairable"])

    def test_hotspot_configuration_failure_is_repairable(self) -> None:
        for error in (
            "Hotspot Wi-Fi provisioning failed: Supervisor token is unavailable",
            "Invalid app configuration: Hotspot password must be 8 to 63 characters",
        ):
            with self.subTest(error=error):
                result = build_status_issues([error], None, {})
                self.assertEqual(len(result), 1)
                issue = result[0]
                self.assertEqual(issue["id"], "hotspot_configuration_failed")
                self.assertEqual(issue["translation_key"], "hotspot_configuration")
                self.assertTrue(issue["repairable"])

    def test_waiting_for_trust_is_transient(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "waiting_for_trust"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_waiting_for_trust")
        self.assertIsNone(issue["translation_key"])
        self.assertFalse(issue["repairable"])
        self.assertTrue(issue["transient"])

    def test_waiting_for_unlock_is_transient(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "waiting_for_unlock"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_waiting_for_unlock")
        self.assertIsNone(issue["translation_key"])
        self.assertFalse(issue["repairable"])
        self.assertTrue(issue["transient"])

    def test_pairing_failed_is_repairable(self) -> None:
        result = build_status_issues(
            [],
            None,
            {"upstream_pairing_state": "pairing_failed"},
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_pairing_failed")
        self.assertEqual(issue["translation_key"], "upstream_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_hotspot_adapter_disabled_is_repairable(self) -> None:
        result = build_status_issues(
            ["Hotspot Wi-Fi adapter is disabled"], None, {}
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "hotspot_adapter_disabled")
        self.assertEqual(issue["translation_key"], "hotspot_adapter_disabled")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_hotspot_not_associated_is_transient(self) -> None:
        result = build_status_issues(
            ["Hotspot Wi-Fi is enabled but not associated"], None, {}
        )
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "hotspot_not_associated")
        self.assertEqual(issue["translation_key"], "hotspot_not_associated")
        self.assertFalse(issue["repairable"])
        self.assertTrue(issue["transient"])

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

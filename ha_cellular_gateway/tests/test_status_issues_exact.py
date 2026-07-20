import unittest

from rootfs.app.status_issues import build_status_issues


class StatusIssuesExactMappingTests(unittest.TestCase):
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
        self.assertTrue(issue["blocking"])

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

    def test_missing_hotspot_is_a_transient_waiting_issue(self) -> None:
        result = build_status_issues(
            ["Hotspot Wi-Fi is enabled but not associated"],
            None,
            {},
        )

        self.assertEqual(result[0]["id"], "hotspot_not_associated")
        self.assertTrue(result[0]["transient"])

    def test_upstream_ipv6_active_maps_to_host_configuration_issue(self) -> None:
        result = build_status_issues(["IPv6 is active on mobile upstream"], None, {})
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_ipv6_active")
        self.assertEqual(issue["translation_key"], "host_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

    def test_upstream_ipv6_unverified_maps_to_host_configuration_issue(self) -> None:
        result = build_status_issues(["Cannot verify upstream IPv6 state"], None, {})
        self.assertEqual(len(result), 1)
        issue = result[0]
        self.assertEqual(issue["id"], "upstream_ipv6_unverified")
        self.assertEqual(issue["translation_key"], "host_configuration")
        self.assertTrue(issue["repairable"])
        self.assertFalse(issue["transient"])

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

    def test_hotspot_adapter_disabled_is_repairable(self) -> None:
        result = build_status_issues(["Hotspot Wi-Fi adapter is disabled"], None, {})
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


if __name__ == "__main__":
    unittest.main()

import unittest

from rootfs.app.status_issues import build_status_issues


class StatusIssuesDynamicMappingTests(unittest.TestCase):
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

    def test_prefix_match_strict_rp_filter(self) -> None:
        result = build_status_issues(["Strict rp_filter is enabled on usb0"], None, {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "strict_rp_filter_enabled")
        self.assertEqual(result[0]["translation_key"], "host_configuration")

    def test_prefix_match_policy_priority_conflict(self) -> None:
        result = build_status_issues(
            ["Policy priority 100 is already in use"], None, {}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "policy_priority_conflict")

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


if __name__ == "__main__":
    unittest.main()

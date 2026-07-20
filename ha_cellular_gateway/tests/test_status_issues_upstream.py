import unittest

from rootfs.app.status_issues import build_status_issues


class StatusIssuesUpstreamMappingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

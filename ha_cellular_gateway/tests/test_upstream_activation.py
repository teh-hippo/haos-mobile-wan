from __future__ import annotations

import unittest

from rootfs.app.const import (
    GENERIC_USB,
    GENERIC_USB_WIFI_FALLBACK,
    IPHONE_USB_WIFI_FALLBACK,
)
from rootfs.app.nm_profile_specs import (
    GENERIC_USB_PROFILE_UUID,
    USB_PROFILE_UUID,
    WIFI_PROFILE_UUID,
)
from upstream_lifecycle_support import UpstreamLifecycleTestCase, genuine_profile


class UpstreamActivationTests(UpstreamLifecycleTestCase):
    def test_wifi_claim_creates_profile_and_gates_device(self) -> None:
        engine = self._engine()

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertFalse(engine.runner.networkmanager.nm_device_autoconnect["wlan0"])
        self.assertTrue(engine.wifi.held)
        self.assertEqual(engine.wifi.phase(), "held")
        marker = engine.wifi.state()
        self.assertIsNotNone(marker)
        self.assertTrue(marker["prior_device_autoconnect"])
        self.assertIsNone(marker["prior_active_foreign_uuid"])

    def test_fallback_claims_wifi_and_usb(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB_WIFI_FALLBACK)

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_generic_usb_claim_reuses_usb_profile_lifecycle(self) -> None:
        engine = self._engine(mobile_connection=GENERIC_USB)

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(
            GENERIC_USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles
        )
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_generic_usb_fallback_claims_usb_and_wifi(self) -> None:
        engine = self._engine(mobile_connection=GENERIC_USB_WIFI_FALLBACK)

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(
            GENERIC_USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles
        )
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_genuine_foreign_profile_is_preserved_and_displaced(self) -> None:
        engine = self._engine()
        engine.runner.networkmanager.nm_profiles["A-D074"] = genuine_profile()
        engine.runner.networkmanager.nm_active["wlan0"] = "A-D074"

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertEqual(
            engine.runner.networkmanager.nm_profiles["A-D074"], genuine_profile()
        )
        self.assertNotIn("wlan0", engine.runner.networkmanager.nm_active)
        marker = engine.wifi.state()
        assert marker is not None
        self.assertEqual(marker["prior_active_foreign_uuid"], "A-D074")

    def test_combined_mode_keeps_usb_owned_while_wifi_safely_unavailable(
        self,
    ) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB_WIFI_FALLBACK)
        engine.runner.networkmanager.nm_radio_hardware = False

        def usb_churn_commands() -> list[list[str]]:
            return [
                command
                for command in engine.runner.commands
                if (
                    command[:3] == ["nmcli", "connection", "add"]
                    and USB_PROFILE_UUID in command
                )
                or command[:4] == ["nmcli", "connection", "delete", "uuid"]
                and command[-1] == USB_PROFILE_UUID
            ]

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertEqual(engine.wifi.phase(), "blocked")
        usb_entry = engine.upstream_lifecycle.journal.entry("iphone_usb")
        assert isinstance(usb_entry, dict)
        self.assertEqual(usb_entry.get("uuid"), USB_PROFILE_UUID)
        churn_after_first = len(usb_churn_commands())

        for _ in range(2):
            engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertEqual(
            engine.upstream_lifecycle.journal.entry("iphone_usb"),
            usb_entry,
        )
        self.assertEqual(len(usb_churn_commands()), churn_after_first)


if __name__ == "__main__":
    unittest.main()

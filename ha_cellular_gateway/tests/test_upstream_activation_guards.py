from __future__ import annotations

import unittest

from rootfs.app.const import IPHONE_USB
from rootfs.app.errors import GatewayError
from rootfs.app.nm_migration import LINEAGE_WIFI_DELETE_ERROR
from rootfs.app.nm_profile_specs import (
    GENERIC_USB_PROFILE_UUID,
    USB_PROFILE_UUID,
    WIFI_PROFILE_UUID,
)
from upstream_lifecycle_support import UpstreamLifecycleTestCase, genuine_profile


def _legacy_profile(uuid: str, interface: str) -> dict[str, str]:
    return {
        "connection.uuid": uuid,
        "connection.id": "Supervisor wlan0",
        "connection.type": "802-11-wireless",
        "connection.interface-name": interface,
        "802-11-wireless.ssid": "Phone",
        "ipv4.addresses": "172.20.10.4/28",
    }


class UpstreamActivationGuardTests(UpstreamLifecycleTestCase):
    def test_legacy_lineage_cleaned_while_genuine_foreign_preserved(self) -> None:
        engine = self._engine()
        engine.runner.networkmanager.nm_profiles["bound"] = _legacy_profile(
            "bound", "wlan0"
        )
        engine.runner.networkmanager.nm_profiles["unbound"] = _legacy_profile(
            "unbound", ""
        )
        engine.runner.networkmanager.nm_profiles["A-D074"] = genuine_profile()

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn("bound", engine.runner.networkmanager.nm_profiles)
        self.assertNotIn("unbound", engine.runner.networkmanager.nm_profiles)
        self.assertIn("A-D074", engine.runner.networkmanager.nm_profiles)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_lineage_address_mismatch_is_not_cleaned(self) -> None:
        engine = self._engine()
        profile = _legacy_profile("mismatch", "wlan0")
        profile["ipv4.addresses"] = "172.20.11.4/28"
        engine.runner.networkmanager.nm_profiles["mismatch"] = profile

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("mismatch", engine.runner.networkmanager.nm_profiles)

    def test_lineage_ssid_mismatch_preserves_genuine_profile(self) -> None:
        engine = self._engine()
        profile = _legacy_profile("same-name", "wlan0")
        profile["802-11-wireless.ssid"] = "Neighbour"
        engine.runner.networkmanager.nm_profiles["same-name"] = profile

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn("same-name", engine.runner.networkmanager.nm_profiles)
        self.assertEqual(
            engine.runner.networkmanager.nm_profiles["same-name"][
                "802-11-wireless.ssid"
            ],
            "Neighbour",
        )

    def test_failed_lineage_delete_is_reported(self) -> None:
        engine = self._engine()
        engine.runner.networkmanager.nm_profiles["bound"] = _legacy_profile(
            "bound", "wlan0"
        )
        engine.runner.networkmanager.nm_delete_fail = True

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            LINEAGE_WIFI_DELETE_ERROR,
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn("bound", engine.runner.networkmanager.nm_profiles)

    def test_activation_requires_management_before_mutation(self) -> None:
        engine = self._engine()

        engine.upstream_lifecycle.activate(None)

        self.assertIn(
            "Management interface is unavailable",
            engine.upstream_lifecycle.error or "",
        )
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_unmanaged_adapter_blocks_without_mutation(self) -> None:
        engine = self._engine()
        engine.runner.networkmanager.nm_managed["wlan0"] = False

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("does not manage", engine.upstream_lifecycle.error or "")
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertTrue(engine.runner.networkmanager.nm_device_autoconnect["wlan0"])

    def test_hard_rfkill_blocks_without_mutation(self) -> None:
        engine = self._engine()
        engine.runner.networkmanager.nm_radio_hardware = False

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("hardware-blocked", engine.upstream_lifecycle.error or "")
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_wifi_profile_drift_blocks_without_deletion(self) -> None:
        engine = self._engine()
        engine.wifi.profile.create()
        engine.runner.networkmanager.nm_profiles[WIFI_PROFILE_UUID][
            "ipv4.route-table"
        ] = "254"

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("unexpected settings", engine.upstream_lifecycle.error or "")
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_usb_profile_drift_blocks_activation_without_deletion(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        engine.upstream.nm.profile.create()
        engine.runner.networkmanager.nm_profiles[USB_PROFILE_UUID][
            "ipv4.route-table"
        ] = "254"

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("unexpected settings", engine.upstream_lifecycle.error or "")
        self.assertIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_usb_profile_claim_conflict_blocks_activation(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        engine.upstream_lifecycle.journal.claim = lambda key, spec: (
            "profile ownership is already claimed elsewhere"
        )

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "profile ownership is already claimed elsewhere",
            engine.upstream_lifecycle.error or "",
        )
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_unclaimed_drifted_profile_blocks_activation_without_rescue(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        engine.runner.networkmanager.nm_profiles[GENERIC_USB_PROFILE_UUID] = {
            "connection.uuid": GENERIC_USB_PROFILE_UUID,
            "connection.id": "haos-mobile-wan-generic-usb",
            "connection.type": "802-3-ethernet",
            "match.driver": "cdc_ether",
        }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "generic USB",
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn(
            GENERIC_USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles
        )

    def test_preflight_inspection_failure_is_reported(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        engine.upstream_lifecycle.inventory.foreign_ipheth_profiles = lambda **kwargs: (
            _ for _ in ()
        ).throw(GatewayError("nmcli connection show failed"))

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "NetworkManager profile operation failed",
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn(
            "nmcli connection show failed",
            engine.upstream_lifecycle.error or "",
        )
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)

    def test_persistent_journal_failure_blocks_activation(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.journal.set_persist(
            lambda: (_ for _ in ()).throw(OSError("disk full"))
        )

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "NetworkManager ownership journal failed",
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn("disk full", engine.upstream_lifecycle.error or "")
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)


if __name__ == "__main__":
    unittest.main()

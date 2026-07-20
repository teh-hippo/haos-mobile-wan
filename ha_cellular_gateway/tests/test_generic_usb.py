from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rootfs.app.const import GENERIC_USB
from rootfs.app.management import ManagementBaseline
from rootfs.app.nm_profile_specs import GENERIC_USB_PROFILE_UUID
from rootfs.app.upstream_generic_usb import GenericUsbUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner


def add_interface(
    root: Path,
    name: str,
    driver: str,
    *,
    carrier: bool = True,
) -> None:
    driver_path = root.parent / "drivers" / driver
    driver_path.mkdir(parents=True, exist_ok=True)
    device = root / name / "device"
    device.mkdir(parents=True)
    (device / "driver").symlink_to(driver_path, target_is_directory=True)
    (root / name / "carrier").write_text(
        "1\n" if carrier else "0\n",
        encoding="utf-8",
    )


def add_usb_interface(
    root: Path,
    name: str,
    driver: str,
    usb_device: str,
) -> None:
    driver_path = root.parent / "drivers" / driver
    driver_path.mkdir(parents=True, exist_ok=True)
    device = root.parent / "devices" / usb_device / f"{usb_device}:1.0"
    device.mkdir(parents=True)
    (device / "driver").symlink_to(driver_path, target_is_directory=True)
    interface = root / name
    interface.mkdir()
    (interface / "device").symlink_to(device, target_is_directory=True)
    (interface / "carrier").write_text("1\n", encoding="utf-8")
    (interface / "address").write_text(
        "02:00:00:00:00:01\n",
        encoding="utf-8",
    )


class GenericUsbUpstreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "net"
        self.root.mkdir()
        self.runner = FakeRunner()
        self.runner.networkmanager.nm_wildcard_bind = "usb0"
        self.config = make_config(mobile_connection=GENERIC_USB)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def upstream(self) -> GenericUsbUpstream:
        return GenericUsbUpstream(
            self.config,
            lambda *args, **kwargs: self.runner.run(list(args), **kwargs),
            sys_net_root=self.root,
        )

    @staticmethod
    def management() -> ManagementBaseline:
        return ManagementBaseline("end0", "192.168.1.2/24")

    def test_supported_interface_uses_shared_dhcp_path(self) -> None:
        add_interface(self.root, "usb0", "cdc_ether")
        self.runner.networkmanager.nm_dhcp["usb0"] = {
            "address": "10.42.0.15",
            "prefix": 24,
            "gateway": "10.42.0.2",
        }
        upstream = self.upstream()
        upstream.nm.profile.create()

        resolved, errors = upstream.resolve(self.management(), "down0")

        self.assertEqual(errors, [])
        assert resolved is not None
        self.assertEqual(resolved.connection, GENERIC_USB)
        self.assertEqual(resolved.interface, "usb0")
        self.assertEqual(resolved.address, "10.42.0.15/24")
        self.assertEqual(resolved.gateway, "10.42.0.2")

    def test_downstream_and_management_interfaces_are_excluded(self) -> None:
        add_interface(self.root, "end0", "cdc_ether")
        add_interface(self.root, "usb0", "rndis_host")
        add_interface(self.root, "usb1", "cdc_ncm")
        upstream = self.upstream()

        resolved, errors = upstream.resolve(self.management(), "usb1")

        self.assertIsNone(resolved)
        self.assertNotIn("Multiple", "; ".join(errors))
        self.assertEqual(upstream.interface, "usb0")

    def test_multiple_eligible_interfaces_fail_unsafe(self) -> None:
        add_interface(self.root, "usb0", "rndis_host")
        add_interface(self.root, "usb1", "cdc_ncm")
        upstream = self.upstream()

        resolved, errors = upstream.resolve(self.management(), "down0")

        self.assertIsNone(resolved)
        self.assertIn("Multiple generic USB", errors[0])
        self.assertFalse(upstream.fallback_allowed())

    def test_carrier_waits_without_activating_profile(self) -> None:
        add_interface(self.root, "usb0", "cdc_ether", carrier=False)
        upstream = self.upstream()
        upstream.nm.profile.create()

        resolved, errors = upstream.resolve(self.management(), "down0")

        self.assertIsNone(resolved)
        self.assertIn("Enable USB tethering", errors[0])
        self.assertNotIn("usb0", self.runner.networkmanager.nm_active)

    def test_foreign_bound_profile_blocks_selected_interface(self) -> None:
        add_interface(self.root, "usb0", "cdc_ether")
        upstream = self.upstream()
        upstream.nm.profile.create()
        self.runner.networkmanager.nm_profiles["foreign"] = {
            "connection.uuid": "foreign",
            "connection.id": "foreign",
            "connection.type": "802-3-ethernet",
            "connection.interface-name": "usb0",
            "match.driver": "",
        }

        resolved, errors = upstream.resolve(self.management(), "down0")

        self.assertIsNone(resolved)
        self.assertIn("foreign NetworkManager profile", errors[0])
        self.assertFalse(upstream.fallback_allowed())
        self.assertIn(GENERIC_USB_PROFILE_UUID, self.runner.networkmanager.nm_profiles)

    def test_engine_assigns_tether_and_router_adapters_separately(self) -> None:
        add_usb_interface(self.root, "usb0", "cdc_ether", "usb2")
        add_usb_interface(self.root, "enxdown", "r8152", "usb1")
        self.runner.networkmanager.nm_wildcard_bind = "usb0"
        self.runner.networkmanager.nm_dhcp["usb0"] = {
            "address": "10.42.0.15",
            "prefix": 24,
            "gateway": "10.42.0.2",
        }
        config = make_config(
            mobile_connection=GENERIC_USB,
            downstream_mac="",
        )
        values = sysctl_values()
        engine = build_engine(
            config,
            runner=self.runner,
            read_text=lambda path: values[path],
            state_path=Path(self.directory.name) / "state.json",
        )
        engine.downstream.sys_net_root = self.root
        assert isinstance(engine.upstream, GenericUsbUpstream)
        engine.upstream.sys_net_root = self.root

        downstream = engine.downstream.find("end0")
        engine.upstream_lifecycle.activate(self.management())
        resolved, errors = engine.upstream.resolve(
            self.management(),
            downstream,
        )

        self.assertEqual(downstream, "enxdown")
        self.assertEqual(errors, [])
        assert resolved is not None
        self.assertEqual(resolved.interface, "usb0")


if __name__ == "__main__":
    unittest.main()

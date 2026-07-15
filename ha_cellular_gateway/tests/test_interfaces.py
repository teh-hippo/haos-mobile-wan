import tempfile
import unittest
from pathlib import Path

from rootfs.app.errors import GatewayError
from rootfs.app.downstream import DownstreamInterface
from rootfs.app.management import detect_management

from helpers import FakeRunner, make_config


class HostInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.sys_net_root = self.root / "sys" / "class" / "net"
        self.sys_net_root.mkdir(parents=True)
        self.runner = FakeRunner()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _downstream(
        self,
        *,
        mac: str = "",
    ) -> DownstreamInterface:
        return DownstreamInterface(
            make_config(downstream_mac=mac),
            lambda *args, **kwargs: self.runner.run(
                list(args),
                check=kwargs.get("check", True),
                timeout=kwargs.get("timeout", 20),
            ),
            lambda path: path.read_text(encoding="utf-8"),
            sys_net_root=self.sys_net_root,
        )

    def _add_interface(
        self,
        name: str,
        mac: str,
        *,
        driver: str = "r8152",
        usb: bool = True,
    ) -> None:
        interface = self.sys_net_root / name
        interface.mkdir()
        (interface / "address").write_text(f"{mac}\n", encoding="utf-8")

        bus = "usb2" if usb else "platform"
        device = self.root / "sys" / "devices" / bus / name
        device.mkdir(parents=True)
        drivers = self.root / "drivers"
        drivers.mkdir(exist_ok=True)
        driver_path = drivers / driver
        driver_path.mkdir(exist_ok=True)
        (device / "driver").symlink_to(driver_path)
        (interface / "device").symlink_to(device)

    def test_detects_management_from_default_route(self) -> None:
        baseline = detect_management(
            lambda *args, **kwargs: self.runner.run(list(args), **kwargs)
        )
        self.assertEqual(baseline.interface, "end0")
        self.assertEqual(baseline.address, "192.168.1.2/24")

    def test_management_prefers_route_source(self) -> None:
        self.runner.interface_addresses["end0"] = [
            ("192.168.1.2", 24),
            ("192.168.1.3", 24),
        ]
        self.runner.main_default_routes[0]["prefsrc"] = "192.168.1.3"
        baseline = detect_management(
            lambda *args, **kwargs: self.runner.run(list(args), **kwargs)
        )
        self.assertEqual(baseline.address, "192.168.1.3/24")

    def test_rejects_multiple_management_interfaces(self) -> None:
        self.runner.main_default_routes.append(
            {"dst": "default", "gateway": "10.0.0.1", "dev": "eth9"}
        )
        with self.assertRaisesRegex(GatewayError, "exactly one"):
            detect_management(
                lambda *args, **kwargs: self.runner.run(list(args), **kwargs)
            )

    def test_auto_selects_only_usb_ethernet_adapter(self) -> None:
        self._add_interface("enp1s0u1", "6c:1f:f7:cc:49:ab")
        self._add_interface(
            "eth0",
            "00:11:22:33:44:55",
            driver="ipheth",
        )
        self._add_interface("end1", "00:11:22:33:44:66", usb=False)

        downstream = self._downstream()

        self.assertEqual(downstream.candidates(), ["enp1s0u1"])
        self.assertEqual(downstream.find(), "enp1s0u1")
        self.assertEqual(
            downstream.mac("enp1s0u1"),
            "6c:1f:f7:cc:49:ab",
        )

    def test_mac_override_selects_between_usb_adapters(self) -> None:
        self._add_interface("enp1s0u1", "6c:1f:f7:cc:49:ab")
        self._add_interface("enp1s0u2", "00:11:22:33:44:55")

        downstream = self._downstream(mac="00:11:22:33:44:55")

        self.assertEqual(downstream.find(), "enp1s0u2")

    def test_multiple_adapters_require_override(self) -> None:
        self._add_interface("enp1s0u1", "6c:1f:f7:cc:49:ab")
        self._add_interface("enp1s0u2", "00:11:22:33:44:55")
        downstream = self._downstream()

        self.assertIsNone(downstream.find())
        self.assertEqual(
            downstream.selection_error(),
            "Multiple USB Ethernet adapters detected; set downstream_mac",
        )

    def test_owns_only_exact_transient_address(self) -> None:
        downstream = self._downstream()
        ownership = {
            "downstream": "enp1s0u1",
            "downstream_address": "192.168.80.1/24",
            "downstream_address_owned": True,
        }

        downstream.apply("enp1s0u1")
        self.assertEqual(
            self.runner.interface_addresses["enp1s0u1"],
            ("192.168.80.1", 24),
        )
        downstream.cleanup(ownership)
        self.assertNotIn("enp1s0u1", self.runner.interface_addresses)

    def test_rejects_host_managed_downstream_address(self) -> None:
        self.runner.interface_addresses["enp1s0u1"] = ("192.168.80.9", 24)
        downstream = self._downstream()

        self.assertEqual(
            downstream.address_errors("enp1s0u1", owned=False),
            ["Downstream interface has host-managed IPv4 addresses"],
        )
        with self.assertRaisesRegex(GatewayError, "host-managed"):
            downstream.apply("enp1s0u1")


if __name__ == "__main__":
    unittest.main()

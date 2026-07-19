import shutil
import subprocess
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised in CI
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "ha_cellular_gateway" / "config.yaml"
APPARMOR_PATH = REPO_ROOT / "ha_cellular_gateway" / "apparmor.txt"


@unittest.skipIf(yaml is None, "pyyaml is required for addon metadata checks")
class AddonSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.profile = APPARMOR_PATH.read_text(encoding="utf-8")

    def test_metadata_keeps_minimal_supported_permissions(self) -> None:
        self.assertEqual(self.config["arch"], ["aarch64"])
        self.assertTrue(self.config["host_network"])
        self.assertTrue(self.config["hassio_api"])
        self.assertEqual(self.config["hassio_role"], "manager")
        self.assertTrue(self.config["usb"])
        self.assertTrue(self.config["apparmor"])
        self.assertEqual(self.config["timeout"], 90)
        self.assertEqual(self.config["privileged"], ["NET_ADMIN", "NET_RAW"])
        self.assertNotIn("full_access", self.config)
        self.assertTrue(self.config["host_dbus"])
        self.assertNotIn("udev", self.config)
        self.assertEqual(
            set(self.config["options"]),
            {
                "auto_disable_minutes",
                "mobile_connection",
                "hotspot_ssid",
                "hotspot_password",
            },
        )
        self.assertNotIn("enabled", self.config["schema"])
        self.assertEqual(
            self.config["schema"]["router_address"],
            "str?",
        )

    def test_apparmor_profile_is_enforcing_and_scoped(self) -> None:
        self.assertIn(
            "profile ha_cellular_gateway flags=(attach_disconnected,mediate_deleted) {",
            self.profile,
        )
        self.assertNotIn("complain", self.profile)
        for fragment in (
            "/run/**",
            "/proc/**",
            "/sys/bus/usb/**",
            "/sys/module/**",
            "/usr/sbin/conntrack",
        ):
            self.assertNotIn(fragment, self.profile)
        for fragment in (
            "capability net_admin,",
            "capability net_raw,",
            "/run/dbus/system_bus_socket rw,",
            "dbus (send, receive) bus=system peer=(name=org.freedesktop.NetworkManager),",
            "/run/ha-cellgw/** rwk,",
            "/run/usbmuxd rw,",
            "/run/usbmuxd/** rwk,",
            "/var/run/usbmuxd rw,",
            "/var/lib/lockdown/** rwk,",
            "/proc/sys/net/ipv4/** r,",
            "/dev/bus/usb/** rw,",
            "/sys/class/net/** r,",
            "/sys/devices/** r,",
            "/sys/bus/usb/devices/ r,",
            "/sys/bus/usb/devices/** r,",
            "/sys/bus/usb/drivers/ipheth/** r,",
            "/sys/bus/usb/drivers/rndis_host/** r,",
            "/sys/bus/usb/drivers/cdc_ether/** r,",
            "/sys/bus/usb/drivers/cdc_ncm/** r,",
            "/sys/module/ipheth/** r,",
            "/usr/bin/python3 ix,",
            "/usr/bin/curl rix,",
            "/usr/bin/idevice_id rix,",
            "/usr/bin/idevicepair rix,",
            "/usr/bin/nmcli rix,",
            "/usr/sbin/dnsmasq rix,",
            "/usr/sbin/usbmuxd rix,",
            "/bin/busybox rix,",
            "/sbin/ip rix,",
            "/sbin/iptables rix,",
            "/sbin/ip6tables rix,",
            "/bin/sh ix,",
        ):
            self.assertIn(fragment, self.profile)
        for fragment in (
            "/sbin/udhcpc",
            "udhcpc.script",
        ):
            self.assertNotIn(fragment, self.profile)

    def test_apparmor_profile_parses(self) -> None:
        parser = shutil.which("apparmor_parser")
        if parser is None:
            self.skipTest("apparmor_parser is unavailable")
        result = subprocess.run(
            [parser, "-QK", str(APPARMOR_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()

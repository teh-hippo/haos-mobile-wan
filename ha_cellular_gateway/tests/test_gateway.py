import json
import tempfile
import unittest
from pathlib import Path

from rootfs.app.gateway import GatewayConfig, GatewayEngine, SafetyError


class Result:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str], *, check: bool = True, timeout: int = 20) -> Result:
        self.commands.append(args)
        if args[:2] == ["iptables", "--version"]:
            return Result(stdout="iptables v1.8.13 (nf_tables)\n")
        if args[:3] in (["iptables", "-S", "DOCKER-USER"], ["ip6tables", "-S", "DOCKER-USER"]):
            return Result()
        if args[:4] == ["ip", "-4", "-j", "address"]:
            interface = args[-1]
            mapping = {
                "end0": "192.168.1.2",
                "wlan0": "172.20.10.4",
                "enx001122334455": "192.168.80.1",
            }
            address = mapping[interface]
            return Result(
                stdout=json.dumps(
                    [{"addr_info": [{"family": "inet", "local": address, "prefixlen": 24 if interface != "wlan0" else 28}]}]
                )
            )
        if args[:4] == ["ip", "-6", "-j", "address"]:
            return Result(stdout="[]")
        if args[:7] == ["ip", "-4", "-j", "route", "show", "table", "main"]:
            return Result(stdout='[{"dst":"default","gateway":"192.168.1.1","dev":"end0"}]')
        if args[:4] == ["ip", "-j", "rule", "show"]:
            return Result(stdout="[]")
        if args[:4] == ["ip", "rule", "del", "pref"]:
            return Result(returncode=1)
        if "-C" in args:
            return Result(returncode=1)
        return Result()


def make_config(**overrides: object) -> GatewayConfig:
    values = {
        "mode": "disabled",
        "dry_run": True,
        "management_interface": "end0",
        "management_address": "192.168.1.2/24",
        "upstream_interface": "wlan0",
        "upstream_ssid": "MobileHotspot",
        "upstream_address": "172.20.10.4/28",
        "upstream_gateway": "172.20.10.1",
        "downstream_mac": "00:11:22:33:44:55",
        "downstream_address": "192.168.80.1/24",
        "transit_subnet": "192.168.80.0/24",
        "dhcp_start": "192.168.80.10",
        "dhcp_end": "192.168.80.50",
        "dns_servers": ("1.1.1.1", "8.8.8.8"),
        "routing_table": 201,
        "reconcile_seconds": 5,
        "trial_seconds": 300,
        "api_bind": "172.30.32.1",
        "api_port": 8099,
    }
    values.update(overrides)
    return GatewayConfig(**values)


class GatewayConfigTests(unittest.TestCase):
    def test_rejects_overlapping_transit(self) -> None:
        config = make_config(
            downstream_address="192.168.1.1/24",
            transit_subnet="192.168.1.0/24",
            dhcp_start="192.168.1.10",
            dhcp_end="192.168.1.50",
        )
        with self.assertRaisesRegex(Exception, "must differ"):
            config.validate()

    def test_reads_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text(
                json.dumps(
                    {
                        "mode": "disabled",
                        "dry_run": True,
                        "downstream_mac": "00:11:22:33:44:55",
                    }
                ),
                encoding="utf-8",
            )
            config = GatewayConfig.from_path(path)
            self.assertEqual(config.transit_subnet, "192.168.80.0/24")


class GatewayEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = FakeRunner()
        values = {
            Path("/proc/sys/net/ipv4/ip_forward"): "1",
            Path("/proc/sys/net/ipv4/conf/all/rp_filter"): "0",
            Path("/proc/sys/net/ipv4/conf/default/rp_filter"): "2",
            Path("/proc/sys/net/ipv4/conf/end0/rp_filter"): "2",
            Path("/proc/sys/net/ipv4/conf/wlan0/rp_filter"): "2",
            Path("/proc/sys/net/ipv4/conf/enx001122334455/rp_filter"): "2",
        }
        self.engine = GatewayEngine(
            make_config(),
            runner=self.runner,
            read_text=lambda path: values[path],
        )
        self.engine._find_interface_by_mac = lambda: "enx001122334455"

    def test_dry_run_refuses_mutation(self) -> None:
        with self.assertRaisesRegex(SafetyError, "dry_run"):
            self.engine.apply("trial")

    def test_dry_run_cleanup_does_not_run_commands(self) -> None:
        self.engine.cleanup()
        self.assertEqual(self.runner.commands, [])

    def test_firewall_is_scoped(self) -> None:
        self.engine._apply_firewall("enx001122334455")
        commands = [" ".join(command) for command in self.runner.commands]
        self.assertTrue(any("NEW,ESTABLISHED" in command for command in commands))
        self.assertTrue(any("ESTABLISHED,RELATED" in command for command in commands))
        self.assertTrue(any("! -o wlan0" in command for command in commands))
        self.assertTrue(
            any(
                "-i enx001122334455 -o wlan0 -s 192.168.80.0/24" in command
                and "TCPMSS" in command
                for command in commands
            )
        )
        self.assertFalse(
            any(
                "--ctstate ESTABLISHED,RELATED -j ACCEPT" in command
                and "-i wlan0" not in command
                for command in commands
            )
        )

    def test_policy_routes_only_transit(self) -> None:
        self.engine._apply_policy_routing("enx001122334455")
        commands = [" ".join(command) for command in self.runner.commands]
        self.assertIn(
            "ip rule add pref 20100 iif enx001122334455 lookup 201",
            commands,
        )
        self.assertIn(
            "ip rule add pref 20110 from 192.168.80.0/24 lookup 201",
            commands,
        )
        self.assertFalse(any("end0" in command for command in commands))


if __name__ == "__main__":
    unittest.main()

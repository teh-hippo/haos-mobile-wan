from __future__ import annotations

import json
from pathlib import Path

from rootfs.app.config import GatewayConfig


class Result:
    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeProcess:
    def __init__(self) -> None:
        self.running = True

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False

    def wait(self, timeout: int = 5) -> int:
        return 0


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.policy_rules: list[dict[str, object]] = []
        self.policy_routes: list[dict[str, object]] = []
        self.fail_ip_forward = False
        self.idevice_udids: list[str] = []
        self.idevice_pair_result = Result(returncode=1, stdout="ERROR: Please accept the trust dialog\n")
        self.idevice_validate_result = Result(returncode=1, stdout="ERROR: Device is not paired\n")
        self.main_default_routes = [{"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}]
        self.interface_addresses = {
            "end0": ("192.168.1.2", 24),
            "wlan0": ("172.20.10.4", 28),
            "enx001122334455": ("192.168.80.1", 24),
        }

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> Result:
        self.commands.append(args)
        if args[:2] == ["iptables", "--version"]:
            return Result(stdout="iptables v1.8.13 (nf_tables)\n")
        if args[:3] in (
            ["iptables", "-S", "DOCKER-USER"],
            ["iptables", "-S", "INPUT"],
            ["ip6tables", "-S", "DOCKER-USER"],
            ["ip6tables", "-S", "INPUT"],
        ):
            return Result()
        if len(args) >= 3 and args[1] == "-S" and args[2].startswith("HA_CELL"):
            return Result(returncode=1)
        if args[:4] == ["ip", "-4", "-j", "address"]:
            interface = args[-1]
            address, prefix = self.interface_addresses[interface]
            return Result(
                stdout=json.dumps(
                    [
                        {
                            "addr_info": [
                                {
                                    "family": "inet",
                                    "local": address,
                                    "prefixlen": prefix,
                                }
                            ]
                        }
                    ]
                )
            )
        if args[:4] == ["ip", "-6", "-j", "address"]:
            return Result(stdout="[]")
        if args[:7] == [
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            "main",
        ]:
            return Result(stdout=json.dumps(self.main_default_routes))
        if args[:7] == [
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            "201",
        ]:
            return Result(stdout=json.dumps(self.policy_routes))
        if args[:4] == ["ip", "-j", "rule", "show"]:
            return Result(stdout=json.dumps(self.policy_rules))
        if args[:3] in (["ip", "rule", "del"], ["ip", "route", "del"]):
            if args[:5] == ["ip", "route", "del", "default", "dev"]:
                interface = args[5]
                removed = False
                remaining = []
                for route in self.main_default_routes:
                    if route.get("dev") == interface and route.get("dst") == "default" and not removed:
                        removed = True
                        continue
                    remaining.append(route)
                self.main_default_routes = remaining
                return Result(returncode=0 if removed else 1)
            return Result(returncode=1)
        if args[:2] == ["idevice_id", "--list"]:
            return Result(stdout="\n".join(self.idevice_udids) + ("\n" if self.idevice_udids else ""))
        if args and args[0] == "idevicepair" and "--udid" in args:
            if args[-1] == "validate":
                return self.idevice_validate_result
            if args[-1] == "pair":
                return self.idevice_pair_result
        if "-C" in args:
            return Result(returncode=1)
        if args and args[0] == "curl":
            return Result(stdout="ip=203.0.113.10\n")
        return Result()


def make_config(**overrides: object) -> GatewayConfig:
    values = {
        "mode": "disabled",
        "dry_run": True,
        "management_interface": "end0",
        "management_address": "192.168.1.2/24",
        "upstream_mode": "hotspot_wifi",
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


def sysctl_values() -> dict[Path, str]:
    return {
        Path("/proc/sys/net/ipv4/ip_forward"): "1",
        Path("/proc/sys/net/ipv4/conf/all/rp_filter"): "0",
        Path("/proc/sys/net/ipv4/conf/default/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/end0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/wlan0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/eth0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/enx001122334455/rp_filter"): "2",
    }

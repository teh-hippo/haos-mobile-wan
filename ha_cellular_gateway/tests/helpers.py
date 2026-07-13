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
        self.chain_listings: dict[tuple[str, str], str] = {}
        self.rule_checks: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()

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
        if len(args) == 3 and args[1] == "-S":
            listing = self.chain_listings.get((args[0], args[2]))
            if listing is not None:
                return Result(stdout=listing)
        if len(args) >= 3 and args[1] == "-S" and args[2].startswith("HA_CELL"):
            return Result(returncode=1)
        if args[:4] == ["ip", "-4", "-j", "address"]:
            interface = args[-1]
            mapping = {
                "end0": "192.168.1.2",
                "wlan0": "172.20.10.4",
                "enx001122334455": "192.168.80.1",
            }
            address = mapping[interface]
            prefix = 28 if interface == "wlan0" else 24
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
            return Result(
                stdout='[{"dst":"default","gateway":"192.168.1.1","dev":"end0"}]'
            )
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
            return Result(returncode=1)
        if "-C" in args:
            index = args.index("-C")
            if (
                args[0],
                tuple(args[1:index]),
                tuple(args[index + 1 :]),
            ) in self.rule_checks:
                return Result()
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


def install_realistic_firewall_state(runner: FakeRunner, firewall, downstream: str) -> None:
    upstream = firewall.config.upstream_interface
    subnet = firewall.config.transit_subnet
    runner.rule_checks.update(
        {
            (
                "iptables",
                tuple(),
                (
                    "INPUT",
                    *firewall.netfilter.jump_rule(
                        firewall.INPUT_CHAIN,
                        "ha-cellgw:local-jump",
                        ["-i", downstream],
                    ),
                ),
            ),
            (
                "iptables",
                tuple(),
                (
                    "DOCKER-USER",
                    *firewall.netfilter.jump_rule(
                        firewall.FORWARD_CHAIN,
                        "ha-cellgw:jump",
                    ),
                ),
            ),
            (
                "iptables",
                ("-t", "nat"),
                ("POSTROUTING", *firewall._nat_rule()),
            ),
            *{
                (
                    "iptables",
                    ("-t", "mangle"),
                    ("FORWARD", *rule),
                )
                for rule in firewall._mss_rules(downstream)
            },
            (
                "ip6tables",
                tuple(),
                (
                    "INPUT",
                    *firewall.netfilter.jump_rule(
                        firewall.INPUT6_CHAIN,
                        "ha-cellgw:v6-local-jump",
                        ["-i", downstream],
                    ),
                ),
            ),
            (
                "ip6tables",
                tuple(),
                (
                    "DOCKER-USER",
                    *firewall.netfilter.jump_rule(
                        firewall.FORWARD6_CHAIN,
                        "ha-cellgw:v6-jump",
                    ),
                ),
            ),
        }
    )
    runner.chain_listings.update(
        {
            (
                "iptables",
                firewall.INPUT_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.INPUT_CHAIN}",
                    "-A HA_CELLGW_LOCAL -m conntrack --ctstate RELATED,ESTABLISHED "
                    "-m comment --comment ha-cellgw:local-established -j ACCEPT",
                    "-A HA_CELLGW_LOCAL -p udp -m udp --sport 68 --dport 67 "
                    "-m comment --comment ha-cellgw:dhcp-in -j ACCEPT",
                    "-A HA_CELLGW_LOCAL -p icmp -m comment --comment ha-cellgw:icmp-in "
                    "-j ACCEPT",
                    "-A HA_CELLGW_LOCAL -m comment --comment ha-cellgw:local-drop -j DROP",
                )
            ),
            (
                "iptables",
                firewall.FORWARD_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.FORWARD_CHAIN}",
                    f"-A HA_CELLGW -i {downstream} -o {upstream} -s {subnet} "
                    "-m conntrack --ctstate ESTABLISHED,NEW -m comment "
                    "--comment ha-cellgw:out -j ACCEPT",
                    f"-A HA_CELLGW -i {upstream} -o {downstream} -d {subnet} "
                    "-m conntrack --ctstate RELATED,ESTABLISHED -m comment "
                    "--comment ha-cellgw:in -j ACCEPT",
                    f"-A HA_CELLGW -i {downstream} ! -o {upstream} -m comment "
                    "--comment ha-cellgw:drop-out -j DROP",
                    f"-A HA_CELLGW ! -i {upstream} -o {downstream} -m comment "
                    "--comment ha-cellgw:drop-in -j DROP",
                    "-A HA_CELLGW -j RETURN",
                )
            ),
            (
                "ip6tables",
                firewall.INPUT6_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.INPUT6_CHAIN}",
                    "-A HA_CELLGW6_LOCAL -j DROP",
                )
            ),
            (
                "ip6tables",
                firewall.FORWARD6_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.FORWARD6_CHAIN}",
                    f"-A HA_CELLGW6 -i {downstream} -j DROP",
                    f"-A HA_CELLGW6 -o {downstream} -j DROP",
                    "-A HA_CELLGW6 -j RETURN",
                )
            ),
        }
    )


def sysctl_values() -> dict[Path, str]:
    return {
        Path("/proc/sys/net/ipv4/ip_forward"): "1",
        Path("/proc/sys/net/ipv4/conf/all/rp_filter"): "0",
        Path("/proc/sys/net/ipv4/conf/default/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/end0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/wlan0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/enx001122334455/rp_filter"): "2",
    }

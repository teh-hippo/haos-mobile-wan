from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from rootfs.app.config import GatewayConfig
from rootfs.app.const import WIFI_HOTSPOT


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
    def __init__(
        self,
        *,
        running: bool = True,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.running = running
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def poll(self) -> int | None:
        return None if self.running else self.returncode

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False

    def wait(self, timeout: int = 5) -> int:
        if self.running:
            raise subprocess.TimeoutExpired("fake-process", timeout)
        return self.returncode

    def communicate(self, timeout: int = 1) -> tuple[str, str]:
        self.running = False
        return self.stdout, self.stderr


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.policy_rules: list[dict[str, object]] = []
        self.policy_routes: list[dict[str, object]] = []
        self.fail_ip_forward = False
        self.chain_listings: dict[tuple[str, str], str] = {}
        self.rule_checks: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
        self.idevice_udids: list[str] = []
        self.idevice_paired_udids: list[str] = []
        self.idevice_pair_result = Result(returncode=1, stdout="ERROR: Please accept the trust dialog\n")
        self.idevice_validate_result = Result(returncode=1, stdout="ERROR: Device is not paired\n")
        self.main_default_routes = [{"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}]
        self.interface_addresses = {
            "end0": ("192.168.1.2", 24),
            "wlan0": ("172.20.10.4", 28),
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
        family = args[0] if args else ""
        action_index = 1
        if len(args) >= 3 and args[1] == "-t":
            action_index = 3
        if len(args) > action_index + 1 and args[action_index] == "-S":
            chain = args[action_index + 1]
            listing = self.chain_listings.get((family, chain))
            if listing is not None:
                return Result(stdout=listing)
        if (
            len(args) > action_index + 1
            and args[action_index] == "-S"
            and (family, args[action_index + 1]) in {
                ("iptables", "DOCKER-USER"),
                ("iptables", "INPUT"),
                ("ip6tables", "DOCKER-USER"),
                ("ip6tables", "INPUT"),
            }
        ):
            return Result()
        if (
            len(args) > action_index + 1
            and args[action_index] == "-S"
            and args[action_index + 1].startswith("HA_CELL")
        ):
            return Result(returncode=1)
        if args[:4] == ["ip", "-4", "-j", "address"]:
            interface = args[-1]
            if interface not in self.interface_addresses:
                return Result(stdout="[]")
            configured = self.interface_addresses[interface]
            addresses = (
                configured
                if isinstance(configured, list)
                else [configured]
            )
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
                                for address, prefix in addresses
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
        if args[:4] in (
            ["ip", "-4", "address", "add"],
            ["ip", "-4", "address", "del"],
        ):
            address, interface = args[4], args[6]
            local, _, prefix = address.partition("/")
            value = (local, int(prefix))
            configured = self.interface_addresses.get(interface)
            addresses = (
                list(configured)
                if isinstance(configured, list)
                else ([configured] if configured else [])
            )
            if args[3] == "add":
                if value not in addresses:
                    addresses.append(value)
                self.interface_addresses[interface] = (
                    addresses[0] if len(addresses) == 1 else addresses
                )
                return Result()
            if value not in addresses:
                return Result(returncode=1)
            addresses.remove(value)
            if not addresses:
                self.interface_addresses.pop(interface, None)
            else:
                self.interface_addresses[interface] = (
                    addresses[0] if len(addresses) == 1 else addresses
                )
            return Result()
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
        if args[:2] == ["idevicepair", "list"]:
            return Result(
                stdout="\n".join(self.idevice_paired_udids)
                + ("\n" if self.idevice_paired_udids else "")
            )
        if args and args[0] == "idevicepair" and "--udid" in args:
            if args[-1] == "validate":
                return self.idevice_validate_result
            if args[-1] == "pair":
                return self.idevice_pair_result
        if "-C" in args:
            index = args.index("-C")
            if (
                args[0],
                tuple(args[1:index]),
                tuple(args[index + 1 :]),
            ) in self.rule_checks:
                return Result()
            return Result(returncode=1)
        if family in {"iptables", "ip6tables"} and len(args) > action_index:
            action = args[action_index]
            command = args[action_index + 1 :]
            if action == "-N" and command:
                self.chain_listings.setdefault((family, command[0]), f"-N {command[0]}")
            elif action == "-F" and command:
                self._flush_chain(family, command[0])
            elif action == "-X" and command:
                self.chain_listings.pop((family, command[0]), None)
            elif action == "-A" and len(command) >= 2:
                self._append_rule(family, command[0], command[1:])
            elif action == "-I" and len(command) >= 3:
                self._insert_rule(
                    family,
                    command[0],
                    int(command[1]),
                    command[2:],
                )
            elif action == "-D" and len(command) >= 1:
                self._delete_rule(family, command[0], command[1:])
        if args and args[0] == "curl":
            return Result(stdout="ip=203.0.113.10\n")
        return Result()

    def _chain_lines(self, family: str, chain: str) -> list[str]:
        listing = self.chain_listings.get((family, chain))
        return [] if not listing else listing.splitlines()

    def _set_chain_lines(self, family: str, chain: str, lines: list[str]) -> None:
        self.chain_listings[(family, chain)] = "\n".join(lines)

    def _append_rule(self, family: str, chain: str, rule: list[str]) -> None:
        lines = self._chain_lines(family, chain)
        lines.append(self._rule_line(chain, rule))
        self._set_chain_lines(family, chain, lines)

    def _insert_rule(
        self,
        family: str,
        chain: str,
        position: int,
        rule: list[str],
    ) -> None:
        lines = self._chain_lines(family, chain)
        header = 1 if lines[:1] == [f"-N {chain}"] else 0
        insert_at = min(header + max(position - 1, 0), len(lines))
        lines.insert(insert_at, self._rule_line(chain, rule))
        self._set_chain_lines(family, chain, lines)

    def _delete_rule(self, family: str, chain: str, spec: list[str]) -> None:
        lines = self._chain_lines(family, chain)
        rule_indexes = [
            index
            for index, line in enumerate(lines)
            if line.startswith(f"-A {chain} ")
        ]
        if not rule_indexes:
            return
        if len(spec) == 1 and spec[0].isdigit():
            position = int(spec[0])
            if 1 <= position <= len(rule_indexes):
                del lines[rule_indexes[position - 1]]
                self._set_chain_lines(family, chain, lines)
            return
        target = self._rule_line(chain, spec)
        for index in rule_indexes:
            if lines[index] == target:
                del lines[index]
                self._set_chain_lines(family, chain, lines)
                return

    def _flush_chain(self, family: str, chain: str) -> None:
        lines = self._chain_lines(family, chain)
        if lines[:1] == [f"-N {chain}"]:
            self._set_chain_lines(family, chain, [lines[0]])
            return
        self._set_chain_lines(family, chain, [])

    @staticmethod
    def _rule_line(chain: str, rule: list[str]) -> str:
        return shlex.join(["-A", chain, *rule])


def make_config(**overrides: object) -> GatewayConfig:
    values = {
        "enabled": False,
        "management_interface": "end0",
        "management_address": "192.168.1.2/24",
        "mobile_connection": WIFI_HOTSPOT,
        "upstream_interface": "wlan0",
        "upstream_address": "172.20.10.4/28",
        "upstream_gateway": "172.20.10.1",
        "hotspot_ssid": "",
        "hotspot_password": "",
        "downstream_mac": "00:11:22:33:44:55",
        "downstream_address": "192.168.80.1/24",
    }
    values.update(overrides)
    return GatewayConfig(**values)


def install_realistic_firewall_state(
    runner: FakeRunner,
    firewall,
    downstream: str,
    upstream: str | None = None,
) -> None:
    upstream = upstream or firewall.config.upstream_interface
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
                ("POSTROUTING", *firewall._nat_rule(upstream)),
            ),
            *{
                (
                    "iptables",
                    ("-t", "mangle"),
                    ("FORWARD", *rule),
                )
                for rule in firewall._mss_rules(downstream, upstream)
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
                "INPUT",
            ): "\n".join(
                (
                    "-A INPUT "
                    f"-i {downstream} -m comment --comment ha-cellgw:local-jump "
                    f"-j {firewall.INPUT_CHAIN}",
                )
            ),
            (
                "iptables",
                "DOCKER-USER",
            ): "\n".join(
                (
                    "-A DOCKER-USER -m comment --comment ha-cellgw:jump "
                    f"-j {firewall.FORWARD_CHAIN}",
                )
            ),
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
                "INPUT",
            ): "\n".join(
                (
                    "-A INPUT "
                    f"-i {downstream} -m comment --comment ha-cellgw:v6-local-jump "
                    f"-j {firewall.INPUT6_CHAIN}",
                )
            ),
            (
                "ip6tables",
                "DOCKER-USER",
            ): "\n".join(
                (
                    "-A DOCKER-USER -m comment --comment ha-cellgw:v6-jump "
                    f"-j {firewall.FORWARD6_CHAIN}",
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


def install_realistic_policy_state(
    runner: FakeRunner,
    policy,
    downstream: str,
    upstream=None,
) -> None:
    ownership = policy.ownership(downstream, upstream)
    runner.policy_rules = []
    for rule in policy.rule_args(ownership):
        entry = {
            "priority": int(rule[rule.index("pref") + 1]),
            "table": rule[rule.index("lookup") + 1],
        }
        if "iif" in rule:
            entry["iifname"] = rule[rule.index("iif") + 1]
        if "from" in rule:
            source = rule[rule.index("from") + 1]
            if "/" in source:
                address, _, length = source.partition("/")
                entry["src"] = address
                entry["srclen"] = int(length)
            else:
                entry["src"] = source
        runner.policy_rules.append(entry)
    runner.policy_routes = [
        {
            "dst": route[0],
            "dev": route[route.index("dev") + 1],
            "prefsrc": route[route.index("src") + 1],
            **(
                {"gateway": route[route.index("via") + 1]}
                if "via" in route
                else {}
            ),
        }
        for route in policy.route_args(ownership)
    ]


def prepend_chain_rule(
    runner: FakeRunner,
    family: str,
    chain: str,
    rule: str,
) -> None:
    listing = runner.chain_listings.get((family, chain), "")
    runner.chain_listings[(family, chain)] = (
        f"{rule}\n{listing}" if listing else rule
    )


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

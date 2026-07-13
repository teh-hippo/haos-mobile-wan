from __future__ import annotations

import subprocess
from collections.abc import Callable

from .config import GatewayConfig
from .netfilter import Netfilter


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class Firewall:
    FORWARD_CHAIN = "HA_CELLGW"
    INPUT_CHAIN = "HA_CELLGW_LOCAL"
    FORWARD6_CHAIN = "HA_CELLGW6"
    INPUT6_CHAIN = "HA_CELLGW6_LOCAL"
    COMMENT_PREFIX = "ha-cellgw"

    def __init__(self, config: GatewayConfig, run: RunCommand) -> None:
        self.config = config
        self.netfilter = Netfilter(run, self.COMMENT_PREFIX)

    def backend_ok(self) -> bool:
        return self.netfilter.backend_ok()

    def chain_exists(self, family: str, chain: str) -> bool:
        return self.netfilter.chain_exists(family, chain)

    def installed(self, downstream: str | None) -> bool:
        if not downstream:
            return False
        if not all(
            self.netfilter.chain_exists("iptables", chain)
            for chain in (self.FORWARD_CHAIN, self.INPUT_CHAIN)
        ):
            return False
        if not self.netfilter.rule_exists(
            "iptables",
            "DOCKER-USER",
            self.netfilter.jump_rule(
                self.FORWARD_CHAIN,
                f"{self.COMMENT_PREFIX}:jump",
            ),
        ):
            return False
        if not self.netfilter.rule_exists(
            "iptables",
            "INPUT",
            self.netfilter.jump_rule(
                self.INPUT_CHAIN,
                f"{self.COMMENT_PREFIX}:local-jump",
                ["-i", downstream],
            ),
        ):
            return False
        if not self.netfilter.chain_exists("ip6tables", "DOCKER-USER"):
            return True
        return all(
            (
                self.netfilter.chain_exists(
                    "ip6tables",
                    self.FORWARD6_CHAIN,
                ),
                self.netfilter.chain_exists("ip6tables", self.INPUT6_CHAIN),
                self.netfilter.rule_exists(
                    "ip6tables",
                    "DOCKER-USER",
                    self.netfilter.jump_rule(
                        self.FORWARD6_CHAIN,
                        f"{self.COMMENT_PREFIX}:v6-jump",
                    ),
                ),
                self.netfilter.rule_exists(
                    "ip6tables",
                    "INPUT",
                    self.netfilter.jump_rule(
                        self.INPUT6_CHAIN,
                        f"{self.COMMENT_PREFIX}:v6-local-jump",
                        ["-i", downstream],
                    ),
                ),
            )
        )

    def apply(self, downstream: str) -> None:
        self._apply_input_guard(downstream)
        self._apply_forwarding(downstream)
        self._apply_nat_and_mss(downstream)
        self._apply_ipv6_block(downstream)

    def _apply_input_guard(self, downstream: str) -> None:
        tag = self.COMMENT_PREFIX
        self.netfilter.ensure_chain("iptables", self.INPUT_CHAIN)
        self.netfilter.ensure_jump(
            "iptables",
            "INPUT",
            self.INPUT_CHAIN,
            f"{tag}:local-jump",
            ["-i", downstream],
        )
        for rule in (
            [
                "-m",
                "conntrack",
                "--ctstate",
                "ESTABLISHED,RELATED",
                "-j",
                "ACCEPT",
                "-m",
                "comment",
                "--comment",
                f"{tag}:local-established",
            ],
            [
                "-p",
                "udp",
                "--sport",
                "68",
                "--dport",
                "67",
                "-j",
                "ACCEPT",
                "-m",
                "comment",
                "--comment",
                f"{tag}:dhcp-in",
            ],
            [
                "-p",
                "icmp",
                "-j",
                "ACCEPT",
                "-m",
                "comment",
                "--comment",
                f"{tag}:icmp-in",
            ],
            [
                "-j",
                "DROP",
                "-m",
                "comment",
                "--comment",
                f"{tag}:local-drop",
            ],
        ):
            self.netfilter.run(
                "iptables",
                "-A",
                self.INPUT_CHAIN,
                *rule,
            )

    def _apply_forwarding(self, downstream: str) -> None:
        upstream = self.config.upstream_interface
        subnet = self.config.transit_subnet
        tag = self.COMMENT_PREFIX
        self.netfilter.ensure_chain("iptables", self.FORWARD_CHAIN)
        self.netfilter.ensure_jump(
            "iptables",
            "DOCKER-USER",
            self.FORWARD_CHAIN,
            f"{tag}:jump",
        )
        for rule in (
            [
                "-i",
                downstream,
                "-o",
                upstream,
                "-s",
                subnet,
                "-m",
                "conntrack",
                "--ctstate",
                "NEW,ESTABLISHED",
                "-j",
                "ACCEPT",
                "-m",
                "comment",
                "--comment",
                f"{tag}:out",
            ],
            [
                "-i",
                upstream,
                "-o",
                downstream,
                "-d",
                subnet,
                "-m",
                "conntrack",
                "--ctstate",
                "ESTABLISHED,RELATED",
                "-j",
                "ACCEPT",
                "-m",
                "comment",
                "--comment",
                f"{tag}:in",
            ],
            [
                "-i",
                downstream,
                "!",
                "-o",
                upstream,
                "-j",
                "DROP",
                "-m",
                "comment",
                "--comment",
                f"{tag}:drop-out",
            ],
            [
                "!",
                "-i",
                upstream,
                "-o",
                downstream,
                "-j",
                "DROP",
                "-m",
                "comment",
                "--comment",
                f"{tag}:drop-in",
            ],
            ["-j", "RETURN"],
        ):
            self.netfilter.run(
                "iptables",
                "-A",
                self.FORWARD_CHAIN,
                *rule,
            )

    def _apply_nat_and_mss(self, downstream: str) -> None:
        upstream = self.config.upstream_interface
        subnet = self.config.transit_subnet
        tag = self.COMMENT_PREFIX
        self.netfilter.ensure_rule(
            "iptables",
            ["-t", "nat"],
            "POSTROUTING",
            [
                "-s",
                subnet,
                "-o",
                upstream,
                "-j",
                "MASQUERADE",
                "-m",
                "comment",
                "--comment",
                f"{tag}:snat",
            ],
        )
        for direction in ("out", "in"):
            match = (
                ["-i", downstream, "-o", upstream, "-s", subnet]
                if direction == "out"
                else ["-i", upstream, "-o", downstream, "-d", subnet]
            )
            self.netfilter.ensure_rule(
                "iptables",
                ["-t", "mangle"],
                "FORWARD",
                [
                    *match,
                    "-p",
                    "tcp",
                    "--tcp-flags",
                    "SYN,RST",
                    "SYN",
                    "-j",
                    "TCPMSS",
                    "--clamp-mss-to-pmtu",
                    "-m",
                    "comment",
                    "--comment",
                    f"{tag}:mss-{direction}",
                ],
            )

    def _apply_ipv6_block(self, downstream: str) -> None:
        if not self.netfilter.chain_exists("ip6tables", "DOCKER-USER"):
            return
        tag = self.COMMENT_PREFIX
        self.netfilter.ensure_chain("ip6tables", self.INPUT6_CHAIN)
        self.netfilter.ensure_jump(
            "ip6tables",
            "INPUT",
            self.INPUT6_CHAIN,
            f"{tag}:v6-local-jump",
            ["-i", downstream],
        )
        self.netfilter.run(
            "ip6tables",
            "-A",
            self.INPUT6_CHAIN,
            "-j",
            "DROP",
        )

        self.netfilter.ensure_chain("ip6tables", self.FORWARD6_CHAIN)
        self.netfilter.ensure_jump(
            "ip6tables",
            "DOCKER-USER",
            self.FORWARD6_CHAIN,
            f"{tag}:v6-jump",
        )
        self.netfilter.run(
            "ip6tables",
            "-A",
            self.FORWARD6_CHAIN,
            "-i",
            downstream,
            "-j",
            "DROP",
        )
        self.netfilter.run(
            "ip6tables",
            "-A",
            self.FORWARD6_CHAIN,
            "-o",
            downstream,
            "-j",
            "DROP",
        )
        self.netfilter.run(
            "ip6tables",
            "-A",
            self.FORWARD6_CHAIN,
            "-j",
            "RETURN",
        )

    def cleanup(self) -> None:
        for family, table_args, chain in (
            ("iptables", [], "INPUT"),
            ("iptables", [], "DOCKER-USER"),
            ("iptables", ["-t", "nat"], "POSTROUTING"),
            ("iptables", ["-t", "mangle"], "FORWARD"),
            ("ip6tables", [], "INPUT"),
            ("ip6tables", [], "DOCKER-USER"),
        ):
            self.netfilter.delete_tagged_rules(
                family,
                chain,
                table_args,
            )
        self.netfilter.remove_chains(
            "iptables",
            (self.FORWARD_CHAIN, self.INPUT_CHAIN),
        )
        self.netfilter.remove_chains(
            "ip6tables",
            (self.FORWARD6_CHAIN, self.INPUT6_CHAIN),
        )

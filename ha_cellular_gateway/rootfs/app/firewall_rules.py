from __future__ import annotations

from .config import GatewayConfig


class FirewallRules:
    def __init__(self, config: GatewayConfig, comment_prefix: str) -> None:
        self.config = config
        self.comment_prefix = comment_prefix

    def input_rules(self) -> tuple[list[str], ...]:
        tag = self.comment_prefix
        return (
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
        )

    def forward_rules(
        self,
        downstream: str,
        upstream: str | None = None,
    ) -> tuple[list[str], ...]:
        upstream = upstream or self.config.upstream_interface
        subnet = self.config.transit_subnet
        tag = self.comment_prefix
        return (
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
        )

    def nat_rule(self, upstream: str | None = None) -> list[str]:
        upstream = upstream or self.config.upstream_interface
        return [
            "-s",
            self.config.transit_subnet,
            "-o",
            upstream,
            "-j",
            "MASQUERADE",
            "-m",
            "comment",
            "--comment",
            f"{self.comment_prefix}:snat",
        ]

    def mss_rules(
        self,
        downstream: str,
        upstream: str | None = None,
    ) -> tuple[list[str], ...]:
        upstream = upstream or self.config.upstream_interface
        subnet = self.config.transit_subnet
        tag = self.comment_prefix
        return (
            [
                "-i",
                downstream,
                "-o",
                upstream,
                "-s",
                subnet,
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
                f"{tag}:mss-out",
            ],
            [
                "-i",
                upstream,
                "-o",
                downstream,
                "-d",
                subnet,
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
                f"{tag}:mss-in",
            ],
        )

    @staticmethod
    def input6_rules() -> tuple[list[str], ...]:
        return (["-j", "DROP"],)

    @staticmethod
    def forward6_rules(downstream: str) -> tuple[list[str], ...]:
        return (
            ["-i", downstream, "-j", "DROP"],
            ["-o", downstream, "-j", "DROP"],
            ["-j", "RETURN"],
        )

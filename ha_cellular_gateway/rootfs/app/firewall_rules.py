from __future__ import annotations

from .config import GatewayConfig


class FirewallRules:
    def __init__(self, config: GatewayConfig, comment_prefix: str) -> None:
        self.config = config
        self.comment_prefix = comment_prefix

    def _tagged(self, suffix: str, *rule: str) -> list[str]:
        return [
            *rule,
            "-m",
            "comment",
            "--comment",
            f"{self.comment_prefix}:{suffix}",
        ]

    def input_rules(self) -> tuple[list[str], ...]:
        return (
            self._tagged(
                "local-established", "-m", "conntrack", "--ctstate",
                "ESTABLISHED,RELATED", "-j", "ACCEPT",
            ),
            self._tagged(
                "dhcp-in", "-p", "udp", "--sport", "68", "--dport", "67",
                "-j", "ACCEPT",
            ),
            self._tagged("icmp-in", "-p", "icmp", "-j", "ACCEPT"),
            self._tagged("local-drop", "-j", "DROP"),
        )

    def _forward_rule(
        self,
        downstream: str,
        upstream: str,
        *,
        outbound: bool,
    ) -> list[str]:
        if outbound:
            interfaces = ("-i", downstream, "-o", upstream)
            suffix, network_flag, states = "out", "-s", "NEW,ESTABLISHED"
        else:
            interfaces = ("-i", upstream, "-o", downstream)
            suffix, network_flag, states = "in", "-d", "ESTABLISHED,RELATED"
        return self._tagged(
            suffix,
            *interfaces,
            network_flag,
            self.config.transit_subnet,
            "-m",
            "conntrack",
            "--ctstate",
            states,
            "-j",
            "ACCEPT",
        )

    def forward_rules(
        self,
        downstream: str,
        upstream: str | None = None,
    ) -> tuple[list[str], ...]:
        upstream = upstream or self.config.upstream_interface
        return (
            self._forward_rule(downstream, upstream, outbound=True),
            self._forward_rule(downstream, upstream, outbound=False),
            self._tagged(
                "drop-out", "-i", downstream, "!", "-o", upstream, "-j", "DROP",
            ),
            self._tagged(
                "drop-in", "!", "-i", upstream, "-o", downstream, "-j", "DROP",
            ),
            ["-j", "RETURN"],
        )

    def nat_rule(self, upstream: str | None = None) -> list[str]:
        upstream = upstream or self.config.upstream_interface
        return self._tagged(
            "snat", "-s", self.config.transit_subnet, "-o", upstream,
            "-j", "MASQUERADE",
        )

    def _mss_rule(
        self,
        downstream: str,
        upstream: str,
        *,
        outbound: bool,
    ) -> list[str]:
        if outbound:
            interfaces = ("-i", downstream, "-o", upstream)
            suffix, network_flag = "mss-out", "-s"
        else:
            interfaces = ("-i", upstream, "-o", downstream)
            suffix, network_flag = "mss-in", "-d"
        return self._tagged(
            suffix,
            *interfaces,
            network_flag,
            self.config.transit_subnet,
            "-p",
            "tcp",
            "--tcp-flags",
            "SYN,RST",
            "SYN",
            "-j",
            "TCPMSS",
            "--clamp-mss-to-pmtu",
        )

    def mss_rules(
        self,
        downstream: str,
        upstream: str | None = None,
    ) -> tuple[list[str], ...]:
        upstream = upstream or self.config.upstream_interface
        return (
            self._mss_rule(downstream, upstream, outbound=True),
            self._mss_rule(downstream, upstream, outbound=False),
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

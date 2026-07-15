from __future__ import annotations

from .command import RunCommand
from .config import GatewayConfig
from .firewall_rules import FirewallRules
from .netfilter import Netfilter


class Firewall:
    FORWARD_CHAIN = "HA_CELLGW"
    INPUT_CHAIN = "HA_CELLGW_LOCAL"
    FORWARD6_CHAIN = "HA_CELLGW6"
    INPUT6_CHAIN = "HA_CELLGW6_LOCAL"
    COMMENT_PREFIX = "ha-cellgw"

    def __init__(self, config: GatewayConfig, run: RunCommand) -> None:
        self.config = config
        self.netfilter = Netfilter(run, self.COMMENT_PREFIX)
        rules = FirewallRules(config, self.COMMENT_PREFIX)
        self._input_rules = rules.input_rules
        self._forward_rules = rules.forward_rules
        self._nat_rule = rules.nat_rule
        self._mss_rules = rules.mss_rules
        self._input6_rules = rules.input6_rules
        self._forward6_rules = rules.forward6_rules

    def backend_ok(self) -> bool:
        return self.netfilter.backend_ok()

    def chain_exists(self, family: str, chain: str) -> bool:
        return self.netfilter.chain_exists(family, chain)

    def installed(
        self,
        downstream: str | None,
        upstream_interface: str | None = None,
    ) -> bool:
        if not downstream or not self.host_protection_installed(downstream):
            return False
        upstream = upstream_interface or self.config.upstream_interface
        if not all(
            (
                self.netfilter.chain_exists("iptables", self.FORWARD_CHAIN),
                self._jump_installed(
                    "iptables",
                    "DOCKER-USER",
                    self.FORWARD_CHAIN,
                    f"{self.COMMENT_PREFIX}:jump",
                ),
                self.netfilter.chain_matches(
                    "iptables",
                    self.FORWARD_CHAIN,
                    self._forward_rules(downstream, upstream),
                ),
                self.netfilter.rule_exists(
                    "iptables",
                    "POSTROUTING",
                    self._nat_rule(upstream),
                    ["-t", "nat"],
                ),
                all(
                    self.netfilter.rule_exists(
                        "iptables",
                        "FORWARD",
                        rule,
                        ["-t", "mangle"],
                    )
                    for rule in self._mss_rules(downstream, upstream)
                ),
            )
        ):
            return False
        if not self.netfilter.chain_exists("ip6tables", "DOCKER-USER"):
            return True
        return all(
            (
                self._ipv6_input_guard_installed(downstream),
                self.netfilter.chain_exists("ip6tables", self.FORWARD6_CHAIN),
                self._jump_installed(
                    "ip6tables",
                    "DOCKER-USER",
                    self.FORWARD6_CHAIN,
                    f"{self.COMMENT_PREFIX}:v6-jump",
                ),
                self.netfilter.chain_matches(
                    "ip6tables",
                    self.FORWARD6_CHAIN,
                    self._forward6_rules(downstream),
                ),
            )
        )

    def host_protection_installed(self, downstream: str | None) -> bool:
        return bool(
            downstream
            and self._input_guard_installed(downstream)
            and (
                not self.netfilter.chain_exists("ip6tables", "DOCKER-USER")
                or self._ipv6_input_guard_installed(downstream)
            )
        )

    def _ensure_chain_rules(
        self,
        family: str,
        chain: str,
        rules: tuple[list[str], ...],
    ) -> None:
        if self.netfilter.chain_matches(family, chain, rules):
            return
        self.netfilter.ensure_chain(family, chain)
        for rule in rules:
            self.netfilter.run(family, "-A", chain, *rule)

    def _input_guard_installed(self, downstream: str) -> bool:
        return all(
            (
                self.netfilter.chain_exists("iptables", self.INPUT_CHAIN),
                self._jump_installed(
                    "iptables",
                    "INPUT",
                    self.INPUT_CHAIN,
                    f"{self.COMMENT_PREFIX}:local-jump",
                    ["-i", downstream],
                ),
                self.netfilter.chain_matches(
                    "iptables",
                    self.INPUT_CHAIN,
                    self._input_rules(),
                ),
            )
        )

    def _ipv6_input_guard_installed(self, downstream: str) -> bool:
        return all(
            (
                self.netfilter.chain_exists("ip6tables", self.INPUT6_CHAIN),
                self._jump_installed(
                    "ip6tables",
                    "INPUT",
                    self.INPUT6_CHAIN,
                    f"{self.COMMENT_PREFIX}:v6-local-jump",
                    ["-i", downstream],
                ),
                self.netfilter.chain_matches(
                    "ip6tables",
                    self.INPUT6_CHAIN,
                    self._input6_rules(),
                ),
            )
        )

    def _jump_installed(
        self,
        family: str,
        parent: str,
        child: str,
        comment: str,
        match: list[str] | None = None,
    ) -> bool:
        return self.netfilter.rule_is_first_unique(
            family,
            parent,
            self.netfilter.jump_rule(child, comment, match),
        )

    def apply(self, downstream: str, upstream_interface: str | None = None) -> None:
        upstream = upstream_interface or self.config.upstream_interface
        self._apply_input_guard(downstream)
        self._apply_forwarding(downstream, upstream)
        self._apply_nat_and_mss(downstream, upstream)
        self._apply_ipv6_block(downstream)

    def protect_host(self, downstream: str) -> None:
        self._apply_input_guard(downstream)
        self._apply_ipv6_local_block(downstream)

    def _apply_input_guard(self, downstream: str) -> None:
        self._ensure_chain_rules(
            "iptables",
            self.INPUT_CHAIN,
            self._input_rules(),
        )
        self.netfilter.ensure_jump(
            "iptables",
            "INPUT",
            self.INPUT_CHAIN,
            f"{self.COMMENT_PREFIX}:local-jump",
            ["-i", downstream],
        )

    def _apply_forwarding(self, downstream: str, upstream: str) -> None:
        self._ensure_chain_rules(
            "iptables",
            self.FORWARD_CHAIN,
            self._forward_rules(downstream, upstream),
        )
        self.netfilter.ensure_jump(
            "iptables",
            "DOCKER-USER",
            self.FORWARD_CHAIN,
            f"{self.COMMENT_PREFIX}:jump",
        )

    def _apply_nat_and_mss(self, downstream: str, upstream: str) -> None:
        self.netfilter.ensure_rule(
            "iptables",
            ["-t", "nat"],
            "POSTROUTING",
            self._nat_rule(upstream),
        )
        for rule in self._mss_rules(downstream, upstream):
            self.netfilter.ensure_rule(
                "iptables",
                ["-t", "mangle"],
                "FORWARD",
                rule,
            )

    def _apply_ipv6_block(self, downstream: str) -> None:
        self._apply_ipv6_local_block(downstream)
        if not self.netfilter.chain_exists("ip6tables", "DOCKER-USER"):
            return
        self._ensure_chain_rules(
            "ip6tables",
            self.FORWARD6_CHAIN,
            self._forward6_rules(downstream),
        )
        self.netfilter.ensure_jump(
            "ip6tables",
            "DOCKER-USER",
            self.FORWARD6_CHAIN,
            f"{self.COMMENT_PREFIX}:v6-jump",
        )

    def _apply_ipv6_local_block(self, downstream: str) -> None:
        if not self.netfilter.chain_exists("ip6tables", "DOCKER-USER"):
            return
        self._ensure_chain_rules(
            "ip6tables",
            self.INPUT6_CHAIN,
            self._input6_rules(),
        )
        self.netfilter.ensure_jump(
            "ip6tables",
            "INPUT",
            self.INPUT6_CHAIN,
            f"{self.COMMENT_PREFIX}:v6-local-jump",
            ["-i", downstream],
        )

    def cleanup(self, preserved_downstream: str | None = None) -> None:
        for family, table_args, chain in (
            ("iptables", [], "DOCKER-USER"),
            ("iptables", ["-t", "nat"], "POSTROUTING"),
            ("iptables", ["-t", "mangle"], "FORWARD"),
            ("ip6tables", [], "DOCKER-USER"),
        ):
            self.netfilter.delete_tagged_rules(
                family,
                chain,
                table_args,
            )
        self.netfilter.remove_chains("iptables", (self.FORWARD_CHAIN,))
        self.netfilter.remove_chains("ip6tables", (self.FORWARD6_CHAIN,))
        if preserved_downstream:
            return
        for family, chain in (("iptables", "INPUT"), ("ip6tables", "INPUT")):
            self.netfilter.delete_tagged_rules(family, chain)
        self.netfilter.remove_chains("iptables", (self.INPUT_CHAIN,))
        self.netfilter.remove_chains("ip6tables", (self.INPUT6_CHAIN,))

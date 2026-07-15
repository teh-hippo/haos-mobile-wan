from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .firewall import Firewall


def firewall_installed(
    firewall: Firewall,
    downstream: str | None,
    upstream_interface: str | None = None,
) -> bool:
    if not downstream or not host_protection_installed(firewall, downstream):
        return False
    upstream = upstream_interface or firewall.config.upstream_interface
    if not _ipv4_forwarding_installed(firewall, downstream, upstream):
        return False
    if not firewall.netfilter.chain_exists("ip6tables", "DOCKER-USER"):
        return True
    return _ipv6_forwarding_installed(firewall, downstream)


def host_protection_installed(firewall: Firewall, downstream: str | None) -> bool:
    return bool(
        downstream
        and _input_guard_installed(firewall, downstream)
        and (
            not firewall.netfilter.chain_exists("ip6tables", "DOCKER-USER")
            or _ipv6_input_guard_installed(firewall, downstream)
        )
    )


def jump_installed(
    firewall: Firewall,
    family: str,
    parent: str,
    child: str,
    comment: str,
    match: list[str] | None = None,
) -> bool:
    return firewall.netfilter.rule_is_first_unique(
        family,
        parent,
        firewall.netfilter.jump_rule(child, comment, match),
    )


def _ipv4_forwarding_installed(
    firewall: Firewall,
    downstream: str,
    upstream: str,
) -> bool:
    return all(
        (
            firewall.netfilter.chain_exists("iptables", firewall.FORWARD_CHAIN),
            jump_installed(
                firewall,
                "iptables",
                "DOCKER-USER",
                firewall.FORWARD_CHAIN,
                f"{firewall.COMMENT_PREFIX}:jump",
            ),
            firewall.netfilter.chain_matches(
                "iptables",
                firewall.FORWARD_CHAIN,
                firewall._forward_rules(downstream, upstream),
            ),
            firewall.netfilter.rule_exists(
                "iptables",
                "POSTROUTING",
                firewall._nat_rule(upstream),
                ["-t", "nat"],
            ),
            all(
                firewall.netfilter.rule_exists(
                    "iptables",
                    "FORWARD",
                    rule,
                    ["-t", "mangle"],
                )
                for rule in firewall._mss_rules(downstream, upstream)
            ),
        )
    )


def _ipv6_forwarding_installed(firewall: Firewall, downstream: str) -> bool:
    return all(
        (
            _ipv6_input_guard_installed(firewall, downstream),
            firewall.netfilter.chain_exists("ip6tables", firewall.FORWARD6_CHAIN),
            jump_installed(
                firewall,
                "ip6tables",
                "DOCKER-USER",
                firewall.FORWARD6_CHAIN,
                f"{firewall.COMMENT_PREFIX}:v6-jump",
            ),
            firewall.netfilter.chain_matches(
                "ip6tables",
                firewall.FORWARD6_CHAIN,
                firewall._forward6_rules(downstream),
            ),
        )
    )


def _input_guard_installed(firewall: Firewall, downstream: str) -> bool:
    return all(
        (
            firewall.netfilter.chain_exists("iptables", firewall.INPUT_CHAIN),
            jump_installed(
                firewall,
                "iptables",
                "INPUT",
                firewall.INPUT_CHAIN,
                f"{firewall.COMMENT_PREFIX}:local-jump",
                ["-i", downstream],
            ),
            firewall.netfilter.chain_matches(
                "iptables",
                firewall.INPUT_CHAIN,
                firewall._input_rules(),
            ),
        )
    )


def _ipv6_input_guard_installed(firewall: Firewall, downstream: str) -> bool:
    return all(
        (
            firewall.netfilter.chain_exists("ip6tables", firewall.INPUT6_CHAIN),
            jump_installed(
                firewall,
                "ip6tables",
                "INPUT",
                firewall.INPUT6_CHAIN,
                f"{firewall.COMMENT_PREFIX}:v6-local-jump",
                ["-i", downstream],
            ),
            firewall.netfilter.chain_matches(
                "ip6tables",
                firewall.INPUT6_CHAIN,
                firewall._input6_rules(),
            ),
        )
    )

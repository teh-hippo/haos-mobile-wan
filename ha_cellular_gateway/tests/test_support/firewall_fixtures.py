"""Realistic firewall/policy state fixtures for gateway integration tests.

These builders seed a ``FakeRunner``'s firewall and route handlers with the
chain listings, rule-existence checks, and policy rules/routes that a fully
applied ``Firewall``/``PolicyRouting`` install would leave behind, so tests
can assert idempotent no-op behaviour on top of a realistic baseline.
"""

from __future__ import annotations

from rootfs.app.firewall import Firewall
from rootfs.app.policy import PolicyRouting
from rootfs.app.upstream_models import ResolvedUpstream

from .runner import FakeRunner


def install_realistic_firewall_state(
    runner: FakeRunner,
    firewall: Firewall,
    downstream: str,
    upstream: str | None = None,
) -> None:
    upstream = upstream or firewall.config.upstream_interface
    subnet = firewall.config.transit_subnet
    runner.firewall.rule_checks.update(
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
    runner.firewall.chain_listings.update(
        {
            (
                "iptables",
                "INPUT",
            ): "\n".join(
                (
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:local-jump -j {firewall.INPUT_CHAIN}",
                )
            ),
            (
                "iptables",
                "DOCKER-USER",
            ): "\n".join(
                (
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:jump -j {firewall.FORWARD_CHAIN}",
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
                    "-A HA_CELLGW_LOCAL -p icmp -m comment --comment ha-cellgw:icmp-in -j ACCEPT",
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
                    f"-A HA_CELLGW -i {downstream} ! -o {upstream} -m comment --comment ha-cellgw:drop-out -j DROP",
                    f"-A HA_CELLGW ! -i {upstream} -o {downstream} -m comment --comment ha-cellgw:drop-in -j DROP",
                    "-A HA_CELLGW -j RETURN",
                )
            ),
            (
                "ip6tables",
                "INPUT",
            ): "\n".join(
                (
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:v6-local-jump -j {firewall.INPUT6_CHAIN}",
                )
            ),
            (
                "ip6tables",
                "DOCKER-USER",
            ): "\n".join(
                (
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:v6-jump -j {firewall.FORWARD6_CHAIN}",
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
    policy: PolicyRouting,
    downstream: str,
    upstream: ResolvedUpstream | None = None,
) -> None:
    ownership = policy.ownership(downstream, upstream)
    runner.routes.policy_rules = []
    for rule in policy.rule_args(ownership):
        entry: dict[str, object] = {
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
        runner.routes.policy_rules.append(entry)
    runner.routes.policy_routes = [
        {
            "dst": route[0],
            "dev": route[route.index("dev") + 1],
            "prefsrc": route[route.index("src") + 1],
            **({"gateway": route[route.index("via") + 1]} if "via" in route else {}),
        }
        for route in policy.route_args(ownership)
    ]


def prepend_chain_rule(
    runner: FakeRunner,
    family: str,
    chain: str,
    rule: str,
) -> None:
    listing = runner.firewall.chain_listings.get((family, chain), "")
    runner.firewall.chain_listings[(family, chain)] = (
        f"{rule}\n{listing}" if listing else rule
    )

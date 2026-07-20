from __future__ import annotations

import ipaddress

from .command import RunCommand, run_json, run_json_table
from .config import GatewayConfig
from .errors import GatewayError
from .policy_match import (
    route_descriptor,
    route_descriptor_from_args,
    route_present,
    rule_matches,
    rule_present,
)
from .upstream_models import ResolvedUpstream, configured_upstream


class PolicyRouting:
    RULE_PRIORITIES = (20100, 20110, 20120)

    def __init__(self, config: GatewayConfig, run: RunCommand) -> None:
        self.config = config
        self.run = run

    def ownership(
        self,
        downstream: str,
        upstream: ResolvedUpstream | None = None,
    ) -> dict[str, object]:
        current = upstream or configured_upstream(self.config)
        return {
            "downstream": downstream,
            "downstream_address": self.config.downstream_address,
            "transit_subnet": self.config.transit_subnet,
            "upstream_interface": current.interface,
            "upstream_address": current.address,
            "upstream_gateway": current.gateway,
            "routing_table": self.config.routing_table,
        }

    @staticmethod
    def _value(ownership: dict[str, object], key: str) -> str:
        value = ownership.get(key)
        if value is None:
            raise GatewayError(f"Persistent ownership state is missing {key}")
        return str(value)

    def rule_args(
        self,
        ownership: dict[str, object],
    ) -> tuple[list[str], ...]:
        downstream = self._value(ownership, "downstream")
        transit = self._value(ownership, "transit_subnet")
        upstream_address = self._value(ownership, "upstream_address")
        upstream_ip = str(ipaddress.ip_interface(upstream_address).ip)
        table = self._value(ownership, "routing_table")
        return (
            ["pref", "20100", "iif", downstream, "lookup", table],
            ["pref", "20110", "from", transit, "lookup", table],
            ["pref", "20120", "from", f"{upstream_ip}/32", "lookup", table],
        )

    def route_args(
        self,
        ownership: dict[str, object],
    ) -> tuple[list[str], ...]:
        downstream = self._value(ownership, "downstream")
        downstream_address = self._value(ownership, "downstream_address")
        downstream_interface = ipaddress.ip_interface(downstream_address)
        upstream_interface = self._value(ownership, "upstream_interface")
        upstream_address = self._value(ownership, "upstream_address")
        upstream_interface_address = ipaddress.ip_interface(upstream_address)
        upstream_gateway = self._value(ownership, "upstream_gateway")
        table = self._value(ownership, "routing_table")
        return (
            [
                str(upstream_interface_address.network),
                "dev",
                upstream_interface,
                "src",
                str(upstream_interface_address.ip),
                "table",
                table,
            ],
            [
                str(downstream_interface.network),
                "dev",
                downstream,
                "src",
                str(downstream_interface.ip),
                "table",
                table,
            ],
            [
                "default",
                "via",
                upstream_gateway,
                "dev",
                upstream_interface,
                "src",
                str(upstream_interface_address.ip),
                "table",
                table,
            ],
        )

    def conflicts(
        self,
        downstream: str,
        upstream: ResolvedUpstream | None = None,
    ) -> list[str]:
        ownership = self.ownership(downstream, upstream)
        return self._rule_conflicts(ownership) + self._route_conflicts(ownership)

    def installed(
        self,
        downstream: str | None,
        upstream: ResolvedUpstream | None = None,
    ) -> bool:
        if not downstream:
            return False
        ownership = self.ownership(downstream, upstream)
        rules = run_json(self.run, "ip", "-j", "rule", "show")
        routes = run_json_table(
            self.run,
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            str(self.config.routing_table),
        )
        return all(
            rule_present(rules, rule) for rule in self.rule_args(ownership)
        ) and all(route_present(routes, route) for route in self.route_args(ownership))

    def _rule_conflicts(
        self,
        ownership: dict[str, object],
    ) -> list[str]:
        rules = run_json(self.run, "ip", "-j", "rule", "show")
        conflicts: list[str] = []
        table = self._value(ownership, "routing_table")
        expected_rules = self.rule_args(ownership)
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, dict):
                continue
            priority = int(rule.get("priority", -1))
            rule_table = str(rule.get("table", rule.get("lookup", "")))
            if priority in self.RULE_PRIORITIES and not any(
                rule_matches(rule, expected) for expected in expected_rules
            ):
                conflicts.append(f"Policy priority {priority} is already in use")
                continue
            if rule_table == table and not any(
                rule_matches(rule, expected) for expected in expected_rules
            ):
                conflicts.append(
                    f"Routing table {self.config.routing_table} already has a foreign policy rule"
                )
        return conflicts

    def _route_conflicts(
        self,
        ownership: dict[str, object],
    ) -> list[str]:
        routes = run_json_table(
            self.run,
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            self._value(ownership, "routing_table"),
        )
        expected = {
            route_descriptor_from_args(route) for route in self.route_args(ownership)
        }
        conflicts: list[str] = []
        for route in routes if isinstance(routes, list) else []:
            if route_descriptor(route) not in expected:
                conflicts.append(
                    f"Routing table {self.config.routing_table} contains an unexpected route"
                )
        return conflicts

    def apply(
        self,
        downstream: str,
        upstream: ResolvedUpstream | None = None,
    ) -> dict[str, object]:
        ownership = self.ownership(downstream, upstream)
        self.cleanup(ownership)
        for route in self.route_args(ownership):
            self.run("ip", "route", "replace", *route)
        for rule in self.rule_args(ownership):
            self.run("ip", "rule", "add", *rule)
        return ownership

    def cleanup(self, ownership: dict[str, object] | None) -> None:
        if not ownership:
            return
        for rule in self.rule_args(ownership):
            while self.run("ip", "rule", "del", *rule, check=False).returncode == 0:
                pass
        for route in reversed(self.route_args(ownership)):
            while (
                self.run(
                    "ip",
                    "route",
                    "del",
                    *route,
                    check=False,
                ).returncode
                == 0
            ):
                pass

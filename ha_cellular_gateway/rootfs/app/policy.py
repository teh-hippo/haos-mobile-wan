from __future__ import annotations

import ipaddress
import json
import subprocess
from collections.abc import Callable

from .config import GatewayConfig
from .errors import GatewayError
from .upstream import ResolvedUpstream, configured_upstream


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class PolicyRouting:
    RULE_PRIORITIES = (20100, 20110, 20120)

    def __init__(self, config: GatewayConfig, run: RunCommand) -> None:
        self.config = config
        self.run = run

    def _read_json(self, *args: str) -> object:
        result = self.run(*args)
        return json.loads(result.stdout or "[]")

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
        conflicts = self._rule_conflicts(downstream, ownership)
        conflicts.extend(self._route_conflicts(downstream, ownership))
        return conflicts

    def _rule_conflicts(
        self,
        downstream: str,
        ownership: dict[str, object],
    ) -> list[str]:
        rules = self._read_json("ip", "-j", "rule", "show")
        conflicts: list[str] = []
        table = self._value(ownership, "routing_table")
        upstream_address = self._value(ownership, "upstream_address")
        upstream_ip = str(ipaddress.ip_interface(upstream_address).ip)
        expected = {
            20100: {"iifname": downstream},
            20110: {"src": self.config.transit_subnet},
            20120: {"src": f"{upstream_ip}/32"},
        }
        for rule in rules if isinstance(rules, list) else []:
            priority = int(rule.get("priority", -1))
            if priority not in self.RULE_PRIORITIES:
                continue
            expected_fields = expected[priority]
            source = str(rule.get("src", ""))
            source_length = rule.get("srclen")
            if source not in {"", "all"} and source_length is not None:
                source = f"{source}/{source_length}"
            expected_source = str(expected_fields.get("src", ""))
            source_matches = not expected_source or source in {
                expected_source,
                expected_source.removesuffix("/32"),
            }
            interface_matches = (
                "iifname" not in expected_fields
                or str(rule.get("iifname", rule.get("iif", "")))
                == expected_fields["iifname"]
            )
            rule_table = str(rule.get("table", rule.get("lookup", "")))
            if (
                rule_table != table
                or not source_matches
                or not interface_matches
            ):
                conflicts.append(f"Policy priority {priority} is already in use")
        return conflicts

    def _route_conflicts(
        self,
        downstream: str,
        ownership: dict[str, object],
    ) -> list[str]:
        routes = self._read_json(
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            self._value(ownership, "routing_table"),
        )
        upstream = ResolvedUpstream(
            mode=self.config.upstream_mode,
            interface=self._value(ownership, "upstream_interface"),
            address=self._value(ownership, "upstream_address"),
            gateway=self._value(ownership, "upstream_gateway"),
        )
        expected = {
            (
                upstream.network,
                upstream.interface,
                upstream.ip,
                "",
            ),
            (
                self.config.downstream_network,
                downstream,
                self.config.downstream_ip,
                "",
            ),
            (
                "default",
                upstream.interface,
                upstream.ip,
                upstream.gateway,
            ),
        }
        conflicts: list[str] = []
        for route in routes if isinstance(routes, list) else []:
            descriptor = (
                str(route.get("dst", "default")),
                str(route.get("dev", "")),
                str(route.get("prefsrc", route.get("src", ""))),
                str(route.get("gateway", "")),
            )
            if descriptor not in expected:
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
            while self.run(
                "ip",
                "route",
                "del",
                *route,
                check=False,
            ).returncode == 0:
                pass

from __future__ import annotations

import ipaddress
import json
import subprocess
from collections.abc import Callable

from .config import GatewayConfig
from .errors import GatewayError


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class PolicyRouting:
    RULE_PRIORITIES = (20100, 20110, 20120)

    def __init__(self, config: GatewayConfig, run: RunCommand) -> None:
        self.config = config
        self.run = run

    def _read_json(self, *args: str) -> object:
        result = self.run(*args)
        return json.loads(result.stdout or "[]")

    def ownership(self, downstream: str) -> dict[str, object]:
        return {
            "downstream": downstream,
            "downstream_address": self.config.downstream_address,
            "transit_subnet": self.config.transit_subnet,
            "upstream_interface": self.config.upstream_interface,
            "upstream_address": self.config.upstream_address,
            "upstream_gateway": self.config.upstream_gateway,
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

    def conflicts(self, downstream: str) -> list[str]:
        conflicts = self._rule_conflicts(downstream)
        conflicts.extend(self._route_conflicts(downstream))
        return conflicts

    def installed(self, downstream: str | None) -> bool:
        if not downstream:
            return False
        ownership = self.ownership(downstream)
        rules = self._read_json("ip", "-j", "rule", "show")
        routes = self._read_json(
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            str(self.config.routing_table),
        )
        return all(
            self._rule_present(rules, rule)
            for rule in self.rule_args(ownership)
        ) and all(
            self._route_present(routes, route)
            for route in self.route_args(ownership)
        )

    @staticmethod
    def _rule_present(rules: object, expected: list[str]) -> bool:
        if not isinstance(rules, list):
            return False
        priority = int(expected[expected.index("pref") + 1])
        table = expected[expected.index("lookup") + 1]
        interface = (
            expected[expected.index("iif") + 1]
            if "iif" in expected
            else None
        )
        source = (
            expected[expected.index("from") + 1]
            if "from" in expected
            else ""
        )
        allowed_sources = {source}
        if source.endswith("/32"):
            allowed_sources.add(source.removesuffix("/32"))

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            actual_source = str(rule.get("src", ""))
            actual_length = rule.get("srclen")
            if actual_source not in {"", "all"} and actual_length is not None:
                actual_source = f"{actual_source}/{actual_length}"
            if (
                int(rule.get("priority", -1)) == priority
                and str(rule.get("table", rule.get("lookup", ""))) == table
                and (
                    interface is None
                    or str(rule.get("iifname", rule.get("iif", ""))) == interface
                )
                and (
                    not source
                    and actual_source in {"", "all"}
                    or actual_source in allowed_sources
                )
            ):
                return True
        return False

    @staticmethod
    def _route_present(routes: object, expected: list[str]) -> bool:
        if not isinstance(routes, list):
            return False
        destination = expected[0]
        interface = expected[expected.index("dev") + 1]
        source = expected[expected.index("src") + 1]
        gateway = expected[expected.index("via") + 1] if "via" in expected else ""
        descriptor = (destination, interface, source, gateway)
        return any(
            isinstance(route, dict)
            and (
                str(route.get("dst", "default")),
                str(route.get("dev", "")),
                str(route.get("prefsrc", route.get("src", ""))),
                str(route.get("gateway", "")),
            )
            == descriptor
            for route in routes
        )

    def _rule_conflicts(self, downstream: str) -> list[str]:
        rules = self._read_json("ip", "-j", "rule", "show")
        conflicts: list[str] = []
        table = str(self.config.routing_table)
        expected = {
            20100: {"iifname": downstream},
            20110: {"src": self.config.transit_subnet},
            20120: {"src": f"{self.config.upstream_ip}/32"},
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

    def _route_conflicts(self, downstream: str) -> list[str]:
        routes = self._read_json(
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            str(self.config.routing_table),
        )
        expected = {
            (
                self.config.upstream_network,
                self.config.upstream_interface,
                self.config.upstream_ip,
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
                self.config.upstream_interface,
                self.config.upstream_ip,
                self.config.upstream_gateway,
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

    def apply(self, downstream: str) -> dict[str, object]:
        ownership = self.ownership(downstream)
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

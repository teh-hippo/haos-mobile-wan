from __future__ import annotations

import ipaddress

from .command import RunCommand, run_json, run_json_table
from .upstream_models import ResolvedUpstream


def main_default_present(run: RunCommand, interface: str) -> bool:
    routes = run_json(
        run,
        "ip",
        "-4",
        "-j",
        "route",
        "show",
        "table",
        "main",
        "default",
    )
    return any(
        isinstance(route, dict)
        and route.get("dev") == interface
        and route.get("dst") == "default"
        for route in routes if isinstance(routes, list)
    )


def rule_selects_table(run: RunCommand, table: int) -> bool:
    rules = run_json(run, "ip", "-j", "rule", "show")
    wanted = str(table)
    return any(
        isinstance(rule, dict)
        and str(rule.get("table", rule.get("lookup", ""))) == wanted
        for rule in rules if isinstance(rules, list)
    )


def table_routes_state(
    run: RunCommand,
    table: int,
    interface: str,
    upstream: ResolvedUpstream,
) -> str:
    routes = run_json_table(
        run,
        "ip",
        "-4",
        "-j",
        "route",
        "show",
        "table",
        str(table),
    )
    entries = [route for route in routes if isinstance(route, dict)]
    if not entries:
        return "waiting"
    address = str(ipaddress.ip_interface(upstream.address).ip)
    expected = {
        ("default", interface, upstream.gateway, address),
        (upstream.network, interface, "", address),
    }
    actual = {
        (
            str(route.get("dst", "default")),
            str(route.get("dev", "")),
            str(route.get("gateway", "")),
            str(route.get("prefsrc", address)),
        )
        for route in entries
    }
    if len(entries) != len(actual) or not actual.issubset(expected):
        return "invalid"
    return "ready" if actual == expected else "waiting"

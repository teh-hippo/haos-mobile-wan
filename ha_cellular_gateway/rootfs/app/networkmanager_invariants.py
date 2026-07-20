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
    if not isinstance(routes, list):
        return False
    return any(
        isinstance(route, dict)
        and route.get("dev") == interface
        and route.get("dst") == "default"
        for route in routes
    )


def rule_selects_table(run: RunCommand, table: int) -> bool:
    rules = run_json(run, "ip", "-j", "rule", "show")
    if not isinstance(rules, list):
        return False
    wanted = str(table)
    return any(
        isinstance(rule, dict)
        and str(rule.get("table", rule.get("lookup", ""))) == wanted
        for rule in rules
    )


def networkmanager_routes(
    run: RunCommand,
    table: int,
) -> list[dict[str, object]]:
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
    if not isinstance(routes, list):
        return []
    return [route for route in routes if isinstance(route, dict)]


def table_gateway(
    routes: list[dict[str, object]],
    interface: str,
) -> tuple[str | None, str]:
    if any(route.get("dev") != interface for route in routes):
        return None, "invalid"
    defaults = [
        route
        for route in routes
        if route.get("dst") == "default" and route.get("dev") == interface
    ]
    if not defaults:
        return None, "waiting"
    gateways = {
        str(route.get("gateway", "")) for route in defaults if route.get("gateway")
    }
    if len(defaults) != 1 or len(gateways) != 1:
        return None, "invalid"
    return gateways.pop(), "ready"


def table_routes_state(
    routes: list[dict[str, object]],
    interface: str,
    upstream: ResolvedUpstream,
) -> str:
    if not routes:
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
        for route in routes
    }
    if len(routes) != len(actual) or not actual.issubset(expected):
        return "invalid"
    return "ready" if actual == expected else "waiting"

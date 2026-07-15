from __future__ import annotations


def rule_present(rules: object, expected: list[str]) -> bool:
    if not isinstance(rules, list):
        return False
    return any(
        isinstance(rule, dict) and rule_matches(rule, expected)
        for rule in rules
    )


def rule_matches(rule: dict[str, object], expected: list[str]) -> bool:
    priority = int(expected[expected.index("pref") + 1])
    table = expected[expected.index("lookup") + 1]
    interface = expected[expected.index("iif") + 1] if "iif" in expected else None
    source = expected[expected.index("from") + 1] if "from" in expected else ""
    allowed_sources = {source}
    if source.endswith("/32"):
        allowed_sources.add(source.removesuffix("/32"))
    actual_source = str(rule.get("src", ""))
    actual_length = rule.get("srclen")
    if actual_source not in {"", "all"} and actual_length is not None:
        actual_source = f"{actual_source}/{actual_length}"
    return (
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
    )


def route_present(routes: object, expected: list[str]) -> bool:
    if not isinstance(routes, list):
        return False
    return any(
        isinstance(route, dict) and route_matches(route, expected)
        for route in routes
    )


def route_matches(route: dict[str, object], expected: list[str]) -> bool:
    return route_descriptor(route) == route_descriptor_from_args(expected)


def route_descriptor(route: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(route.get("dst", "default")),
        str(route.get("dev", "")),
        str(route.get("prefsrc", route.get("src", ""))),
        str(route.get("gateway", "")),
    )


def route_descriptor_from_args(route: list[str]) -> tuple[str, str, str, str]:
    return (
        route[0],
        route[route.index("dev") + 1],
        route[route.index("src") + 1],
        route[route.index("via") + 1] if "via" in route else "",
    )

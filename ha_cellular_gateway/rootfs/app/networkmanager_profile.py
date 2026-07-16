from __future__ import annotations

import re

PROFILE_NAME = "haos-mobile-wan-iphone"
PROFILE_UUID = "795b0402-f4b8-571b-91b0-2ab6816add52"
ROUTE_TABLE = 202

MODIFY_SETTINGS: tuple[tuple[str, str], ...] = (
    ("connection.interface-name", ""),
    ("connection.autoconnect", "yes"),
    ("connection.autoconnect-priority", "999"),
    ("connection.autoconnect-retries", "0"),
    ("match.driver", "ipheth"),
    ("ipv4.method", "auto"),
    ("ipv4.route-table", str(ROUTE_TABLE)),
    ("ipv4.ignore-auto-dns", "yes"),
    ("ipv4.never-default", "no"),
    ("ipv4.may-fail", "no"),
    ("ipv4.dhcp-timeout", "45"),
    ("ipv6.method", "disabled"),
    ("802-3-ethernet.cloned-mac-address", "preserve"),
)
EXPECTED_SETTINGS: dict[str, str] = {
    "connection.uuid": PROFILE_UUID,
    "connection.type": "802-3-ethernet",
    **dict(MODIFY_SETTINGS),
}
READ_FIELDS: tuple[str, ...] = tuple(EXPECTED_SETTINGS)

_ENUM_PATTERN = re.compile(r"^\d+\s*\((.+)\)$")


def normalise_setting(value: str) -> str:
    stripped = value.strip()
    if stripped == "--":
        return ""
    match = _ENUM_PATTERN.match(stripped)
    return match.group(1) if match else stripped

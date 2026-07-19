from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def interface_driver(interface: Path) -> str | None:
    try:
        return (interface / "device" / "driver").resolve().name
    except OSError:
        return None


def interfaces_by_driver(
    root: Path,
    drivers: Iterable[str],
    *,
    excluded: Iterable[str] = (),
) -> list[str]:
    if not root.exists():
        return []
    allowed = set(drivers)
    blocked = set(excluded)
    matches: list[str] = []
    for interface in root.iterdir():
        if interface.name in blocked:
            continue
        driver = interface_driver(interface)
        if driver in allowed:
            matches.append(interface.name)
    return sorted(matches)


def interface_carrier(root: Path, interface: str) -> bool | None:
    try:
        value = (root / interface / "carrier").read_text(encoding="utf-8")
    except OSError:
        return None
    return value.strip() == "1"

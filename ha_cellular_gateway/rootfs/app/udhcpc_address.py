from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .upstream_lease import (
    load_app_lease_record,
    write_app_lease_record,
)


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
INTERFACE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}")


def normalise_interface(value: str) -> str:
    if not INTERFACE_PATTERN.fullmatch(value):
        raise ValueError("DHCP interface name is invalid")
    return value


def _load_record(path: Path) -> tuple[str, str, str] | None:
    record = load_app_lease_record(path)
    if record is None and not path.exists():
        return None
    if record is None:
        raise ValueError("iPhone USB lease record is invalid")
    try:
        interface = normalise_interface(record[0])
        address = str(ipaddress.IPv4Interface(record[1]))
        gateway = str(ipaddress.IPv4Address(record[2]))
    except (TypeError, ValueError) as err:
        raise ValueError("iPhone USB lease record is invalid") from err
    return interface, address, gateway


def _address_present(
    run: RunCommand,
    interface: str,
    address: str,
) -> bool:
    result = run(
        ["ip", "-4", "-j", "address", "show", "dev", interface],
        check=False,
        timeout=5,
    )
    if result.returncode != 0:
        detail = f"{result.stdout}\n{result.stderr}".lower()
        if "does not exist" in detail or "cannot find device" in detail:
            return False
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    target = ipaddress.IPv4Interface(address)
    for item in json.loads(result.stdout or "[]"):
        for entry in item.get("addr_info", []):
            if entry.get("family") != "inet":
                continue
            current = ipaddress.IPv4Interface(
                f"{entry['local']}/{entry['prefixlen']}"
            )
            if current == target:
                return True
    return False


def _delete_address(
    run: RunCommand,
    interface: str,
    address: str,
) -> None:
    result = run(
        ["ip", "-4", "address", "del", address, "dev", interface],
        check=False,
        timeout=5,
    )
    if result.returncode == 0 or not _address_present(
        run,
        interface,
        address,
    ):
        return
    raise subprocess.CalledProcessError(
        result.returncode,
        result.args,
        output=result.stdout,
        stderr=result.stderr,
    )


def deconfigure(path: Path, run: RunCommand) -> None:
    record = _load_record(path)
    if record is not None:
        _delete_address(run, record[0], record[1])
        path.unlink(missing_ok=True)


def configure(
    path: Path,
    lease: tuple[str, str, str],
    run: RunCommand,
) -> None:
    interface, address, gateway = lease
    previous = _load_record(path)
    replaced = bool(
        previous
        and previous[0] == interface
        and previous[1] == address
    )
    added = False
    removed_previous = False
    try:
        if replaced:
            run(
                ["ip", "-4", "address", "replace", address, "dev", interface],
                check=True,
                timeout=5,
            )
        else:
            if previous:
                _delete_address(run, previous[0], previous[1])
                removed_previous = True
            run(
                ["ip", "-4", "address", "add", address, "dev", interface],
                check=True,
                timeout=5,
            )
            added = True
        write_app_lease_record(path, interface, address, gateway)
    except (OSError, subprocess.SubprocessError):
        if added:
            try:
                _delete_address(run, interface, address)
            except (OSError, subprocess.SubprocessError):
                write_app_lease_record(
                    path,
                    interface,
                    address,
                    gateway,
                )
                raise
        if previous and removed_previous:
            run(
                [
                    "ip",
                    "-4",
                    "address",
                    "add",
                    previous[1],
                    "dev",
                    previous[0],
                ],
                check=False,
                timeout=5,
            )
        raise

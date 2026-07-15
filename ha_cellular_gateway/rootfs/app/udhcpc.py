from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from .udhcpc_address import (
    RunCommand,
    configure,
    deconfigure,
    normalise_interface,
)
from .upstream_lease import lease_lock


LEASE_NAME = "iphone-usb-lease.json"
LOCK_NAME = "iphone-usb.lock"
ERROR_NAME = "iphone-usb-dhcp-error"


def _run(
    args: list[str],
    *,
    check: bool = True,
    timeout: int = 5,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _lease_from_environment(
    environment: Mapping[str, str],
) -> tuple[str, str, str]:
    interface = normalise_interface(environment.get("interface", ""))
    address = ipaddress.IPv4Address(environment.get("ip", ""))
    netmask = environment.get("subnet", "255.255.255.0")
    prefix = ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    lease = ipaddress.IPv4Interface(f"{address}/{prefix}")
    routers = environment.get("router", "").split()
    if not routers:
        raise ValueError("iPhone USB DHCP lease has no gateway")
    gateway = ipaddress.IPv4Address(routers[0])
    if address in {lease.network.network_address, lease.network.broadcast_address}:
        raise ValueError("iPhone USB DHCP lease address is not usable")
    if gateway not in lease.network or gateway in {
        address,
        lease.network.network_address,
        lease.network.broadcast_address,
    }:
        raise ValueError("iPhone USB DHCP lease gateway is not usable")
    return interface, str(lease), str(gateway)


def _error_message(error: Exception) -> str:
    if isinstance(error, ValueError):
        return str(error)
    if isinstance(error, subprocess.TimeoutExpired):
        return "iPhone USB DHCP address command timed out"
    return "iPhone USB DHCP address configuration failed"


def _write_error(path: Path, error: Exception) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            _error_message(error)[:256],
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def handle_event(
    event: str,
    *,
    environment: Mapping[str, str],
    run_dir: Path,
    run: RunCommand = _run,
) -> None:
    if event not in {"bound", "deconfig", "renew"}:
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    lease_path = run_dir / LEASE_NAME
    error_path = run_dir / ERROR_NAME
    with lease_lock(run_dir / LOCK_NAME, exclusive=True):
        try:
            if event == "deconfig":
                deconfigure(lease_path, run)
            else:
                try:
                    lease = _lease_from_environment(environment)
                except ValueError:
                    deconfigure(lease_path, run)
                    raise
                configure(lease_path, lease, run)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            _write_error(error_path, error)
            raise
        error_path.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) != 2:
        print("udhcpc: expected one lease event", file=sys.stderr)
        return 2
    try:
        handle_event(
            sys.argv[1],
            environment=os.environ,
            run_dir=Path(
                os.environ.get("CELLGW_RUN_DIR", "/run/ha-cellgw")
            ),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as err:
        print(f"udhcpc: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

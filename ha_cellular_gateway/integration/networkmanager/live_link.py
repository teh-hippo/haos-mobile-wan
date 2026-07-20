"""Veth and dnsmasq lifecycle for realised-device scenarios."""

from __future__ import annotations

import os
import subprocess

from live_constants import DEVICE, FIXED_UUIDS, HARNESS_DIR, PHONE
from live_dbus import delete_fixed_profiles, device_present
from live_tracing import TracingRun, wait_for

_ACTIVE_DNSMASQ: list["subprocess.Popen[bytes]"] = []


def _terminate(proc: "subprocess.Popen[bytes]") -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def untrack_process(proc: "subprocess.Popen[bytes]") -> None:
    if proc in _ACTIVE_DNSMASQ:
        _ACTIVE_DNSMASQ.remove(proc)


def stop_dnsmasq(proc: "subprocess.Popen[bytes]") -> None:
    """Terminate a tracked dnsmasq peer and stop tracking it for teardown."""
    untrack_process(proc)
    _terminate(proc)


def realise_link(run: TracingRun) -> "subprocess.Popen[bytes]":
    """Create the carrier-up veth and DHCP peer, then wait for NM to see it.

    NetworkManager is already running, so realising the link here exercises the
    real one-time have_connection_for_device gate exactly as HAOS does.
    """
    run("ip", "link", "add", DEVICE, "type", "veth", "peer", "name", PHONE)
    run("ip", "address", "add", "192.0.2.1/24", "dev", PHONE)
    run("ip", "link", "set", PHONE, "up")
    run("ip", "link", "set", DEVICE, "up")
    # Each realisation gets a fresh single-address pool. Every veth is created
    # with a new MAC, so a lease database carried over from a prior scenario
    # would leave the only address bound to a stale client and starve DHCP.
    lease_file = os.path.join(HARNESS_DIR, "dnsmasq.leases")
    if os.path.exists(lease_file):
        os.remove(lease_file)
    with open(os.path.join(HARNESS_DIR, "dnsmasq.log"), "ab") as log:
        proc = subprocess.Popen(
            [
                "dnsmasq",
                "--keep-in-foreground",
                "--port=0",
                f"--interface={PHONE}",
                "--bind-interfaces",
                "--except-interface=lo",
                f"--dhcp-leasefile={lease_file}",
                "--dhcp-authoritative",
                "--dhcp-range=192.0.2.100,192.0.2.100,255.255.255.0,1h",
                "--dhcp-option=option:router,192.0.2.1",
                "--dhcp-option=option:dns-server,192.0.2.1",
                "--log-dhcp",
            ],
            stdout=log,
            stderr=log,
        )
    wait_for(
        lambda: device_present(run),
        "NetworkManager did not realise the veth device",
    )
    _ACTIVE_DNSMASQ.append(proc)
    return proc


def destroy_link(run: TracingRun, proc: "subprocess.Popen[bytes] | None") -> None:
    if proc is not None:
        stop_dnsmasq(proc)
    run("ip", "link", "delete", DEVICE, "type", "veth", check=False)
    wait_for(
        lambda: not device_present(run),
        "veth device was not removed",
    )


def drop_generated_connections(run: TracingRun) -> None:
    """Remove any NetworkManager-generated connection so cleanup stays exact."""
    run("nmcli", "-w", "5", "device", "disconnect", DEVICE, check=False)
    listing = (
        run(
            "nmcli",
            "--escape",
            "no",
            "-g",
            "UUID",
            "connection",
            "show",
            check=False,
        ).stdout
        or ""
    )
    for uuid in listing.split():
        if uuid not in FIXED_UUIDS:
            run("nmcli", "connection", "delete", "uuid", uuid, check=False)


def teardown_active_links(run: TracingRun) -> None:
    for proc in list(_ACTIVE_DNSMASQ):
        destroy_link(run, proc)
    run("ip", "link", "delete", DEVICE, "type", "veth", check=False)
    delete_fixed_profiles(run)

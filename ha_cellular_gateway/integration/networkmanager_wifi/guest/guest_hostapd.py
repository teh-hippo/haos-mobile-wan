from __future__ import annotations

import os
import signal
import subprocess
import time

from app.networkmanager_wifi import NetworkManagerWifi
from guest_tracing import (
    FOREIGN_UUID,
    TracingRun,
    active_uuid,
    profile_settings,
    require,
    wait_for,
)


def create_foreign_profile(run: TracingRun) -> tuple[str, ...]:
    interface = os.environ["LAB_CLIENT_INTERFACE"]
    run(
        "nmcli",
        "connection",
        "add",
        "type",
        "wifi",
        "con-name",
        "Foreign Wi-Fi",
        "connection.uuid",
        FOREIGN_UUID,
        "ifname",
        interface,
        "ssid",
        os.environ["LAB_SSID"],
    )
    run(
        "nmcli",
        "connection",
        "modify",
        "uuid",
        FOREIGN_UUID,
        "connection.autoconnect",
        "yes",
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "wifi-sec.psk",
        os.environ["LAB_PSK"],
        "ipv4.method",
        "manual",
        "ipv4.addresses",
        "172.20.10.5/28",
        "ipv4.gateway",
        "172.20.10.1",
        "ipv6.method",
        "disabled",
    )
    run(
        "nmcli",
        "-w",
        "15",
        "connection",
        "up",
        "uuid",
        FOREIGN_UUID,
        "ifname",
        interface,
    )
    require(active_uuid(run) == FOREIGN_UUID, "foreign profile did not activate")
    return profile_settings(run, FOREIGN_UUID)


def wait_until_active(wifi: NetworkManagerWifi) -> None:
    result = wifi.inspect()
    deadline = time.monotonic() + 30
    while result.upstream is None and time.monotonic() < deadline:
        time.sleep(1)
        result = wifi.inspect()
    require(result.upstream is not None, f"Wi-Fi did not become active: {result.error}")


def stop_hostapd() -> None:
    with open(os.environ["LAB_HOSTAPD_PID_FILE"], encoding="utf-8") as stream:
        pid = int(stream.read())
    os.kill(pid, signal.SIGTERM)
    wait_for(
        lambda: not _process_exists(pid),
        "hostapd did not stop",
        seconds=10,
    )


def start_hostapd() -> None:
    try:
        os.unlink(os.environ["LAB_HOSTAPD_PID_FILE"])
    except FileNotFoundError:
        pass
    result = subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            os.environ["LAB_AP_NAMESPACE"],
            "hostapd",
            "-B",
            "-P",
            os.environ["LAB_HOSTAPD_PID_FILE"],
            "-f",
            os.environ["LAB_HOSTAPD_LOG"],
            os.environ["LAB_HOSTAPD_CONFIG"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    require(result.returncode == 0, "hostapd did not restart")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def target_visible(run: TracingRun) -> bool:
    interface = os.environ["LAB_CLIENT_INTERFACE"]
    run(
        "nmcli",
        "device",
        "wifi",
        "rescan",
        "ifname",
        interface,
        check=False,
    )
    result = run(
        "nmcli",
        "-g",
        "SSID",
        "device",
        "wifi",
        "list",
        "ifname",
        interface,
        "--rescan",
        "no",
        check=False,
    )
    return os.environ["LAB_SSID"] in (result.stdout or "").splitlines()

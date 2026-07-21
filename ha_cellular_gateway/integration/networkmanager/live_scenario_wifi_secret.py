from __future__ import annotations

import subprocess

from app.nm_metadata import DbusWifiProfileMetadata
from app.wifi_custody import MARKER_KEY
from live_constants import LAB_MARKER_VALUE, SYNTHETIC_PSK, WIFI_UUID
from live_dbus import (
    get_settings,
    profile_exists,
    read_psk_without_logging,
    without_user_setting,
)
from live_tracing import TracingRun, require


def test_wifi_marker_preserves_secret(run: TracingRun) -> None:
    try:
        created = run(
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "con-name",
            "nm-lab-psk",
            "connection.uuid",
            WIFI_UUID,
            "ifname",
            "*",
            "ssid",
            "LabHotspot",
            "connection.autoconnect",
            "no",
            "wifi-sec.key-mgmt",
            "wpa-psk",
            "wifi-sec.psk",
            SYNTHETIC_PSK,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise AssertionError("synthetic Wi-Fi profile creation failed") from None
    require(
        created.returncode == 0,
        "synthetic Wi-Fi profile creation failed",
    )
    secret_before = read_psk_without_logging(run, WIFI_UUID)
    require(secret_before == SYNTHETIC_PSK, "synthetic PSK was not stored")
    settings_before = get_settings(WIFI_UUID)
    require(
        "user" not in settings_before,
        "synthetic profile unexpectedly carried user metadata",
    )

    metadata = DbusWifiProfileMetadata(WIFI_UUID)
    metadata.write(MARKER_KEY, LAB_MARKER_VALUE)
    require(
        metadata.read(MARKER_KEY) == LAB_MARKER_VALUE,
        "marker did not persist through the production D-Bus helper",
    )
    require(
        read_psk_without_logging(run, WIFI_UUID) == secret_before,
        "writing the marker altered the Wi-Fi PSK",
    )
    settings_marked = get_settings(WIFI_UUID)
    require(
        settings_marked.get("user", {}).get("data", {}).get(MARKER_KEY)
        == LAB_MARKER_VALUE,
        "marker is missing from user.data after a D-Bus write",
    )
    require(
        without_user_setting(settings_marked) == without_user_setting(settings_before),
        "writing the marker altered other profile settings",
    )

    metadata.clear(MARKER_KEY)
    require(metadata.read(MARKER_KEY) is None, "marker was not cleared")
    require(
        read_psk_without_logging(run, WIFI_UUID) == secret_before,
        "clearing the marker altered the Wi-Fi PSK",
    )
    settings_cleared = get_settings(WIFI_UUID)
    require(
        MARKER_KEY not in settings_cleared.get("user", {}).get("data", {}),
        "marker remained in user.data after being cleared",
    )
    require(
        without_user_setting(settings_cleared) == without_user_setting(settings_before),
        "clearing the marker altered other profile settings",
    )

    run("nmcli", "connection", "delete", "uuid", WIFI_UUID, check=False)
    require(
        not profile_exists(run, WIFI_UUID),
        "synthetic Wi-Fi profile remains after cleanup",
    )

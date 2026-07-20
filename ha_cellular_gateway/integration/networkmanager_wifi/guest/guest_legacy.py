"""Legacy (pre-fix) NetworkManager Wi-Fi control-path regression check."""

from __future__ import annotations

import os

from app.networkmanager_wifi import NetworkManagerWifi
from app.wifi_custody import RADIO_HARD_OFF
from guest_tracing import TracingRun, profile_exists, require


def legacy_control(run: TracingRun, wifi: NetworkManagerWifi) -> None:
    errors = wifi.claim(os.environ["LAB_MANAGEMENT_INTERFACE"])

    require(RADIO_HARD_OFF in errors, "v0.10.0 did not reproduce the false block")
    require(not profile_exists(run), "legacy code unexpectedly created Wi-Fi profile")
    require(
        ("nmcli", "-g", "WIFI-HW,WIFI", "radio") in run.commands,
        "legacy code did not execute the combined radio query",
    )

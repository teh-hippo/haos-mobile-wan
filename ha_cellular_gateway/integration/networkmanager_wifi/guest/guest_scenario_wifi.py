"""Fixed Wi-Fi custody, wrong-PSK rejection, and target-loss recovery scenarios."""

from __future__ import annotations

import os
import time

from app.networkmanager_wifi import NetworkManagerWifi
from app.nm_profile_specs import WIFI_PROFILE_UUID
from guest_hostapd import (
    create_foreign_profile,
    start_hostapd,
    stop_hostapd,
    target_visible,
    wait_until_active,
)
from guest_tracing import (
    FOREIGN_UUID,
    TracingRun,
    active_uuid,
    config,
    profile_exists,
    profile_settings,
    require,
    wait_for,
)


def custody_and_restoration(run: TracingRun, wifi: NetworkManagerWifi) -> None:
    foreign_before = create_foreign_profile(run)
    errors = wifi.claim(os.environ["LAB_MANAGEMENT_INTERFACE"])
    require(not errors, f"Wi-Fi claim failed: {errors}")
    require(profile_exists(run), "fixed code did not create the Wi-Fi profile")
    require(active_uuid(run) != FOREIGN_UUID, "foreign profile remains active")

    wait_until_active(wifi)
    require(
        ("nmcli", "-g", "WIFI-HW", "radio") in run.commands,
        "fixed code did not read the hardware radio field",
    )
    require(
        ("nmcli", "-g", "WIFI", "radio") in run.commands,
        "fixed code did not read the software radio field",
    )
    require(
        ("nmcli", "-g", "WIFI-HW,WIFI", "radio") not in run.commands,
        "fixed code still used the combined radio query",
    )

    errors = wifi.release(os.environ["LAB_MANAGEMENT_INTERFACE"])
    require(not errors, f"Wi-Fi release failed: {errors}")
    require(not profile_exists(run), "app Wi-Fi profile remains after release")
    require(active_uuid(run) == FOREIGN_UUID, "foreign profile was not restored")
    require(
        profile_settings(run, FOREIGN_UUID) == foreign_before,
        "foreign profile definition changed",
    )
    run("nmcli", "connection", "delete", "uuid", FOREIGN_UUID)


def wrong_psk_rejection(run: TracingRun) -> None:
    wrong = NetworkManagerWifi(config(password="lab-incorrect-psk"), run)
    errors = wrong.claim(os.environ["LAB_MANAGEMENT_INTERFACE"])
    require(not errors, f"wrong-PSK claim failed: {errors}")
    result = wrong.inspect()
    deadline = time.monotonic() + 20
    while result.state != "auth_failed" and time.monotonic() < deadline:
        time.sleep(1)
        result = wrong.inspect()
    require(result.state == "auth_failed", "wrong PSK was not classified")
    require(
        not wrong.release(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "wrong-PSK release failed",
    )


def target_loss_and_recovery(run: TracingRun) -> None:
    restored = NetworkManagerWifi(config(), run)
    require(
        not restored.claim(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "target-loss claim failed",
    )
    wait_until_active(restored)
    stop_hostapd()
    wait_for(
        lambda: not target_visible(run),
        "target SSID remained cached after access-point loss",
        seconds=60,
    )
    wait_for(
        lambda: active_uuid(run) != WIFI_PROFILE_UUID,
        "NetworkManager kept the lost access point active",
        seconds=20,
    )
    result = restored.inspect()
    require(result.upstream is None, "Wi-Fi stayed active after target loss")
    start_hostapd()
    wait_for(
        lambda: target_visible(run),
        "target SSID did not return",
        seconds=20,
    )
    wait_until_active(restored)
    require(
        not restored.release(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "target-return release failed",
    )

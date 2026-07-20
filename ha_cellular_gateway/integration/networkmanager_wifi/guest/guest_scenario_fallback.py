"""Generic USB upstream selection and Wi-Fi fallback preference scenario."""

from __future__ import annotations

import os
import time

from app.const import GENERIC_USB, GENERIC_USB_WIFI_FALLBACK, WIFI_HOTSPOT
from app.mobile_connection import MobileConnectionResolver
from app.networkmanager_wifi import NetworkManagerWifi
from app.nm_profile_specs import GENERIC_USB_PROFILE_UUID
from app.upstream_generic_usb import GenericUsbUpstream
from guest_hostapd import wait_until_active
from guest_tracing import TracingRun, config, management, profile_exists, require
from guest_usb import bind_generic_usb, resolve_generic, unbind_generic_usb


def generic_usb_and_fallback(run: TracingRun) -> None:
    fallback_config = config(connection=GENERIC_USB_WIFI_FALLBACK)
    generic = GenericUsbUpstream(fallback_config, run)
    generic.nm.profile.create()
    interface = bind_generic_usb()
    require(
        os.path.basename(os.path.realpath(f"/sys/class/net/{interface}/device/driver"))
        == "cdc_ether",
        "QEMU generic USB did not bind with cdc_ether",
    )
    resolved = resolve_generic(generic)
    require(resolved.connection == GENERIC_USB, "generic USB-only selection failed")
    require(profile_exists(run, GENERIC_USB_PROFILE_UUID), "generic profile missing")

    fallback_wifi = NetworkManagerWifi(fallback_config, run)
    require(
        not fallback_wifi.claim(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "generic fallback Wi-Fi claim failed",
    )
    wait_until_active(fallback_wifi)
    resolver = MobileConnectionResolver(
        fallback_config,
        generic,
        fallback_wifi,
    )
    selected = resolver.resolve(management(), "downstream0")
    require(
        selected.upstream is not None and selected.upstream.connection == GENERIC_USB,
        "generic USB was not preferred over Wi-Fi",
    )

    unbind_generic_usb()
    selected = resolver.resolve(management(), "downstream0")
    require(
        selected.upstream is not None
        and selected.upstream.connection == WIFI_HOTSPOT
        and selected.fallback_active,
        "Wi-Fi was not promoted after generic USB removal",
    )

    bind_generic_usb()
    deadline = time.monotonic() + 30
    selected = resolver.resolve(management(), "downstream0")
    while (
        selected.upstream is None or selected.upstream.connection != GENERIC_USB
    ) and time.monotonic() < deadline:
        time.sleep(1)
        selected = resolver.resolve(management(), "downstream0")
    require(
        selected.upstream is not None and selected.upstream.connection == GENERIC_USB,
        "generic USB preference did not return",
    )

    require(
        not fallback_wifi.release(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "generic fallback Wi-Fi release failed",
    )
    generic.nm.release_profile()
    generic.cleanup()
    require(
        not profile_exists(run, GENERIC_USB_PROFILE_UUID),
        "generic USB profile remains after cleanup",
    )

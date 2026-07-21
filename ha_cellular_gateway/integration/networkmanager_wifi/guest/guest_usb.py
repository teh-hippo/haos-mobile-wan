from __future__ import annotations

import os
import time

from app.upstream_generic_usb import GenericUsbUpstream
from guest_tracing import management, require, wait_for


def generic_interface() -> str | None:
    root = "/sys/class/net"
    for name in os.listdir(root):
        driver = os.path.join(root, name, "device", "driver")
        if not os.path.exists(driver):
            continue
        if os.path.basename(os.path.realpath(driver)) in {
            "rndis_host",
            "cdc_ether",
            "cdc_ncm",
        }:
            return name
    return None


def bind_generic_usb() -> str:
    driver = os.environ["LAB_GENERIC_USB_DRIVER"]
    bind_id = os.environ["LAB_GENERIC_USB_BIND_ID"]
    with open(
        f"/sys/bus/usb/drivers/{driver}/bind",
        "w",
        encoding="utf-8",
    ) as stream:
        stream.write(bind_id)
    wait_for(lambda: generic_interface() is not None, "generic USB did not bind")
    interface = generic_interface()
    assert interface is not None
    return interface


def unbind_generic_usb() -> None:
    driver = os.environ["LAB_GENERIC_USB_DRIVER"]
    bind_id = os.environ["LAB_GENERIC_USB_BIND_ID"]
    with open(
        f"/sys/bus/usb/drivers/{driver}/unbind",
        "w",
        encoding="utf-8",
    ) as stream:
        stream.write(bind_id)
    wait_for(lambda: generic_interface() is None, "generic USB did not unbind")


def resolve_generic(
    usb: GenericUsbUpstream,
) -> object:
    resolved, errors = usb.resolve(management(), "downstream0")
    deadline = time.monotonic() + 30
    while resolved is None and time.monotonic() < deadline:
        time.sleep(1)
        resolved, errors = usb.resolve(management(), "downstream0")
    require(resolved is not None, f"generic USB did not become active: {errors}")
    return resolved

from __future__ import annotations

import os
import time
from pathlib import Path

from app.upstream_generic_usb import GenericUsbUpstream
from guest_tracing import management, require, wait_for


def generic_interface() -> str | None:
    for entry in Path("/sys/class/net").iterdir():
        driver = entry / "device" / "driver"
        if not driver.exists():
            continue
        if driver.resolve().name in {
            "rndis_host",
            "cdc_ether",
            "cdc_ncm",
        }:
            return entry.name
    return None


def bind_generic_usb() -> str:
    driver = os.environ["LAB_GENERIC_USB_DRIVER"]
    bind_id = os.environ["LAB_GENERIC_USB_BIND_ID"]
    with Path(f"/sys/bus/usb/drivers/{driver}/bind").open(
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
    with Path(f"/sys/bus/usb/drivers/{driver}/unbind").open(
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

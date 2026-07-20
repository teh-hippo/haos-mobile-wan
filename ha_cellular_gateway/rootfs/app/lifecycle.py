from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from .const import GENERIC_USB, IPHONE_USB
from .errors import GatewayError

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .upstream_models import ResolvedUpstream

_LOGGER = logging.getLogger(__name__)


def wifi_interface_status(engine: GatewayEngine) -> dict[str, object] | None:
    config = engine.config
    if not config.uses_wifi:
        return None
    try:
        active = engine.wifi.profile.active_uuid(config.upstream_interface)
        enabled = engine.wifi.profile.inspect().state == "exact"
    except (
        GatewayError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ):
        return None
    return {
        "enabled": enabled,
        "connected": active == engine.wifi.profile.spec.uuid,
    }


def log_upstream_transitions(
    engine: GatewayEngine,
    upstream: ResolvedUpstream | None,
    wifi_status: dict[str, object] | None,
) -> None:
    usb = upstream is not None and upstream.connection in {
        IPHONE_USB,
        GENERIC_USB,
    }
    wifi = wifi_status is not None and wifi_status.get("connected") is True
    with engine.lock:
        previous_usb = engine._prev_usb_present
        previous_wifi = engine._prev_wifi_connected
        engine._prev_usb_present = usb
        engine._prev_wifi_connected = wifi
    if usb and not previous_usb:
        assert upstream is not None
        _LOGGER.info(
            "%s device connected",
            "iPhone USB" if upstream.connection == IPHONE_USB else "Generic USB",
        )
    if wifi and not previous_wifi:
        _LOGGER.info("Wi-Fi hotspot connected")
    if (previous_usb or previous_wifi) and not (usb or wifi):
        _LOGGER.info("Mobile upstream disconnected")

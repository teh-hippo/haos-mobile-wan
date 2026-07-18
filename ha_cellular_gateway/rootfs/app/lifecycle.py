from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from .errors import GatewayError
from .const import IPHONE_USB

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
    iphone = upstream is not None and upstream.connection == IPHONE_USB
    wifi = wifi_status is not None and wifi_status.get("connected") is True
    with engine.lock:
        previous_iphone = engine._prev_iphone_present
        previous_wifi = engine._prev_wifi_connected
        engine._prev_iphone_present = iphone
        engine._prev_wifi_connected = wifi
    if iphone and not previous_iphone:
        _LOGGER.info("iPhone USB device connected")
    if wifi and not previous_wifi:
        _LOGGER.info("Wi-Fi hotspot connected")
    if (previous_iphone or previous_wifi) and not (iphone or wifi):
        _LOGGER.info("Mobile upstream disconnected")

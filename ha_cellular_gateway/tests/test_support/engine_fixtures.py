from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rootfs.app.config import GatewayConfig
from rootfs.app.const import WIFI_HOTSPOT

from .metadata import FakeWifiProfileMetadata

if TYPE_CHECKING:
    from rootfs.app.gateway import GatewayEngine


def build_engine(config: GatewayConfig, **kwargs: object) -> "GatewayEngine":
    from rootfs.app.gateway import GatewayEngine

    kwargs.setdefault("wifi_metadata", FakeWifiProfileMetadata())
    return GatewayEngine(config, **kwargs)


def make_config(**overrides: object) -> GatewayConfig:
    values: dict[str, object] = {
        "auto_disable_minutes": 30,
        "mobile_connection": WIFI_HOTSPOT,
        "upstream_interface": "wlan0",
        "upstream_address": "172.20.10.4/28",
        "upstream_gateway": "172.20.10.1",
        "hotspot_ssid": "",
        "hotspot_password": "",
        "downstream_mac": "00:11:22:33:44:55",
        "downstream_address": "192.168.80.1/24",
    }
    values.update(overrides)
    return GatewayConfig(**values)


def sysctl_values() -> dict[Path, str]:
    return {
        Path("/proc/sys/net/ipv4/ip_forward"): "1",
        Path("/proc/sys/net/ipv4/conf/all/rp_filter"): "0",
        Path("/proc/sys/net/ipv4/conf/default/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/end0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/wlan0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/eth0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/enx001122334455/rp_filter"): "2",
    }

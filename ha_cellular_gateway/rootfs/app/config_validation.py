from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING

from .const import (
    MOBILE_CONNECTIONS,
)
from .errors import GatewayError

if TYPE_CHECKING:
    from .config import GatewayConfig


PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def validate_config(config: GatewayConfig) -> None:
    if not 0 <= config.auto_disable_minutes <= 1440:
        raise GatewayError("Auto-disable must be between 0 and 1440 minutes")
    if config.mobile_connection not in MOBILE_CONNECTIONS:
        raise GatewayError(f"Unsupported mobile connection: {config.mobile_connection}")
    if config.uses_wifi and not config.upstream_interface:
        raise GatewayError("Network interface names must not be empty")
    validate_hotspot_credentials(config.hotspot_ssid, config.hotspot_password)
    _validate_addresses(config)
    _validate_downstream_mac(config.downstream_mac)


def validate_hotspot_credentials(ssid: str, password: str) -> None:
    if not ssid and not password:
        return
    if not ssid or not password:
        raise GatewayError(
            "Hotspot SSID and password must both be set or both be empty"
        )
    try:
        ssid_length = len(ssid.encode("utf-8"))
    except UnicodeError as err:
        raise GatewayError("Hotspot SSID must be valid UTF-8") from err
    if ssid_length < 1 or ssid_length > 32 or "\x00" in ssid:
        raise GatewayError("Hotspot SSID must be 1 to 32 bytes")
    if len(password) < 8 or len(password) > 63 or "\x00" in password:
        raise GatewayError("Hotspot password must be 8 to 63 characters")


def _validate_addresses(config: GatewayConfig) -> None:
    try:
        downstream = ipaddress.ip_interface(config.downstream_address)
    except ValueError as err:
        raise GatewayError(f"Invalid network configuration: {err}") from err
    upstream = _hotspot_interface(config)
    gateway = _hotspot_gateway(config)
    if not isinstance(downstream, ipaddress.IPv4Interface):
        raise GatewayError("Only IPv4 gateway mode is supported")
    _validate_host_address("Downstream", downstream)
    if downstream.network.prefixlen > 30:
        raise GatewayError("Downstream network must have room for a router lease")
    if not any(downstream.network.subnet_of(private) for private in PRIVATE_NETWORKS):
        raise GatewayError("Downstream network must use private IPv4 space")
    if upstream:
        _validate_upstream(upstream, gateway)
    _validate_non_overlapping(downstream, upstream)


def _hotspot_interface(
    config: GatewayConfig,
) -> ipaddress.IPv4Interface | None:
    if not config.uses_wifi:
        return None
    try:
        upstream = ipaddress.ip_interface(config.upstream_address)
    except ValueError as err:
        raise GatewayError(f"Invalid network configuration: {err}") from err
    if not isinstance(upstream, ipaddress.IPv4Interface):
        raise GatewayError("Only IPv4 gateway mode is supported")
    return upstream


def _hotspot_gateway(config: GatewayConfig) -> ipaddress.IPv4Address | None:
    if not config.uses_wifi:
        return None
    try:
        gateway = ipaddress.ip_address(config.upstream_gateway)
    except ValueError as err:
        raise GatewayError(f"Invalid network configuration: {err}") from err
    if not isinstance(gateway, ipaddress.IPv4Address):
        raise GatewayError("Only IPv4 gateway mode is supported")
    return gateway


def _validate_host_address(
    label: str,
    interface: ipaddress.IPv4Interface,
) -> None:
    if interface.ip in {
        interface.network.network_address,
        interface.network.broadcast_address,
    }:
        raise GatewayError(f"{label} address is not a usable host address")


def _validate_upstream(
    upstream: ipaddress.IPv4Interface,
    gateway: ipaddress.IPv4Address | None,
) -> None:
    if upstream.ip in {
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        raise GatewayError("Upstream address is not a usable host address")
    assert gateway is not None
    if gateway not in upstream.network:
        raise GatewayError("Upstream gateway is outside the upstream subnet")
    if gateway in {
        upstream.ip,
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        raise GatewayError("Upstream gateway is not a usable peer address")


def _validate_non_overlapping(
    downstream: ipaddress.IPv4Interface,
    upstream: ipaddress.IPv4Interface | None,
) -> None:
    networks = _networks(downstream, upstream)
    if any(
        left.overlaps(right)
        for index, left in enumerate(networks)
        for right in networks[index + 1 :]
    ):
        raise GatewayError("Upstream and downstream networks must not overlap")


def _networks(
    downstream: ipaddress.IPv4Interface,
    upstream: ipaddress.IPv4Interface | None,
) -> tuple[ipaddress.IPv4Network, ...]:
    return (*((upstream.network,) if upstream else ()), downstream.network)


def _validate_downstream_mac(mac: str) -> None:
    if mac and not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        raise GatewayError("Downstream MAC address is invalid")

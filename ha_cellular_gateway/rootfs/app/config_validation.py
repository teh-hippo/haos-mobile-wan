from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING

from .errors import GatewayError

if TYPE_CHECKING:
    from .config import GatewayConfig


PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def validate_config(config: GatewayConfig) -> None:
    if config.mode not in {"disabled", "active"}:
        raise GatewayError(f"Unsupported mode: {config.mode}")
    if config.upstream_mode not in {"hotspot_wifi", "iphone_usb"}:
        raise GatewayError(f"Unsupported upstream mode: {config.upstream_mode}")
    if not config.management_interface or not config.upstream_interface:
        raise GatewayError("Network interface names must not be empty")
    validate_hotspot_credentials(config.hotspot_ssid, config.hotspot_password)
    _validate_addresses(config)
    _validate_downstream_mac(config.downstream_mac)


def validate_hotspot_credentials(ssid: str, password: str) -> None:
    if not ssid and not password:
        return
    if not ssid or not password:
        raise GatewayError("Hotspot SSID and password must both be set or both be empty")
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
        management = ipaddress.ip_interface(config.management_address)
        downstream = ipaddress.ip_interface(config.downstream_address)
    except ValueError as err:
        raise GatewayError(f"Invalid network configuration: {err}") from err
    upstream = _hotspot_interface(config)
    gateway = _hotspot_gateway(config)
    for interface in (management, downstream, *(tuple([upstream]) if upstream else ())):
        if interface.version != 4:
            raise GatewayError("Only IPv4 gateway mode is supported")
    _validate_host_address("Management", management)
    _validate_host_address("Downstream", downstream)
    if downstream.network.prefixlen > 30:
        raise GatewayError("Downstream network must have room for a router lease")
    if not any(downstream.network.subnet_of(private) for private in PRIVATE_NETWORKS):
        raise GatewayError("Downstream network must use private IPv4 space")
    if upstream:
        _validate_upstream(config, upstream, gateway)
    _validate_non_overlapping(management, downstream, upstream)


def _hotspot_interface(
    config: GatewayConfig,
) -> ipaddress.IPv4Interface | ipaddress.IPv6Interface | None:
    if config.upstream_mode != "hotspot_wifi":
        return None
    try:
        upstream = ipaddress.ip_interface(config.upstream_address)
    except ValueError as err:
        raise GatewayError(f"Invalid network configuration: {err}") from err
    return upstream


def _hotspot_gateway(config: GatewayConfig) -> ipaddress.IPv4Address | None:
    if config.upstream_mode != "hotspot_wifi":
        return None
    try:
        gateway = ipaddress.ip_address(config.upstream_gateway)
    except ValueError as err:
        raise GatewayError(f"Invalid network configuration: {err}") from err
    if gateway.version != 4:
        raise GatewayError("Only IPv4 gateway mode is supported")
    return gateway


def _validate_host_address(
    label: str,
    interface: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
) -> None:
    if interface.ip in {
        interface.network.network_address,
        interface.network.broadcast_address,
    }:
        raise GatewayError(f"{label} address is not a usable host address")


def _validate_upstream(
    config: GatewayConfig,
    upstream: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    gateway: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
) -> None:
    if upstream.ip in {
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        raise GatewayError("Upstream address is not a usable host address")
    if config.management_interface == config.upstream_interface:
        raise GatewayError("Management and upstream interfaces must differ")
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
    management: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    downstream: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    upstream: ipaddress.IPv4Interface | ipaddress.IPv6Interface | None,
) -> None:
    networks = _networks(management, downstream, upstream)
    if any(
        left.overlaps(right)
        for index, left in enumerate(networks)
        for right in networks[index + 1 :]
    ):
        raise GatewayError(
            "Management, upstream and downstream networks must not overlap"
        )


def _networks(
    management: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    downstream: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    upstream: ipaddress.IPv4Interface | ipaddress.IPv6Interface | None,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return (management.network, *((upstream.network,) if upstream else ()), downstream.network)


def _validate_downstream_mac(mac: str) -> None:
    if mac and not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        raise GatewayError("Downstream MAC address is invalid")

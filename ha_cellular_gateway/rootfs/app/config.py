from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import GatewayError


OPTIONS_PATH = Path(os.environ.get("CELLGW_OPTIONS", "/data/options.json"))
TOKEN_PATH = Path(os.environ.get("CELLGW_TOKEN", "/data/api_token"))
RUN_DIR = Path(os.environ.get("CELLGW_RUN_DIR", "/run/ha-cellgw"))
LEASE_PATH = Path(os.environ.get("CELLGW_LEASES", "/data/dnsmasq.leases"))
STATE_PATH = Path(os.environ.get("CELLGW_STATE", "/data/state.json"))


@dataclass(frozen=True)
class GatewayConfig:
    mode: str
    dry_run: bool
    management_interface: str
    management_address: str
    upstream_mode: str
    upstream_interface: str
    upstream_ssid: str
    upstream_address: str
    upstream_gateway: str
    downstream_mac: str
    downstream_address: str
    transit_subnet: str
    dhcp_start: str
    dhcp_end: str
    dns_servers: tuple[str, ...]
    routing_table: int
    reconcile_seconds: int
    trial_seconds: int
    api_bind: str
    api_port: int

    @classmethod
    def from_path(cls, path: Path = OPTIONS_PATH) -> "GatewayConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        config = cls(
            mode=str(data.get("mode", "disabled")),
            dry_run=bool(data.get("dry_run", True)),
            management_interface=str(data.get("management_interface", "end0")),
            management_address=str(data.get("management_address", "192.168.1.2/24")),
            upstream_mode=str(data.get("upstream_mode", "hotspot_wifi")),
            upstream_interface=str(data.get("upstream_interface", "wlan0")),
            upstream_ssid=str(data.get("upstream_ssid", "MobileHotspot")),
            upstream_address=str(data.get("upstream_address", "172.20.10.4/28")),
            upstream_gateway=str(data.get("upstream_gateway", "172.20.10.1")),
            downstream_mac=str(data.get("downstream_mac", "")).lower(),
            downstream_address=str(data.get("downstream_address", "192.168.80.1/24")),
            transit_subnet=str(data.get("transit_subnet", "192.168.80.0/24")),
            dhcp_start=str(data.get("dhcp_start", "192.168.80.10")),
            dhcp_end=str(data.get("dhcp_end", "192.168.80.50")),
            dns_servers=tuple(data.get("dns_servers", ["1.1.1.1", "8.8.8.8"])),
            routing_table=int(data.get("routing_table", 201)),
            reconcile_seconds=max(2, int(data.get("reconcile_seconds", 5))),
            trial_seconds=max(60, int(data.get("trial_seconds", 300))),
            api_bind=str(data.get("api_bind", "172.30.32.1")),
            api_port=int(data.get("api_port", 8099)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"disabled", "trial", "active"}:
            raise GatewayError(f"Unsupported mode: {self.mode}")
        if self.upstream_mode not in {"hotspot_wifi", "iphone_usb"}:
            raise GatewayError(f"Unsupported upstream mode: {self.upstream_mode}")

        try:
            management = ipaddress.ip_interface(self.management_address)
            downstream = ipaddress.ip_interface(self.downstream_address)
            dhcp_start = ipaddress.ip_address(self.dhcp_start)
            dhcp_end = ipaddress.ip_address(self.dhcp_end)
            api_bind = ipaddress.ip_address(self.api_bind)
        except ValueError as err:
            raise GatewayError(f"Invalid network configuration: {err}") from err
        upstream = None
        gateway = None
        if self.upstream_mode == "hotspot_wifi":
            try:
                upstream = ipaddress.ip_interface(self.upstream_address)
                gateway = ipaddress.ip_address(self.upstream_gateway)
            except ValueError as err:
                raise GatewayError(f"Invalid network configuration: {err}") from err
        transit = ipaddress.ip_network(self.transit_subnet)

        if management.version != 4 or downstream.version != 4:
            raise GatewayError("Only IPv4 gateway mode is supported")
        if upstream and upstream.version != 4:
            raise GatewayError("Only IPv4 gateway mode is supported")
        if api_bind.version != 4 or api_bind.is_unspecified or api_bind.is_multicast:
            raise GatewayError("API bind address must be a specific IPv4 address")
        for label, interface in (
            ("Management", management),
            ("Downstream", downstream),
        ):
            if interface.ip in {
                interface.network.network_address,
                interface.network.broadcast_address,
            }:
                raise GatewayError(f"{label} address is not a usable host address")
        if upstream:
            if upstream.ip in {
                upstream.network.network_address,
                upstream.network.broadcast_address,
            }:
                raise GatewayError("Upstream address is not a usable host address")
            if self.management_interface == self.upstream_interface:
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
        if downstream.network != transit:
            raise GatewayError("Downstream address must use the transit subnet prefix")
        if dhcp_start not in transit or dhcp_end not in transit or dhcp_start > dhcp_end:
            raise GatewayError("Invalid DHCP range")
        if dhcp_start in {
            transit.network_address,
            transit.broadcast_address,
        } or dhcp_end in {
            transit.network_address,
            transit.broadcast_address,
        }:
            raise GatewayError("DHCP range includes a reserved subnet address")
        if dhcp_start <= downstream.ip <= dhcp_end:
            raise GatewayError("DHCP range includes the downstream gateway address")
        if any(
            left.overlaps(right)
            for index, left in enumerate(
                (management.network, *( [upstream.network] if upstream else [] ), transit)
            )
            for right in (
                management.network,
                *( [upstream.network] if upstream else [] ),
                transit,
            )[index + 1 :]
        ):
            raise GatewayError("Management, upstream and transit networks must not overlap")
        if self.downstream_mac and not re.fullmatch(
            r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}",
            self.downstream_mac,
        ):
            raise GatewayError("Downstream MAC address is invalid")
        if self.routing_table < 1 or self.routing_table > 4_294_967_295:
            raise GatewayError("Invalid routing table")
        if not self.dns_servers:
            raise GatewayError("At least one IPv4 DNS server is required")
        for dns in self.dns_servers:
            try:
                dns_address = ipaddress.ip_address(dns)
            except ValueError as err:
                raise GatewayError(f"Invalid DNS server: {dns}") from err
            if dns_address.version != 4:
                raise GatewayError("Only IPv4 DNS servers are supported")

    @property
    def upstream_ip(self) -> str:
        return str(ipaddress.ip_interface(self.upstream_address).ip)

    @property
    def upstream_network(self) -> str:
        return str(ipaddress.ip_interface(self.upstream_address).network)

    @property
    def downstream_ip(self) -> str:
        return str(ipaddress.ip_interface(self.downstream_address).ip)

    @property
    def downstream_network(self) -> str:
        return str(ipaddress.ip_interface(self.downstream_address).network)

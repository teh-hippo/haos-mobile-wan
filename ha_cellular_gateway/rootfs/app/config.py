from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .command import CommandRunner, RunCommand
from .errors import GatewayError
from .interfaces import ManagementBaseline, detect_management


OPTIONS_PATH = Path(os.environ.get("CELLGW_OPTIONS", "/data/options.json"))
TOKEN_PATH = Path(os.environ.get("CELLGW_TOKEN", "/data/api_token"))
RUN_DIR = Path(os.environ.get("CELLGW_RUN_DIR", "/run/ha-cellgw"))
LEASE_PATH = Path(os.environ.get("CELLGW_LEASES", "/data/dnsmasq.leases"))
STATE_PATH = Path(os.environ.get("CELLGW_STATE", "/data/state.json"))

PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
FALLBACK_MANAGEMENT = ManagementBaseline(
    interface="management-unavailable",
    address="192.0.2.1/24",
)


@dataclass(frozen=True)
class GatewayConfig:
    mode: str
    dry_run: bool
    management_interface: str
    management_address: str
    upstream_mode: str
    upstream_interface: str
    upstream_address: str
    upstream_gateway: str
    downstream_mac: str
    downstream_address: str

    dns_servers: ClassVar[tuple[str, ...]] = ("1.1.1.1", "8.8.8.8")
    routing_table: ClassVar[int] = 201
    reconcile_seconds: ClassVar[int] = 5
    trial_seconds: ClassVar[int] = 300
    api_bind: ClassVar[str] = "172.30.32.1"
    api_port: ClassVar[int] = 8099

    @classmethod
    def from_path(
        cls,
        path: Path = OPTIONS_PATH,
        *,
        run: RunCommand | None = None,
    ) -> "GatewayConfig":
        data = cls._read_options(path)
        management = detect_management(cls._resolve_run(run))
        config = cls._from_data(data, management)
        config.validate()
        return config

    @classmethod
    def load_path(
        cls,
        path: Path = OPTIONS_PATH,
        *,
        run: RunCommand | None = None,
    ) -> tuple["GatewayConfig", str | None]:
        errors: list[str] = []
        try:
            data = cls._read_options(path)
        except (GatewayError, OSError, ValueError) as err:
            data = {}
            errors.append(f"Cannot read app configuration: {err}")
        try:
            management = detect_management(cls._resolve_run(run))
        except (
            GatewayError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            management = FALLBACK_MANAGEMENT
            errors.append(f"Cannot detect management network: {err}")
        config = cls._from_data(data, management)
        try:
            config.validate()
        except GatewayError as err:
            errors.append(f"Invalid app configuration: {err}")
            config = cls._from_data({}, management)
        return config, "; ".join(errors) or None

    @staticmethod
    def _read_options(path: Path) -> dict[str, object]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise GatewayError("App configuration must be an object")
        return data

    @staticmethod
    def _resolve_run(run: RunCommand | None) -> RunCommand:
        if run is not None:
            return run
        runner = CommandRunner()
        return lambda *args, **kwargs: runner.run(
            list(args),
            check=kwargs.get("check", True),
            timeout=kwargs.get("timeout", 20),
        )

    @classmethod
    def _from_data(
        cls,
        data: dict[str, object],
        management: ManagementBaseline,
    ) -> "GatewayConfig":
        return cls(
            mode=str(data.get("mode", "disabled")),
            dry_run=bool(data.get("dry_run", True)),
            management_interface=management.interface,
            management_address=management.address,
            upstream_mode=str(data.get("upstream_mode", "hotspot_wifi")),
            upstream_interface=str(data.get("upstream_interface", "wlan0")),
            upstream_address=str(data.get("upstream_address", "172.20.10.4/28")),
            upstream_gateway=str(data.get("upstream_gateway", "172.20.10.1")),
            downstream_mac=str(data.get("downstream_mac", "")).lower(),
            downstream_address=str(
                data.get("downstream_address", "192.168.80.1/24")
            ),
        )

    def validate(self) -> None:
        if self.mode not in {"disabled", "trial", "active"}:
            raise GatewayError(f"Unsupported mode: {self.mode}")
        if self.upstream_mode not in {"hotspot_wifi", "iphone_usb"}:
            raise GatewayError(f"Unsupported upstream mode: {self.upstream_mode}")
        if not self.management_interface or not self.upstream_interface:
            raise GatewayError("Network interface names must not be empty")

        try:
            management = ipaddress.ip_interface(self.management_address)
            downstream = ipaddress.ip_interface(self.downstream_address)
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

        if management.version != 4 or downstream.version != 4:
            raise GatewayError("Only IPv4 gateway mode is supported")
        if upstream and upstream.version != 4:
            raise GatewayError("Only IPv4 gateway mode is supported")
        for label, interface in (
            ("Management", management),
            ("Downstream", downstream),
        ):
            if interface.ip in {
                interface.network.network_address,
                interface.network.broadcast_address,
            }:
                raise GatewayError(f"{label} address is not a usable host address")
        if downstream.network.prefixlen > 30:
            raise GatewayError("Downstream network must have room for a router lease")
        if not any(
            downstream.network.subnet_of(private) for private in PRIVATE_NETWORKS
        ):
            raise GatewayError("Downstream network must use private IPv4 space")
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
        networks = (
            management.network,
            *((upstream.network,) if upstream else ()),
            downstream.network,
        )
        if any(
            left.overlaps(right)
            for index, left in enumerate(networks)
            for right in networks[index + 1 :]
        ):
            raise GatewayError(
                "Management, upstream and downstream networks must not overlap"
            )
        if self.downstream_mac and not re.fullmatch(
            r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}",
            self.downstream_mac,
        ):
            raise GatewayError("Downstream MAC address is invalid")

    @property
    def upstream_ip(self) -> str:
        return str(ipaddress.ip_interface(self.upstream_address).ip)

    @property
    def downstream_ip(self) -> str:
        return str(ipaddress.ip_interface(self.downstream_address).ip)

    @property
    def transit_subnet(self) -> str:
        return str(ipaddress.ip_interface(self.downstream_address).network)

    @property
    def dhcp_start(self) -> str:
        downstream = ipaddress.ip_interface(self.downstream_address)
        candidate = downstream.network.network_address + 1
        if candidate == downstream.ip:
            candidate += 1
        return str(candidate)

    @property
    def dhcp_end(self) -> str:
        return self.dhcp_start

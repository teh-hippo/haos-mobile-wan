from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .command import CommandRunner, RunCommand
from .const import (
    DEFAULT_MOBILE_CONNECTION_OPTION,
    IPHONE_USB_WIFI_FALLBACK,
    MOBILE_CONNECTION_OPTIONS,
    WIFI_HOTSPOT,
)
from .errors import GatewayError
from .config_validation import validate_config
from .management import ManagementBaseline, detect_management


OPTIONS_PATH = Path(os.environ.get("CELLGW_OPTIONS", "/data/options.json"))
TOKEN_PATH = Path(os.environ.get("CELLGW_TOKEN", "/data/api_token"))
RUN_DIR = Path(os.environ.get("CELLGW_RUN_DIR", "/run/ha-cellgw"))
LEASE_PATH = Path(os.environ.get("CELLGW_LEASES", "/data/dnsmasq.leases"))
STATE_PATH = Path(os.environ.get("CELLGW_STATE", "/data/state.json"))

FALLBACK_MANAGEMENT = ManagementBaseline(
    interface="management-unavailable",
    address="192.0.2.1/24",
)


@dataclass(frozen=True)
class GatewayConfig:
    enabled: bool
    management_interface: str
    management_address: str
    mobile_connection: str
    upstream_interface: str
    upstream_address: str
    upstream_gateway: str
    hotspot_ssid: str
    hotspot_password: str
    downstream_mac: str
    downstream_address: str

    dns_servers: ClassVar[tuple[str, ...]] = ("1.1.1.1", "8.8.8.8")
    routing_table: ClassVar[int] = 201
    reconcile_seconds: ClassVar[int] = 5
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
        mobile_connection = str(
            data.get("mobile_connection", DEFAULT_MOBILE_CONNECTION_OPTION)
        )
        return cls(
            enabled=bool(data.get("enabled", False)),
            management_interface=management.interface,
            management_address=management.address,
            mobile_connection=MOBILE_CONNECTION_OPTIONS.get(
                mobile_connection,
                mobile_connection,
            ),
            upstream_interface=str(data.get("upstream_interface", "wlan0")),
            upstream_address=str(data.get("upstream_address", "172.20.10.4/28")),
            upstream_gateway=str(data.get("upstream_gateway", "172.20.10.1")),
            hotspot_ssid=str(data.get("hotspot_ssid", "")),
            hotspot_password=str(data.get("hotspot_password", "")),
            downstream_mac=str(data.get("downstream_mac", "")).lower(),
            downstream_address=str(
                data.get("router_address", "192.168.80.1/24")
            ),
        )

    def validate(self) -> None:
        validate_config(self)

    @property
    def hotspot_credentials_configured(self) -> bool:
        return bool(self.hotspot_ssid and self.hotspot_password)

    @property
    def uses_wifi(self) -> bool:
        return self.mobile_connection in {
            WIFI_HOTSPOT,
            IPHONE_USB_WIFI_FALLBACK,
        }

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

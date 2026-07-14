from __future__ import annotations

from typing import Literal, TypedDict, TypeAlias

GatewayMode: TypeAlias = Literal["disabled", "trial", "active"]
GatewaySelectableMode: TypeAlias = Literal["disabled", "trial"]
GatewayUpstreamMode: TypeAlias = Literal["hotspot_wifi", "iphone_usb"]
GatewayPairingState: TypeAlias = Literal[
    "not_applicable",
    "not_ready",
    "dry_run_blocked",
    "invalid_lease",
    "waiting_for_dhcp",
    "paired",
    "daemon_failed",
    "waiting_for_device",
    "multiple_devices",
    "waiting_for_interface",
    "ownership_conflict",
]
GatewayLeaseOwner: TypeAlias = Literal["app", "external"]


class GatewayRuntimeConfig(TypedDict):
    mode: GatewayMode
    dry_run: bool
    management_interface: str
    management_address: str
    upstream_mode: GatewayUpstreamMode
    upstream_interface: str
    upstream_ssid: str
    upstream_address: str
    upstream_gateway: str
    downstream_mac: str
    downstream_address: str
    transit_subnet: str
    dhcp_start: str
    dhcp_end: str
    routing_table: int
    reconcile_seconds: int
    trial_seconds: int
    api_bind: str
    api_port: int


class GatewayStatus(TypedDict):
    mode: GatewayMode
    desired_mode: GatewayMode
    configured_mode: GatewayMode
    dry_run: bool
    management_interface: str
    upstream_mode: GatewayUpstreamMode
    configured_upstream_interface: str
    upstream_interface: str | None
    upstream_address: str | None
    upstream_gateway: str | None
    downstream_interface: str | None
    downstream_present: bool
    rules_installed: bool
    dnsmasq_running: bool
    upstream_healthy: bool
    public_ip: str | None
    rollback_armed: bool
    rollback_deadline: float | None
    last_reconcile: float | None
    last_health_probe: float | None
    last_error: str | None
    safety_errors: list[str]
    upstream_pairing_state: GatewayPairingState
    upstream_pairing_message: str | None
    upstream_device_udid: str | None
    upstream_runtime_interface: str | None
    upstream_lockdown_path: str
    upstream_lease_owner: GatewayLeaseOwner | None
    config: GatewayRuntimeConfig

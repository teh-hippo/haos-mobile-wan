from __future__ import annotations

from typing import Literal, NotRequired, TypeAlias, TypedDict

GatewayMobileConnection: TypeAlias = Literal[
    "wifi_hotspot",
    "iphone_usb",
    "iphone_usb_wifi_fallback",
]
GatewayActiveConnection: TypeAlias = Literal["wifi_hotspot", "iphone_usb"]
GatewayPairingState: TypeAlias = Literal[
    "not_applicable",
    "not_ready",
    "waiting_for_device",
    "multiple_devices",
    "waiting_for_interface",
    "waiting_for_trust",
    "waiting_for_unlock",
    "pairing_failed",
    "daemon_failed",
    "profile_failed",
    "waiting_for_profile",
    "profile_conflict",
    "invalid_lease",
    "paired",
]
GatewayLeaseOwner: TypeAlias = Literal["networkmanager"]


class GatewayIssue(TypedDict):
    id: str
    translation_key: str | None
    repairable: bool
    transient: bool
    message: str


class GatewayRuntimeConfig(TypedDict):
    enabled: bool
    management_interface: str
    management_address: str
    mobile_connection: GatewayMobileConnection
    upstream_interface: str
    upstream_address: str
    upstream_gateway: str
    hotspot_ssid: str
    downstream_mac: str
    downstream_address: str


class GatewayStatus(TypedDict):
    enabled: bool
    configured_enabled: bool
    active: bool
    management_interface: str
    mobile_connection: GatewayMobileConnection
    active_connection: GatewayActiveConnection | None
    fallback_active: bool
    fallback_reason: str | None
    connection_warnings: list[str]
    configured_upstream_interface: str
    upstream_interface: str | None
    upstream_address: str | None
    upstream_gateway: str | None
    downstream_interface: str | None
    downstream_mac: str | None
    downstream_present: bool
    rules_installed: bool
    dnsmasq_running: bool
    upstream_healthy: bool
    public_ip: str | None
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
    issues: NotRequired[list[GatewayIssue]]

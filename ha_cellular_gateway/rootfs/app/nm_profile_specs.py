from __future__ import annotations

from .config import GatewayConfig
from .nm_profile import ProfileSpec

USB_PROFILE_NAME = "haos-mobile-wan-iphone"
USB_PROFILE_UUID = "69fc469b-e2b9-52ba-8f8d-20e5a353735b"
LEGACY_USB_PROFILE_UUID = "795b0402-f4b8-571b-91b0-2ab6816add52"
USB_ROUTE_TABLE = 202
USB_DHCP_TIMEOUT_SECONDS = 45
GENERIC_USB_PROFILE_NAME = "haos-mobile-wan-generic-usb"
GENERIC_USB_PROFILE_UUID = "9fa59daf-83d4-512a-8324-5caadc830fb8"
GENERIC_USB_DRIVERS = ("rndis_host", "cdc_ether", "cdc_ncm")

WIFI_PROFILE_NAME = "haos-mobile-wan-hotspot"
WIFI_PROFILE_UUID = "463ad2a4-3a0b-56a2-9b86-ec5470d95eb0"
WIFI_ROUTE_TABLE = 203


def usb_profile_spec() -> ProfileSpec:
    settings = (
        ("connection.interface-name", ""),
        ("connection.autoconnect", "no"),
        ("connection.autoconnect-retries", "0"),
        ("match.driver", "ipheth"),
        ("ipv4.method", "auto"),
        ("ipv4.route-table", str(USB_ROUTE_TABLE)),
        ("ipv4.ignore-auto-dns", "yes"),
        ("ipv4.never-default", "no"),
        ("ipv4.may-fail", "no"),
        ("ipv4.dhcp-timeout", str(USB_DHCP_TIMEOUT_SECONDS)),
        ("ipv6.method", "disabled"),
        ("802-3-ethernet.cloned-mac-address", "preserve"),
    )
    return ProfileSpec(
        key="iphone_usb",
        uuid=USB_PROFILE_UUID,
        name=USB_PROFILE_NAME,
        connection_type="802-3-ethernet",
        create_args=(
            "type",
            "ethernet",
            "con-name",
            USB_PROFILE_NAME,
            "connection.uuid",
            USB_PROFILE_UUID,
            "ifname",
            "*",
        ),
        settings=settings,
    )


def generic_usb_profile_spec() -> ProfileSpec:
    current = usb_profile_spec()
    settings = tuple(
        (
            "match.driver",
            ",".join(GENERIC_USB_DRIVERS),
        )
        if field == "match.driver"
        else (field, value)
        for field, value in current.settings
    )
    return ProfileSpec(
        key="generic_usb",
        uuid=GENERIC_USB_PROFILE_UUID,
        name=GENERIC_USB_PROFILE_NAME,
        connection_type=current.connection_type,
        create_args=(
            "type",
            "ethernet",
            "con-name",
            GENERIC_USB_PROFILE_NAME,
            "connection.uuid",
            GENERIC_USB_PROFILE_UUID,
            "ifname",
            "*",
        ),
        settings=settings,
    )


def legacy_usb_profile_spec() -> ProfileSpec:
    current = usb_profile_spec()
    settings = tuple(
        (field, "yes" if field == "connection.autoconnect" else value)
        for field, value in current.settings
    )
    return ProfileSpec(
        key="legacy_iphone_usb",
        uuid=LEGACY_USB_PROFILE_UUID,
        name=USB_PROFILE_NAME,
        connection_type=current.connection_type,
        create_args=(),
        settings=settings,
    )


def wifi_profile_spec(config: GatewayConfig) -> ProfileSpec:
    settings = (
        ("connection.interface-name", config.upstream_interface),
        ("connection.autoconnect", "no"),
        ("connection.autoconnect-retries", "0"),
        ("802-11-wireless.mode", "infrastructure"),
        ("802-11-wireless.ssid", config.hotspot_ssid),
        ("802-11-wireless-security.key-mgmt", "wpa-psk"),
        ("802-11-wireless-security.psk", config.hotspot_password),
        ("ipv4.method", "manual"),
        ("ipv4.addresses", config.upstream_address),
        ("ipv4.gateway", config.upstream_gateway),
        ("ipv4.route-table", str(WIFI_ROUTE_TABLE)),
        ("ipv4.ignore-auto-dns", "yes"),
        ("ipv4.never-default", "no"),
        ("ipv4.may-fail", "no"),
        ("ipv6.method", "disabled"),
    )
    return ProfileSpec(
        key="wifi_hotspot",
        uuid=WIFI_PROFILE_UUID,
        name=WIFI_PROFILE_NAME,
        connection_type="802-11-wireless",
        create_args=(
            "type",
            "wifi",
            "con-name",
            WIFI_PROFILE_NAME,
            "connection.uuid",
            WIFI_PROFILE_UUID,
            "ifname",
            config.upstream_interface,
            "ssid",
            config.hotspot_ssid,
        ),
        settings=settings,
    )

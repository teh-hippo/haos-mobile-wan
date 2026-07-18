from __future__ import annotations

from dataclasses import dataclass

from .config import GatewayConfig
from .management import ManagementBaseline
from .nm_inventory import NmInventory, ProfileRecord
from .nm_profile_specs import (
    LEGACY_USB_PROFILE_UUID,
    USB_PROFILE_UUID,
    WIFI_PROFILE_UUID,
)

MANAGEMENT_REQUIRED = "Management interface is unavailable"
WIFI_MANAGEMENT_CONFLICT = "Wi-Fi upstream is the management interface"
WIFI_FOREIGN_PROFILE = "Wi-Fi upstream has a foreign NetworkManager profile"
USB_FOREIGN_PROFILE = "iPhone USB has a foreign NetworkManager profile"


@dataclass(frozen=True)
class NmPreflightResult:
    errors: tuple[str, ...]
    legacy_wifi_profiles: tuple[ProfileRecord, ...] = ()


def inspect_nm_ownership(
    config: GatewayConfig,
    inventory: NmInventory,
    management: ManagementBaseline | None,
) -> NmPreflightResult:
    if management is None:
        return NmPreflightResult((MANAGEMENT_REQUIRED,))
    errors: list[str] = []
    legacy_wifi: list[ProfileRecord] = []
    if config.uses_wifi:
        if config.upstream_interface == management.interface:
            errors.append(WIFI_MANAGEMENT_CONFLICT)
        for profile in inventory.foreign_wifi_profiles(
            config.upstream_interface,
            allowed_uuid=WIFI_PROFILE_UUID,
        ):
            if profile.name == f"Supervisor {config.upstream_interface}":
                legacy_wifi.append(profile)
            else:
                errors.append(WIFI_FOREIGN_PROFILE)
    if config.uses_iphone:
        foreign_usb = inventory.foreign_ipheth_profiles(
            allowed_uuids={USB_PROFILE_UUID, LEGACY_USB_PROFILE_UUID}
        )
        if foreign_usb:
            errors.append(USB_FOREIGN_PROFILE)
    return NmPreflightResult(
        tuple(dict.fromkeys(errors)),
        tuple(legacy_wifi),
    )

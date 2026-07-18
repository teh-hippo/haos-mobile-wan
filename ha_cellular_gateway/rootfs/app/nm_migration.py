from __future__ import annotations

import re

from .command import RunCommand
from .config import GatewayConfig
from .const import LEGACY_WIFI_MIGRATE_MATCHING
from .nm_inventory import NmInventory, ProfileRecord
from .nm_profile import NmProfile
from .nm_profile_specs import legacy_usb_profile_spec

LEGACY_WIFI_MANUAL_ERROR = (
    "Legacy Supervisor Wi-Fi profile requires manual cleanup"
)
LEGACY_WIFI_MISMATCH_ERROR = (
    "Legacy Supervisor Wi-Fi profile does not match the app configuration"
)
LEGACY_USB_DRIFT_ERROR = (
    "The legacy iPhone USB profile has unexpected settings"
)
LEGACY_WIFI_DELETE_ERROR = (
    "Legacy Supervisor Wi-Fi profile could not be deleted"
)


def migrate_legacy_usb(run: RunCommand) -> list[str]:
    profile = NmProfile(run, legacy_usb_profile_spec())
    inspection = profile.inspect()
    if inspection.state == "missing":
        return []
    if inspection.state == "drifted":
        return [LEGACY_USB_DRIFT_ERROR]
    profile.deactivate()
    profile.delete()
    return []


def migrate_legacy_wifi(
    config: GatewayConfig,
    run: RunCommand,
    profiles: tuple[ProfileRecord, ...],
) -> list[str]:
    if not profiles:
        return []
    if config.legacy_wifi_migration != LEGACY_WIFI_MIGRATE_MATCHING:
        return [LEGACY_WIFI_MANUAL_ERROR]
    if not all(_matches_legacy_wifi(config, profile) for profile in profiles):
        return [LEGACY_WIFI_MISMATCH_ERROR]
    for profile in profiles:
        result = run(
            "nmcli",
            "connection",
            "delete",
            "uuid",
            profile.uuid,
            check=False,
        )
        if result.returncode != 0:
            return [LEGACY_WIFI_DELETE_ERROR]
    remaining = {
        profile.uuid
        for profile in NmInventory(run).profiles()
    }
    if any(profile.uuid in remaining for profile in profiles):
        return [LEGACY_WIFI_DELETE_ERROR]
    return []


def _matches_legacy_wifi(
    config: GatewayConfig,
    profile: ProfileRecord,
) -> bool:
    addresses = {
        value.strip()
        for value in re.split(r"[,;]", profile.ipv4_addresses)
        if value.strip()
    }
    return (
        profile.interface_name in {"", config.upstream_interface}
        and profile.name == f"Supervisor {config.upstream_interface}"
        and profile.ssid == config.hotspot_ssid
        and addresses == {config.upstream_address}
    )

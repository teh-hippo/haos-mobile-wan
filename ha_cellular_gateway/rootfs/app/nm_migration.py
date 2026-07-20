from __future__ import annotations

import re

from .command import RunCommand
from .config import GatewayConfig
from .nm_inventory import NmInventory, ProfileRecord
from .nm_profile import NmProfile
from .nm_profile_specs import legacy_usb_profile_spec

LEGACY_USB_DRIFT_ERROR = "The legacy iPhone USB profile has unexpected settings"
LINEAGE_WIFI_DELETE_ERROR = "A legacy Supervisor Wi-Fi profile could not be removed"


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


def is_lineage_wifi(config: GatewayConfig, profile: ProfileRecord) -> bool:
    addresses = {
        value.strip()
        for value in re.split(r"[,;]", profile.ipv4_addresses)
        if value.strip()
    }
    return (
        profile.connection_type == "802-11-wireless"
        and profile.interface_name in {"", config.upstream_interface}
        and profile.name == f"Supervisor {config.upstream_interface}"
        and profile.ssid == config.hotspot_ssid
        and addresses == {config.upstream_address}
    )


def clean_lineage_wifi(
    config: GatewayConfig,
    run: RunCommand,
    profiles: tuple[ProfileRecord, ...],
) -> list[str]:
    lineage = [profile for profile in profiles if is_lineage_wifi(config, profile)]
    if not lineage:
        return []
    for profile in lineage:
        result = run("nmcli", "connection", "delete", "uuid", profile.uuid, check=False)
        if result.returncode != 0:
            return [LINEAGE_WIFI_DELETE_ERROR]
    remaining = {profile.uuid for profile in NmInventory(run).profiles()}
    if any(profile.uuid in remaining for profile in lineage):
        return [LINEAGE_WIFI_DELETE_ERROR]
    return []

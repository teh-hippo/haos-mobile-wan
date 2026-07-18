from __future__ import annotations

from .command import RunCommand
from .config import GatewayConfig
from .const import LEGACY_WIFI_MIGRATE_MATCHING
from .nm_inventory import ProfileRecord
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
    errors: list[str] = []
    for profile in profiles:
        if not (
            profile.ssid == config.hotspot_ssid
            and config.upstream_address in profile.ipv4_addresses
        ):
            errors.append(LEGACY_WIFI_MISMATCH_ERROR)
            continue
        run(
            "nmcli",
            "connection",
            "delete",
            "uuid",
            profile.uuid,
            check=False,
        )
    return errors

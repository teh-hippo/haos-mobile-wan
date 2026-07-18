from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .config import GatewayConfig
from .const import LEGACY_WIFI_MIGRATE_MATCHING
from .errors import GatewayError
from .networkmanager_wifi import NetworkManagerWifi
from .nm_inventory import NmInventory, ProfileRecord
from .nm_preflight import inspect_nm_ownership
from .nm_profile import NmProfile
from .nm_profile_specs import (
    USB_PROFILE_UUID,
    WIFI_PROFILE_UUID,
    legacy_usb_profile_spec,
)
from .upstream_iphone import IPhoneUsbUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline

PROFILE_ERRORS = (
    GatewayError,
    OSError,
    subprocess.SubprocessError,
    ValueError,
)

LEGACY_WIFI_MANUAL_ERROR = (
    "Legacy Supervisor Wi-Fi profile requires manual cleanup"
)
LEGACY_WIFI_MISMATCH_ERROR = (
    "Legacy Supervisor Wi-Fi profile does not match the app configuration"
)
USB_PROFILE_DRIFT_ERROR = (
    "The app-owned iPhone USB profile has unexpected settings"
)
LEGACY_USB_DRIFT_ERROR = (
    "The legacy iPhone USB profile has unexpected settings"
)


class UpstreamLifecycle:
    def __init__(
        self,
        config: GatewayConfig,
        iphone: IPhoneUsbUpstream,
        wifi: NetworkManagerWifi,
    ) -> None:
        self.config = config
        self.iphone = iphone
        self.wifi = wifi
        self.inventory = NmInventory(iphone.run)
        self.legacy_usb = NmProfile(iphone.run, legacy_usb_profile_spec())
        self.error: str | None = None
        self.owned_profiles: dict[str, str] = {}
        self.legacy_wifi_profiles: tuple[ProfileRecord, ...] = ()
        self._iphone_dormant = False

    def load_state(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(uuid, str)
            for key, uuid in value.items()
        ):
            return "Persistent NetworkManager profile ownership is invalid"
        self.owned_profiles = dict(value)
        return None

    def state(self) -> dict[str, object] | None:
        return dict(self.owned_profiles) or None

    def activate(self, management: ManagementBaseline | None) -> None:
        self._iphone_dormant = False
        preflight = inspect_nm_ownership(
            self.config,
            self.inventory,
            management,
        )
        self.legacy_wifi_profiles = preflight.legacy_wifi_profiles
        errors = list(preflight.errors)
        errors.extend(self._migrate_legacy_usb())
        errors.extend(self._migrate_legacy_wifi())
        if not errors and self.config.uses_iphone:
            errors.extend(self._ensure_usb_profile())
        if not errors and self.config.uses_wifi:
            errors.extend(self._ensure_wifi_profile())
        self.error = "; ".join(dict.fromkeys(errors)) or None

    def deactivate(self, management: ManagementBaseline | None) -> None:
        del management
        errors: list[str] = []
        if not self._iphone_dormant:
            try:
                self.iphone.cleanup()
            except PROFILE_ERRORS as err:
                errors.append(f"iPhone USB cleanup failed: {err}")
            else:
                self._iphone_dormant = True
        errors.extend(
            self._release_profile(
                self.iphone.nm.profile,
                "iphone_usb",
                USB_PROFILE_DRIFT_ERROR,
            )
        )
        errors.extend(
            self._release_profile(
                self.wifi.profile,
                "wifi_hotspot",
                "The app-owned Wi-Fi hotspot profile has unexpected settings",
            )
        )
        errors.extend(self._migrate_legacy_usb())
        self.error = "; ".join(dict.fromkeys(errors)) or None

    def _ensure_usb_profile(self) -> list[str]:
        inspection = self.iphone.nm.profile.inspect()
        if inspection.state == "drifted":
            return [USB_PROFILE_DRIFT_ERROR]
        if inspection.state == "missing":
            self.iphone.nm.profile.create()
        self.owned_profiles["iphone_usb"] = USB_PROFILE_UUID
        return []

    def _ensure_wifi_profile(self) -> list[str]:
        error = self.wifi.ensure_profile()
        if error:
            return [error]
        self.owned_profiles["wifi_hotspot"] = WIFI_PROFILE_UUID
        return []

    def _release_profile(
        self,
        profile: NmProfile,
        key: str,
        drift_error: str,
    ) -> list[str]:
        inspection = profile.inspect()
        if inspection.state == "missing":
            self.owned_profiles.pop(key, None)
            return []
        if inspection.state == "drifted":
            return [drift_error]
        profile.deactivate()
        profile.delete()
        self.owned_profiles.pop(key, None)
        return []

    def _migrate_legacy_usb(self) -> list[str]:
        inspection = self.legacy_usb.inspect()
        if inspection.state == "missing":
            return []
        if inspection.state == "drifted":
            return [LEGACY_USB_DRIFT_ERROR]
        self.legacy_usb.deactivate()
        self.legacy_usb.delete()
        return []

    def _migrate_legacy_wifi(self) -> list[str]:
        if not self.legacy_wifi_profiles:
            return []
        if self.config.legacy_wifi_migration != LEGACY_WIFI_MIGRATE_MATCHING:
            return [LEGACY_WIFI_MANUAL_ERROR]
        errors: list[str] = []
        for profile in self.legacy_wifi_profiles:
            if not (
                profile.ssid == self.config.hotspot_ssid
                and self.config.upstream_address in profile.ipv4_addresses
            ):
                errors.append(LEGACY_WIFI_MISMATCH_ERROR)
                continue
            self.iphone.run(
                "nmcli",
                "connection",
                "delete",
                "uuid",
                profile.uuid,
                check=False,
            )
        return errors

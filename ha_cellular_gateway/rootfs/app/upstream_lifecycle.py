from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from .config import GatewayConfig
from .errors import GatewayError
from .networkmanager_wifi import WIFI_PROFILE_DRIFT_MESSAGE, NetworkManagerWifi
from .nm_inventory import NmInventory, ProfileRecord
from .nm_journal import NmOwnershipJournal
from .nm_migration import (
    LEGACY_WIFI_MANUAL_ERROR,
    migrate_legacy_usb,
    migrate_legacy_wifi,
)
from .nm_preflight import inspect_nm_ownership
from .nm_profile import NmProfile
from .upstream_iphone import IPhoneUsbUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline

PROFILE_ERRORS = (
    GatewayError,
    OSError,
    subprocess.SubprocessError,
    ValueError,
)

USB_PROFILE_DRIFT_ERROR = "The app-owned iPhone USB profile has unexpected settings"


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
        self.error: str | None = None
        self.journal = NmOwnershipJournal()
        self.legacy_wifi_profiles: tuple[ProfileRecord, ...] = ()
        self._iphone_dormant = False

    def load_state(self, value: object) -> str | None:
        return self.journal.load(value)

    def state(self) -> dict[str, object] | None:
        return self.journal.state()

    def set_persist(self, persist: Callable[[], None]) -> None:
        self.journal.set_persist(persist)

    def activate(self, management: ManagementBaseline | None) -> None:
        self._iphone_dormant = False
        errors: list[str] = []
        journal_error = self.journal.transition("acquiring")
        if journal_error:
            errors.append(journal_error)
        try:
            preflight = inspect_nm_ownership(
                self.config,
                self.inventory,
                management,
            )
            self.legacy_wifi_profiles = preflight.legacy_wifi_profiles
            errors.extend(preflight.errors)
            if not errors:
                errors.extend(migrate_legacy_usb(self.iphone.run))
                errors.extend(
                    migrate_legacy_wifi(
                        self.config,
                        self.iphone.run,
                        self.legacy_wifi_profiles,
                    )
                )
                errors.extend(self._release_unselected_profiles())
            if not errors and self.config.uses_iphone:
                errors.extend(self._ensure_usb_profile())
            if not errors and self.config.uses_wifi:
                if not self.config.hotspot_credentials_configured:
                    errors.append(
                        "Wi-Fi hotspot credentials are not configured"
                    )
                else:
                    errors.extend(self._ensure_wifi_profile())
            if errors and management is not None:
                errors.extend(self._release_all_profiles())
        except PROFILE_ERRORS as err:
            errors.append(f"NetworkManager profile operation failed: {err}")
        self.error = "; ".join(dict.fromkeys(errors)) or None
        journal_error = self.journal.transition(
            "active" if self.error is None else "blocked"
        )
        if journal_error:
            self.error = "; ".join(
                dict.fromkeys(filter(None, (self.error, journal_error)))
            )

    def deactivate(self, management: ManagementBaseline | None) -> None:
        del management
        errors: list[str] = []
        journal_error = self.journal.transition("releasing")
        if journal_error:
            errors.append(journal_error)
        if not self._iphone_dormant:
            try:
                self.iphone.cleanup()
            except PROFILE_ERRORS as err:
                errors.append(f"iPhone USB cleanup failed: {err}")
            else:
                self._iphone_dormant = True
        try:
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
                    WIFI_PROFILE_DRIFT_MESSAGE,
                )
            )
            errors.extend(migrate_legacy_usb(self.iphone.run))
        except PROFILE_ERRORS as err:
            errors.append(f"NetworkManager profile cleanup failed: {err}")
        self.error = "; ".join(dict.fromkeys(errors)) or None
        journal_error = self.journal.transition(
            "disabled" if self.error is None else "blocked"
        )
        if journal_error:
            self.error = "; ".join(
                dict.fromkeys(filter(None, (self.error, journal_error)))
            )

    def _ensure_usb_profile(self) -> list[str]:
        inspection = self.iphone.nm.profile.inspect()
        if inspection.state == "drifted":
            return [USB_PROFILE_DRIFT_ERROR]
        journal_error = self.journal.claim(
            "iphone_usb",
            self.iphone.nm.profile.spec,
        )
        if journal_error:
            return [journal_error]
        if inspection.state == "missing":
            self.iphone.nm.profile.create()
        return []

    def _release_unselected_profiles(self) -> list[str]:
        errors: list[str] = []
        if not self.config.uses_iphone:
            errors.extend(
                self._release_profile(
                    self.iphone.nm.profile,
                    "iphone_usb",
                    USB_PROFILE_DRIFT_ERROR,
                )
            )
        if not self.config.uses_wifi:
            errors.extend(
                self._release_profile(
                    self.wifi.profile,
                    "wifi_hotspot",
                    WIFI_PROFILE_DRIFT_MESSAGE,
                )
            )
        return errors

    def _release_all_profiles(self) -> list[str]:
        return [
            *self._release_profile(
                self.iphone.nm.profile,
                "iphone_usb",
                USB_PROFILE_DRIFT_ERROR,
            ),
            *self._release_profile(
                self.wifi.profile,
                "wifi_hotspot",
                WIFI_PROFILE_DRIFT_MESSAGE,
            ),
        ]

    def _ensure_wifi_profile(self) -> list[str]:
        inspection = self.wifi.profile.inspect()
        if inspection.state == "drifted":
            return [WIFI_PROFILE_DRIFT_MESSAGE]
        journal_error = self.journal.claim(
            "wifi_hotspot",
            self.wifi.profile.spec,
        )
        if journal_error:
            return [journal_error]
        if inspection.state == "missing":
            self.wifi.profile.create()
        return []

    def _release_profile(
        self,
        profile: NmProfile,
        key: str,
        drift_error: str,
    ) -> list[str]:
        inspection = profile.inspect()
        if inspection.state == "missing":
            journal_error = self.journal.release(key)
            if journal_error:
                return [journal_error]
            return []
        if inspection.state == "drifted":
            entry = self.journal.entry(key)
            fingerprint = (
                entry.get("fingerprint")
                if isinstance(entry, dict)
                else None
            )
            if (
                isinstance(fingerprint, dict)
                and profile.matches_fingerprint(fingerprint)
            ) or (
                entry is not None
                and self.journal.phase in {"acquiring", "releasing"}
                and profile.matches_identity()
            ):
                profile.deactivate()
                profile.delete()
                journal_error = self.journal.release(key)
                return [journal_error] if journal_error else []
            return [drift_error]
        profile.deactivate()
        profile.delete()
        journal_error = self.journal.release(key)
        if journal_error:
            return [journal_error]
        return []

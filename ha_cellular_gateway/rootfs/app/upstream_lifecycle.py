from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from .config import GatewayConfig
from .errors import GatewayError
from .networkmanager_wifi import NetworkManagerWifi, safe_wifi_unavailable
from .nm_inventory import NmInventory, ProfileRecord
from .nm_journal import NmOwnershipJournal
from .nm_migration import clean_lineage_wifi, migrate_legacy_usb
from .nm_preflight import WIFI_MANAGEMENT_CONFLICT, inspect_nm_ownership
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
        self.lineage_wifi_profiles: tuple[ProfileRecord, ...] = ()
        self._iphone_dormant = False

    def load_state(self, value: object) -> str | None:
        return self.journal.load(value)

    def state(self) -> dict[str, object] | None:
        return self.journal.state()

    def diagnostics(self) -> dict[str, object]:
        diagnostics = self.journal.diagnostics(
            legacy_wifi_profiles=len(self.lineage_wifi_profiles)
        )
        diagnostics["wifi_phase"] = self.wifi.phase()
        diagnostics["wifi_restore_pending"] = self.wifi.restore_pending
        return diagnostics

    def set_persist(self, persist: Callable[[], None]) -> None:
        self.journal.set_persist(persist)

    def _manage_iface(self, management: ManagementBaseline | None) -> str | None:
        return management.interface if management is not None else None

    def activate(self, management: ManagementBaseline | None) -> None:
        self._iphone_dormant = False
        errors: list[str] = []
        journal_error = self.journal.transition("acquiring")
        if journal_error:
            errors.append(journal_error)
        try:
            preflight = inspect_nm_ownership(
                self.config, self.inventory, management
            )
            self.lineage_wifi_profiles = preflight.lineage_wifi_profiles
            errors.extend(preflight.errors)
            if management is not None and WIFI_MANAGEMENT_CONFLICT not in errors:
                errors.extend(migrate_legacy_usb(self.iphone.run))
                errors.extend(
                    clean_lineage_wifi(
                        self.config, self.iphone.run, self.lineage_wifi_profiles
                    )
                )
            if not errors:
                errors.extend(self._release_unselected(management))
                if self.config.uses_iphone:
                    errors.extend(self._ensure_usb_profile())
                if self.config.uses_wifi:
                    errors.extend(self._claim_wifi(management))
            if errors and management is not None:
                errors.extend(self._release_all(management))
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
            errors.extend(self._release_usb_profile())
            errors.extend(self.wifi.release(self._manage_iface(management)))
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

    def recover(self, management: ManagementBaseline | None) -> list[str]:
        return self.wifi.recover(self._manage_iface(management))

    def _claim_wifi(self, management: ManagementBaseline | None) -> list[str]:
        if not self.config.hotspot_credentials_configured:
            return ["Wi-Fi hotspot credentials are not configured"]
        errors = self.wifi.claim(self._manage_iface(management))
        if self.config.uses_iphone:
            # Combined/fallback mode: a safely unavailable Wi-Fi adapter must not
            # fail closed or churn the healthy USB source. The blocker is still
            # recorded on the Wi-Fi controller for diagnostics.
            errors = [
                error for error in errors if not safe_wifi_unavailable(error)
            ]
        return errors

    def _ensure_usb_profile(self) -> list[str]:
        inspection = self.iphone.nm.profile.inspect()
        self.journal.set_profile_state("iphone_usb", inspection.state)
        if inspection.state == "drifted":
            return [USB_PROFILE_DRIFT_ERROR]
        journal_error = self.journal.claim("iphone_usb", self.iphone.nm.profile.spec)
        if journal_error:
            return [journal_error]
        if inspection.state == "missing":
            self.iphone.nm.profile.create()
            self.journal.set_profile_state("iphone_usb", "exact")
        return []

    def _release_unselected(
        self, management: ManagementBaseline | None
    ) -> list[str]:
        errors: list[str] = []
        if not self.config.uses_iphone:
            errors.extend(self._release_usb_profile())
        if not self.config.uses_wifi:
            errors.extend(self.wifi.release(self._manage_iface(management)))
        return errors

    def _release_all(self, management: ManagementBaseline | None) -> list[str]:
        return [
            *self._release_usb_profile(),
            *self.wifi.release(self._manage_iface(management)),
        ]

    def _release_usb_profile(self) -> list[str]:
        profile = self.iphone.nm.profile
        key = "iphone_usb"
        inspection = profile.inspect()
        self.journal.set_profile_state(key, inspection.state)
        if inspection.state == "missing":
            journal_error = self.journal.release(key)
            return [journal_error] if journal_error else []
        if inspection.state == "drifted":
            entry = self.journal.entry(key)
            fingerprint = entry.get("fingerprint") if isinstance(entry, dict) else None
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
                self.journal.set_profile_state(key, "missing")
                journal_error = self.journal.release(key)
                return [journal_error] if journal_error else []
            return [USB_PROFILE_DRIFT_ERROR]
        profile.deactivate()
        profile.delete()
        self.journal.set_profile_state(key, "missing")
        journal_error = self.journal.release(key)
        return [journal_error] if journal_error else []

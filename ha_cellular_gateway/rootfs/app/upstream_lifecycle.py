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
from .upstream_usb import UsbNetworkUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline

PROFILE_ERRORS = (
    GatewayError,
    OSError,
    subprocess.SubprocessError,
    ValueError,
)


class UpstreamLifecycle:
    def __init__(
        self,
        config: GatewayConfig,
        usb: UsbNetworkUpstream,
        usb_upstreams: tuple[UsbNetworkUpstream, ...],
        wifi: NetworkManagerWifi,
    ) -> None:
        self.config = config
        self.usb = usb
        self.usb_upstreams = usb_upstreams
        self.wifi = wifi
        self.inventory = NmInventory(usb.run)
        self.error: str | None = None
        self.journal = NmOwnershipJournal()
        self.lineage_wifi_profiles: tuple[ProfileRecord, ...] = ()
        self._usb_dormant = False

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
        self._usb_dormant = False
        errors: list[str] = []
        journal_error = self.journal.transition("acquiring")
        if journal_error:
            errors.append(journal_error)
        try:
            preflight = inspect_nm_ownership(self.config, self.inventory, management)
            self.lineage_wifi_profiles = preflight.lineage_wifi_profiles
            errors.extend(preflight.errors)
            if management is not None and WIFI_MANAGEMENT_CONFLICT not in errors:
                errors.extend(migrate_legacy_usb(self.usb.run))
                errors.extend(
                    clean_lineage_wifi(
                        self.config, self.usb.run, self.lineage_wifi_profiles
                    )
                )
            if not errors:
                errors.extend(self._release_unselected(management))
                if self.config.uses_usb:
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
        if not self._usb_dormant:
            try:
                self.usb.cleanup()
            except PROFILE_ERRORS as err:
                errors.append(f"{self.usb.cleanup_error_label}: {err}")
            else:
                self._usb_dormant = True
        try:
            for upstream in self.usb_upstreams:
                errors.extend(self._release_usb_profile(upstream))
            errors.extend(self.wifi.release(self._manage_iface(management)))
            errors.extend(migrate_legacy_usb(self.usb.run))
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
        if self.config.uses_usb:
            errors = [error for error in errors if not safe_wifi_unavailable(error)]
        return errors

    def _ensure_usb_profile(self) -> list[str]:
        profile = self.usb.nm.profile
        key = self.usb.profile_key
        inspection = profile.inspect()
        self.journal.set_profile_state(key, inspection.state)
        if inspection.state == "drifted":
            return [self.usb.profile_drift_error]
        journal_error = self.journal.claim(key, profile.spec)
        if journal_error:
            return [journal_error]
        if inspection.state == "missing":
            profile.create()
            self.journal.set_profile_state(key, "exact")
        return []

    def _release_unselected(self, management: ManagementBaseline | None) -> list[str]:
        errors: list[str] = []
        for upstream in self.usb_upstreams:
            if not self.config.uses_usb or upstream is not self.usb:
                errors.extend(self._release_usb_profile(upstream))
        if not self.config.uses_wifi:
            errors.extend(self.wifi.release(self._manage_iface(management)))
        return errors

    def _release_all(self, management: ManagementBaseline | None) -> list[str]:
        errors = [
            error
            for upstream in self.usb_upstreams
            for error in self._release_usb_profile(upstream)
        ]
        return [*errors, *self.wifi.release(self._manage_iface(management))]

    def _release_usb_profile(
        self,
        upstream: UsbNetworkUpstream,
    ) -> list[str]:
        profile = upstream.nm.profile
        key = upstream.profile_key
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
            return [upstream.profile_drift_error]
        profile.deactivate()
        profile.delete()
        self.journal.set_profile_state(key, "missing")
        journal_error = self.journal.release(key)
        return [journal_error] if journal_error else []

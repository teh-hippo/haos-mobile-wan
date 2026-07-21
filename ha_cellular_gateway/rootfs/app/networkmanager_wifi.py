from __future__ import annotations

import subprocess
import time
from collections.abc import Callable

from .command import RunCommand
from .config import GatewayConfig
from .errors import GatewayError
from .networkmanager import NetworkManagerResult
from .networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
    table_routes_state,
)
from .nm_device import read_device_state
from .nm_metadata import DbusWifiProfileMetadata, WifiProfileMetadata
from .nm_profile import NmProfile
from .nm_profile_specs import WIFI_ROUTE_TABLE, wifi_profile_spec
from .upstream_models import configured_upstream
from .wifi_activation import WifiActivator
from .wifi_custody import (
    DEVICE_MISSING,
    DEVICE_UNMANAGED,
    RADIO_HARD_OFF,
    RADIO_INSPECTION_UNAVAILABLE,
    RADIO_SOFT_OFF,
    WifiCustodian,
)
from .wifi_custody_marker import CustodyMarker, parse_marker

WIFI_NOT_ASSOCIATED = "Hotspot Wi-Fi is enabled but not associated"
WIFI_PROFILE_DRIFT_MESSAGE = (
    "The app-owned Wi-Fi hotspot profile has unexpected settings"
)
WIFI_ROUTE_MESSAGE = (
    f"NetworkManager Wi-Fi table {WIFI_ROUTE_TABLE} has unexpected routes"
)
WIFI_RULE_MESSAGE = (
    f"A policy rule selects the NetworkManager Wi-Fi table {WIFI_ROUTE_TABLE}"
)
WIFI_DEFAULT_MESSAGE = (
    "NetworkManager left a Wi-Fi hotspot default route in the main table"
)
WIFI_CUSTODY_STATE_INVALID = "Persistent Wi-Fi custody state is invalid"

CONTROL_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)

SAFE_WIFI_UNAVAILABLE = frozenset(
    {
        DEVICE_MISSING,
        DEVICE_UNMANAGED,
        RADIO_SOFT_OFF,
        RADIO_HARD_OFF,
        RADIO_INSPECTION_UNAVAILABLE,
    }
)


def safe_wifi_unavailable(message: str | None) -> bool:
    return message in SAFE_WIFI_UNAVAILABLE


class NetworkManagerWifi:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        metadata: WifiProfileMetadata | None = None,
    ) -> None:
        self.config = config
        self.run = run
        self.profile = NmProfile(run, wifi_profile_spec(config), monotonic=monotonic)
        self.custodian = WifiCustodian(
            config.upstream_interface,
            run,
            self.profile,
            metadata=metadata or DbusWifiProfileMetadata(self.profile.spec.uuid),
            excluded_uuids=lambda: {self.profile.spec.uuid},
        )
        self.activator = WifiActivator(
            run, self.profile, config.hotspot_ssid, monotonic=monotonic
        )
        self.marker: CustodyMarker | None = None
        self.persist: Callable[[], None] = lambda: None
        self.held = False
        self.blocker: str | None = None
        self.restore_pending = False

    def set_persist(self, persist: Callable[[], None]) -> None:
        self.persist = persist

    def state(self) -> dict[str, object] | None:
        return self.marker.as_state() if self.marker is not None else None

    def load_state(self, value: object) -> str | None:
        if value is None:
            return None
        marker = parse_marker(value)
        if marker is None:
            return WIFI_CUSTODY_STATE_INVALID
        self.marker = marker
        return None

    def phase(self) -> str:
        if self.blocker:
            return "blocked"
        if self.restore_pending:
            return "restoration_pending"
        if not self.held:
            return "released"
        if self.activator.sticky:
            return "attention"
        return "held"

    def claim(self, management_interface: str | None) -> list[str]:
        self.blocker = None
        existing = self.marker or self.custodian.read_profile_marker()
        errors = self.custodian.hold(management_interface, existing)
        if errors:
            self.held = False
            self.blocker = errors[0]
            return errors
        inspection = self.profile.inspect()
        if inspection.state == "drifted":
            self.held = False
            self.blocker = WIFI_PROFILE_DRIFT_MESSAGE
            return [WIFI_PROFILE_DRIFT_MESSAGE]
        if inspection.state == "missing":
            self.profile.create()
        self.marker = self.custodian.marker
        gate_errors = self.custodian.apply_gate(self.persist)
        if gate_errors:
            self.held = False
            self.blocker = gate_errors[0]
            return gate_errors
        self.held = True
        return []

    def release(self, management_interface: str | None) -> list[str]:
        marker = self.marker or self.custodian.read_profile_marker()
        errors = self.custodian.release(management_interface, marker, self.persist)
        self.restore_pending = bool(errors)
        self.activator.reset()
        if not errors:
            self.marker = None
            self.held = False
            self.blocker = None
            self.persist()
        return errors

    def recover(self, management_interface: str | None) -> list[str]:
        marker = self.marker or self.custodian.read_profile_marker()
        if marker is not None:
            self.marker = marker
            return self.release(management_interface)
        if self.profile.inspect().state == "exact":
            self.profile.deactivate()
            self.profile.delete()
        return []

    def inspect(self) -> NetworkManagerResult:
        try:
            return self._inspect()
        except CONTROL_ERRORS:
            return NetworkManagerResult(
                None,
                "waiting",
                "NetworkManager Wi-Fi inspection is unavailable",
                True,
            )

    def _inspect(self) -> NetworkManagerResult:
        if self.blocker:
            return NetworkManagerResult(
                None, "blocked", self.blocker, safe_wifi_unavailable(self.blocker)
            )
        interface = self.custodian.interface
        if not self.held or interface is None:
            return NetworkManagerResult(None, "waiting", WIFI_NOT_ASSOCIATED, True)
        active = self.profile.active_uuid(interface)
        if active == self.profile.spec.uuid:
            self.activator.note_associated()
            return self._verify_active(interface)
        return self._drive(interface, active)

    def _drive(self, interface: str, active: str) -> NetworkManagerResult:
        device = read_device_state(self.run, interface)
        fingerprint = (device.managed, device.autoconnect, device.radio_software)
        foreign_active = bool(active) and active != self.profile.spec.uuid
        outcome = self.activator.drive(
            interface, active, fingerprint, foreign_active=foreign_active
        )
        if outcome.phase == "associated":
            return self._verify_active(interface)
        return NetworkManagerResult(None, outcome.phase, outcome.message, True)

    def _verify_active(self, interface: str) -> NetworkManagerResult:
        if main_default_present(self.run, interface):
            return NetworkManagerResult(None, "invalid", WIFI_DEFAULT_MESSAGE, False)
        if rule_selects_table(self.run, WIFI_ROUTE_TABLE):
            return NetworkManagerResult(None, "invalid", WIFI_RULE_MESSAGE, False)
        addresses = self.profile.device_values(interface, "IP4.ADDRESS")
        if addresses != [self.config.upstream_address]:
            return NetworkManagerResult(None, "waiting", WIFI_NOT_ASSOCIATED, True)
        upstream = configured_upstream(self.config)
        routes = networkmanager_routes(self.run, WIFI_ROUTE_TABLE)
        route_state = table_routes_state(routes, interface, upstream)
        if route_state == "invalid":
            return NetworkManagerResult(None, "invalid", WIFI_ROUTE_MESSAGE, False)
        if route_state == "waiting":
            return NetworkManagerResult(None, "waiting", WIFI_NOT_ASSOCIATED, True)
        return NetworkManagerResult(upstream, "active", None, True)

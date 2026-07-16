from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .command import RunCommand
from .config import GatewayConfig
from .networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
    table_gateway,
    table_routes_state,
)
from .networkmanager_profile import (
    EXPECTED_SETTINGS,
    MODIFY_SETTINGS,
    PROFILE_NAME,
    PROFILE_UUID,
    READ_FIELDS,
    ROUTE_TABLE,
    normalise_setting,
)
from .upstream_models import ResolvedUpstream, validate_dynamic_lease

ACTIVATION_COOLDOWN_SECONDS = 30
LEASE_OWNER = "networkmanager"

FOREIGN_MESSAGE = (
    "NetworkManager could not activate the app iPhone USB profile because a "
    "different profile remains active"
)
INACTIVE_MESSAGE = "Waiting for NetworkManager to activate the iPhone USB profile"
LEASE_MESSAGE = "Waiting for the NetworkManager iPhone USB lease"
MAIN_DEFAULT_MESSAGE = (
    "NetworkManager left an iPhone USB default route in the main table"
)
RULE_MESSAGE = (
    f"A policy rule selects the NetworkManager iPhone USB table {ROUTE_TABLE}"
)
TABLE_MESSAGE = (
    f"NetworkManager iPhone USB table {ROUTE_TABLE} has unexpected routes"
)
MULTIPLE_ADDRESS_MESSAGE = "The iPhone USB interface has more than one IPv4 address"


@dataclass(frozen=True)
class NetworkManagerResult:
    upstream: ResolvedUpstream | None
    state: str
    error: str | None
    safe: bool


class NetworkManagerIphone:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.run = run
        self._monotonic = monotonic
        self._last_activation: float | None = None
        self._needs_reactivation = False
        self._profile_checked = False

    def ensure_profile(self) -> None:
        if self._profile_checked:
            return
        settings = self._profile_settings()
        if settings is None:
            self._create_profile()
        else:
            drifted = self._drifted_fields(settings)
            if drifted:
                print(
                    "networkmanager: repairing profile fields: "
                    + ",".join(drifted),
                    flush=True,
                )
                self._apply_settings()
                self._needs_reactivation = True
        self._profile_checked = True

    def _drifted_fields(self, settings: dict[str, str]) -> list[str]:
        return [
            field
            for field, expected in EXPECTED_SETTINGS.items()
            if normalise_setting(settings.get(field, "")) != expected
        ]

    def inspect(self, interface: str) -> NetworkManagerResult:
        state = self._ensure_active(interface)
        if state == "foreign":
            return NetworkManagerResult(None, "foreign", FOREIGN_MESSAGE, False)
        if state == "inactive":
            return NetworkManagerResult(None, "waiting", INACTIVE_MESSAGE, True)
        if main_default_present(self.run, interface):
            return NetworkManagerResult(None, "invalid", MAIN_DEFAULT_MESSAGE, False)
        if rule_selects_table(self.run, ROUTE_TABLE):
            return NetworkManagerResult(None, "invalid", RULE_MESSAGE, False)
        addresses = self._device_values(interface, "IP4.ADDRESS")
        if len(addresses) > 1:
            return NetworkManagerResult(
                None, "invalid", MULTIPLE_ADDRESS_MESSAGE, False
            )
        if not addresses:
            return NetworkManagerResult(None, "waiting", LEASE_MESSAGE, True)
        routes = networkmanager_routes(self.run, ROUTE_TABLE)
        gateway, gateway_state = table_gateway(routes, interface)
        if gateway_state == "invalid":
            return NetworkManagerResult(None, "invalid", TABLE_MESSAGE, False)
        if gateway is None:
            return NetworkManagerResult(None, "waiting", LEASE_MESSAGE, True)
        upstream, error = validate_dynamic_lease(
            self.config,
            interface,
            addresses[0],
            gateway,
        )
        if error:
            return NetworkManagerResult(None, "invalid", error, False)
        assert upstream is not None
        route_state = table_routes_state(routes, interface, upstream)
        if route_state == "invalid":
            return NetworkManagerResult(None, "invalid", TABLE_MESSAGE, False)
        if route_state == "waiting":
            return NetworkManagerResult(None, "waiting", LEASE_MESSAGE, True)
        return NetworkManagerResult(upstream, "active", None, True)

    def _profile_settings(self) -> dict[str, str] | None:
        result = self.run(
            "nmcli",
            "-g",
            ",".join(READ_FIELDS),
            "connection",
            "show",
            PROFILE_UUID,
            check=False,
        )
        if result.returncode != 0:
            return None
        values = (result.stdout or "").splitlines()
        return {
            field: values[index].strip() if index < len(values) else ""
            for index, field in enumerate(READ_FIELDS)
        }

    def _create_profile(self) -> None:
        arguments = [
            "connection",
            "add",
            "type",
            "ethernet",
            "con-name",
            PROFILE_NAME,
            "connection.uuid",
            PROFILE_UUID,
            "ifname",
            "*",
        ]
        for field, value in MODIFY_SETTINGS:
            if field != "connection.interface-name":
                arguments += [field, value]
        self.run("nmcli", *arguments)

    def _apply_settings(self) -> None:
        arguments: list[str] = ["connection", "modify", PROFILE_UUID]
        for field, value in MODIFY_SETTINGS:
            arguments += [field, value]
        self.run("nmcli", *arguments)

    def _ensure_active(self, interface: str) -> str:
        active = self._active_connection(interface)
        if active == PROFILE_UUID and not self._needs_reactivation:
            self._last_activation = None
            return "active"
        foreign = bool(active and active != PROFILE_UUID)
        if self._activation_due():
            self.run(
                "nmcli",
                "--wait",
                "8",
                "connection",
                "up",
                "uuid",
                PROFILE_UUID,
                "ifname",
                interface,
                check=False,
                timeout=15,
            )
            self._last_activation = self._monotonic()
            active = self._active_connection(interface)
            if active == PROFILE_UUID:
                self._last_activation = None
                self._needs_reactivation = False
                return "active"
            foreign = foreign or bool(active and active != PROFILE_UUID)
        return "foreign" if foreign else "inactive"

    def _activation_due(self) -> bool:
        if self._last_activation is None:
            return True
        return self._monotonic() - self._last_activation >= ACTIVATION_COOLDOWN_SECONDS

    def _active_connection(self, interface: str) -> str:
        result = self.run(
            "nmcli",
            "-g",
            "GENERAL.CON-UUID",
            "device",
            "show",
            interface,
            check=False,
        )
        if result.returncode != 0:
            return ""
        value = (result.stdout or "").strip()
        return "" if value == "--" else value

    def _device_values(self, interface: str, field: str) -> list[str]:
        result = self.run(
            "nmcli",
            "-g",
            field,
            "device",
            "show",
            interface,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [
            stripped
            for line in (result.stdout or "").splitlines()
            if (stripped := line.strip()) and stripped != "--"
        ]

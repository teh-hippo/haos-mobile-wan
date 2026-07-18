from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .command import RunCommand
from .config import GatewayConfig
from .errors import GatewayError
from .nm_profile import ACTIVATION_COOLDOWN_SECONDS, NmProfile
from .nm_profile_specs import USB_ROUTE_TABLE, usb_profile_spec
from .networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
    table_gateway,
    table_routes_state,
)
from .networkmanager_profile import (
    EXPECTED_SETTINGS,
    PROFILE_NAME,
    PROFILE_UUID,
    ROUTE_TABLE,
)
from .upstream_models import ResolvedUpstream, validate_dynamic_lease

if TYPE_CHECKING:
    from .management import ManagementBaseline

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
    f"A policy rule selects the NetworkManager iPhone USB table {USB_ROUTE_TABLE}"
)
TABLE_MESSAGE = (
    f"NetworkManager iPhone USB table {USB_ROUTE_TABLE} has unexpected routes"
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
        self.profile = NmProfile(
            run,
            usb_profile_spec(),
            monotonic=monotonic,
        )

    def inspect(
        self, interface: str, management: ManagementBaseline | None = None
    ) -> NetworkManagerResult:
        state = self.profile.activate(interface)
        if state == "foreign":
            return NetworkManagerResult(None, "foreign", FOREIGN_MESSAGE, False)
        if state == "waiting":
            return NetworkManagerResult(None, "waiting", INACTIVE_MESSAGE, True)
        if main_default_present(self.run, interface):
            return NetworkManagerResult(None, "invalid", MAIN_DEFAULT_MESSAGE, False)
        if rule_selects_table(self.run, USB_ROUTE_TABLE):
            return NetworkManagerResult(None, "invalid", RULE_MESSAGE, False)
        addresses = self.profile.device_values(interface, "IP4.ADDRESS")
        if len(addresses) > 1:
            return NetworkManagerResult(
                None, "invalid", MULTIPLE_ADDRESS_MESSAGE, False
            )
        if not addresses:
            return NetworkManagerResult(None, "waiting", LEASE_MESSAGE, True)
        routes = networkmanager_routes(self.run, USB_ROUTE_TABLE)
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
            management,
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

    def continuity(self, upstream: ResolvedUpstream) -> bool:
        try:
            if self.profile.active_uuid(upstream.interface) != self.profile.spec.uuid:
                return False
            if main_default_present(self.run, upstream.interface):
                return False
            if rule_selects_table(self.run, USB_ROUTE_TABLE):
                return False
            if self.profile.device_values(
                upstream.interface,
                "IP4.ADDRESS",
            ) != [upstream.address]:
                return False
            routes = networkmanager_routes(self.run, USB_ROUTE_TABLE)
            return (
                table_routes_state(routes, upstream.interface, upstream)
                == "ready"
            )
        except (
            GatewayError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ):
            return False

    def release_profile(self) -> None:
        self.profile.deactivate()
        self.profile.delete()

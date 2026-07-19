from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .command import RunCommand
from .config import GatewayConfig
from .const import GENERIC_USB, IPHONE_USB
from .errors import GatewayError
from .nm_profile import ACTIVATION_COOLDOWN_SECONDS, NmProfile, ProfileSpec
from .nm_profile_specs import (
    USB_ROUTE_TABLE,
    generic_usb_profile_spec,
    usb_profile_spec,
)
from .networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
    table_gateway,
    table_routes_state,
)
from .upstream_models import ResolvedUpstream, validate_dynamic_lease

if TYPE_CHECKING:
    from .management import ManagementBaseline

LEASE_OWNER = "networkmanager"

RULE_MESSAGE = (
    f"A policy rule selects the NetworkManager USB table {USB_ROUTE_TABLE}"
)
MULTIPLE_ADDRESS_MESSAGE = (
    "The iPhone USB interface has more than one IPv4 address"
)


@dataclass(frozen=True)
class NetworkManagerResult:
    upstream: ResolvedUpstream | None
    state: str
    error: str | None
    safe: bool


class NetworkManagerUsb:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        profile_spec: ProfileSpec,
        connection: str,
        label: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.run = run
        self.connection = connection
        self.label = label
        self.profile = NmProfile(run, profile_spec, monotonic=monotonic)

    def inspect(
        self, interface: str, management: ManagementBaseline | None = None
    ) -> NetworkManagerResult:
        state = self.profile.activate(interface)
        if state == "foreign":
            return NetworkManagerResult(
                None,
                "foreign",
                f"NetworkManager could not activate the app {self.label} profile "
                "because a different profile remains active",
                False,
            )
        if state == "waiting":
            return NetworkManagerResult(
                None,
                "waiting",
                f"Waiting for NetworkManager to activate the {self.label} profile",
                True,
            )
        if main_default_present(self.run, interface):
            return NetworkManagerResult(
                None,
                "invalid",
                f"NetworkManager left a {self.label} default route in the main table",
                False,
            )
        if rule_selects_table(self.run, USB_ROUTE_TABLE):
            return NetworkManagerResult(None, "invalid", RULE_MESSAGE, False)
        addresses = self.profile.device_values(interface, "IP4.ADDRESS")
        if len(addresses) > 1:
            message = (
                MULTIPLE_ADDRESS_MESSAGE
                if self.connection == IPHONE_USB
                else f"The {self.label} interface has more than one IPv4 address"
            )
            return NetworkManagerResult(
                None,
                "invalid",
                message,
                False,
            )
        if not addresses:
            return NetworkManagerResult(
                None,
                "waiting",
                f"Waiting for the NetworkManager {self.label} lease",
                True,
            )
        routes = networkmanager_routes(self.run, USB_ROUTE_TABLE)
        gateway, gateway_state = table_gateway(routes, interface)
        table_message = (
            f"NetworkManager {self.label} table {USB_ROUTE_TABLE} "
            "has unexpected routes"
        )
        if gateway_state == "invalid":
            return NetworkManagerResult(None, "invalid", table_message, False)
        if gateway is None:
            return NetworkManagerResult(
                None,
                "waiting",
                f"Waiting for the NetworkManager {self.label} lease",
                True,
            )
        upstream, error = validate_dynamic_lease(
            self.config,
            interface,
            addresses[0],
            gateway,
            management,
            connection=self.connection,
            label=self.label,
        )
        if error:
            return NetworkManagerResult(None, "invalid", error, False)
        assert upstream is not None
        route_state = table_routes_state(routes, interface, upstream)
        if route_state == "invalid":
            return NetworkManagerResult(None, "invalid", table_message, False)
        if route_state == "waiting":
            return NetworkManagerResult(
                None,
                "waiting",
                f"Waiting for the NetworkManager {self.label} lease",
                True,
            )
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


class NetworkManagerIphone(NetworkManagerUsb):
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            config,
            run,
            profile_spec=usb_profile_spec(),
            connection=IPHONE_USB,
            label="iPhone USB",
            monotonic=monotonic,
        )


class NetworkManagerGenericUsb(NetworkManagerUsb):
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            config,
            run,
            profile_spec=generic_usb_profile_spec(),
            connection=GENERIC_USB,
            label="generic USB",
            monotonic=monotonic,
        )

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .command import RunCommand
from .config import GatewayConfig
from .hotspot import WIFI_NOT_ASSOCIATED
from .networkmanager import NetworkManagerResult
from .networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
    table_routes_state,
)
from .nm_profile import NmProfile
from .nm_profile_specs import WIFI_ROUTE_TABLE, wifi_profile_spec
from .upstream_models import configured_upstream

_LOGGER = logging.getLogger(__name__)

WIFI_FOREIGN_MESSAGE = (
    "A different NetworkManager profile controls the Wi-Fi hotspot adapter"
)
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


class NetworkManagerWifi:
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
            wifi_profile_spec(config),
            monotonic=monotonic,
        )

    def ensure_profile(self) -> str | None:
        inspection = self.profile.inspect()
        if inspection.state == "missing":
            self.profile.create()
            return None
        if inspection.state == "drifted":
            _LOGGER.warning(
                "Wi-Fi profile drift detected: %s",
                ",".join(inspection.drifted_fields),
            )
            return WIFI_PROFILE_DRIFT_MESSAGE
        return None

    def inspect(self) -> NetworkManagerResult:
        state = self.profile.activate(self.config.upstream_interface)
        if state == "foreign":
            return NetworkManagerResult(
                None,
                "foreign",
                WIFI_FOREIGN_MESSAGE,
                False,
            )
        if state == "waiting":
            return NetworkManagerResult(
                None,
                "waiting",
                WIFI_NOT_ASSOCIATED,
                True,
            )
        if main_default_present(self.run, self.config.upstream_interface):
            return NetworkManagerResult(
                None,
                "invalid",
                WIFI_DEFAULT_MESSAGE,
                False,
            )
        if rule_selects_table(self.run, WIFI_ROUTE_TABLE):
            return NetworkManagerResult(
                None,
                "invalid",
                WIFI_RULE_MESSAGE,
                False,
            )
        addresses = self.profile.device_values(
            self.config.upstream_interface,
            "IP4.ADDRESS",
        )
        if addresses != [self.config.upstream_address]:
            return NetworkManagerResult(
                None,
                "waiting",
                WIFI_NOT_ASSOCIATED,
                True,
            )
        upstream = configured_upstream(self.config)
        routes = networkmanager_routes(self.run, WIFI_ROUTE_TABLE)
        route_state = table_routes_state(
            routes,
            self.config.upstream_interface,
            upstream,
        )
        if route_state == "invalid":
            return NetworkManagerResult(
                None,
                "invalid",
                WIFI_ROUTE_MESSAGE,
                False,
            )
        if route_state == "waiting":
            return NetworkManagerResult(
                None,
                "waiting",
                WIFI_NOT_ASSOCIATED,
                True,
            )
        return NetworkManagerResult(upstream, "active", None, True)

    def release_profile(self) -> None:
        self.profile.deactivate()
        self.profile.delete()

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import GatewayConfig
from .const import WIFI_HOTSPOT
from .networkmanager_wifi import NetworkManagerWifi
from .upstream_models import ResolvedUpstream
from .upstream_usb import UsbNetworkUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline


@dataclass(frozen=True)
class ConnectionResolution:
    upstream: ResolvedUpstream | None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    fallback_active: bool = False
    fallback_reason: str | None = None


class MobileConnectionResolver:
    def __init__(
        self,
        config: GatewayConfig,
        usb: UsbNetworkUpstream,
        wifi: NetworkManagerWifi,
        *,
        wifi_error: str | None = None,
    ) -> None:
        self.config = config
        self.usb = usb
        self.wifi = wifi
        self.wifi_error = wifi_error

    def resolve(
        self,
        management: ManagementBaseline | None = None,
        downstream_interface: str | None = None,
    ) -> ConnectionResolution:
        if self.config.mobile_connection == WIFI_HOTSPOT:
            if self.wifi_error:
                return ConnectionResolution(None, errors=(self.wifi_error,))
            result = self.wifi.inspect()
            return ConnectionResolution(
                result.upstream,
                errors=(result.error,) if result.error else (),
            )

        upstream, usb_errors = self.usb.resolve(
            management,
            downstream_interface,
        )
        if not self.usb.fallback_allowed():
            upstream = None
            usb_errors = [
                self.usb.pairing_message
                or f"{self.usb.label} ownership is unsafe"
            ]
        if self.config.uses_usb and not self.config.uses_wifi:
            return ConnectionResolution(
                upstream,
                errors=tuple(usb_errors),
            )

        if not self.config.usb_with_wifi_fallback:
            return ConnectionResolution(
                None,
                errors=("Unsupported mobile connection",),
            )

        if self.wifi_error:
            return ConnectionResolution(
                None,
                errors=(self.wifi_error,),
            )
        wifi = self.wifi.inspect()
        if not wifi.safe:
            return ConnectionResolution(
                None,
                errors=(wifi.error,) if wifi.error else (),
            )
        if upstream is not None and not usb_errors:
            return ConnectionResolution(
                upstream,
                warnings=(wifi.error,) if wifi.error else (),
            )

        reason = "; ".join(usb_errors) or self.usb.unavailable_message
        if not self.usb.fallback_safe:
            return ConnectionResolution(
                None,
                errors=tuple(usb_errors) or (reason,),
                fallback_reason=reason,
            )
        if wifi.upstream is not None and wifi.error is None:
            return ConnectionResolution(
                wifi.upstream,
                fallback_active=True,
                fallback_reason=reason,
            )
        errors = tuple(
            error
            for error in (*usb_errors, wifi.error)
            if error
        )
        return ConnectionResolution(
            None,
            errors=errors,
            fallback_reason=reason,
        )

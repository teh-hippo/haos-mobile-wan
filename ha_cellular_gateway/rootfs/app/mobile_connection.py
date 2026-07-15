from __future__ import annotations

from dataclasses import dataclass

from .config import GatewayConfig
from .const import IPHONE_USB, IPHONE_USB_WIFI_FALLBACK, WIFI_HOTSPOT
from .upstream_iphone import IPhoneUsbUpstream
from .upstream_models import ResolvedUpstream, configured_upstream


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
        iphone: IPhoneUsbUpstream,
        *,
        wifi_error: str | None = None,
    ) -> None:
        self.config = config
        self.iphone = iphone
        self.wifi_error = wifi_error

    def resolve(self) -> ConnectionResolution:
        if self.config.mobile_connection == WIFI_HOTSPOT:
            return ConnectionResolution(
                configured_upstream(self.config),
                errors=(self.wifi_error,) if self.wifi_error else (),
            )

        upstream, usb_errors = self.iphone.resolve()
        if not self.iphone.fallback_allowed():
            upstream = None
            usb_errors = [
                self.iphone.pairing_message
                or "USB (iPhone) ownership is unsafe"
            ]
        if self.config.mobile_connection == IPHONE_USB:
            return ConnectionResolution(
                upstream,
                errors=tuple(usb_errors),
            )

        if self.config.mobile_connection != IPHONE_USB_WIFI_FALLBACK:
            return ConnectionResolution(
                None,
                errors=("Unsupported mobile connection",),
            )

        if upstream is not None and not usb_errors:
            return ConnectionResolution(
                upstream,
                warnings=(self.wifi_error,) if self.wifi_error else (),
            )

        reason = "; ".join(usb_errors) or "USB (iPhone) is unavailable"
        if not self.iphone.fallback_safe:
            return ConnectionResolution(
                None,
                errors=tuple(usb_errors) or (reason,),
                fallback_reason=reason,
            )
        return ConnectionResolution(
            configured_upstream(self.config),
            errors=(self.wifi_error,) if self.wifi_error else (),
            fallback_active=True,
            fallback_reason=reason,
        )

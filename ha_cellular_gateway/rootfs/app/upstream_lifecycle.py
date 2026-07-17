from __future__ import annotations

import time
from collections.abc import Callable

from .config import GatewayConfig
from .hotspot import configure_hotspot
from .upstream_iphone import IPhoneUsbUpstream

HotspotConfigure = Callable[..., str | None]

RETRY_SECONDS = 60


class UpstreamLifecycle:
    def __init__(
        self,
        config: GatewayConfig,
        iphone: IPhoneUsbUpstream,
        *,
        configure: HotspotConfigure = configure_hotspot,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.iphone = iphone
        self.configure = configure
        self.clock = clock
        self.error: str | None = None
        self._hotspot_enabled: bool | None = None
        self._retry_at = 0.0
        self._iphone_dormant = False

    def activate(self, management_interface: str | None) -> None:
        self._iphone_dormant = False
        self._set_hotspot(True, management_interface)

    def deactivate(self, management_interface: str | None) -> None:
        if not self._iphone_dormant:
            self.iphone.cleanup()
            self._iphone_dormant = True
        self._set_hotspot(False, management_interface)

    def _set_hotspot(
        self,
        enabled: bool,
        management_interface: str | None,
    ) -> None:
        if not (
            self.config.uses_wifi
            and self.config.hotspot_credentials_configured
        ):
            self.error = None
            self._hotspot_enabled = enabled
            return
        if management_interface == self.config.upstream_interface:
            self.error = (
                "Hotspot Wi-Fi interface is the management interface"
            )
            return
        if self._hotspot_enabled == enabled and self.error is None:
            return
        now = self.clock()
        if self.error is not None and now < self._retry_at:
            return
        error = self.configure(self.config, enabled=enabled)
        if error is not None:
            self.error = error
            self._retry_at = now + RETRY_SECONDS
            return
        self.error = None
        self._retry_at = 0.0
        self._hotspot_enabled = enabled

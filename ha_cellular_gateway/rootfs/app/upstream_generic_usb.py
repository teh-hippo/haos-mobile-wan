from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .config import GatewayConfig
from .networkmanager import NetworkManagerGenericUsb
from .nm_inventory import NmInventory
from .nm_profile_specs import GENERIC_USB_DRIVERS, GENERIC_USB_PROFILE_UUID
from .upstream_usb import UpstreamResolution, UsbNetworkUpstream
from .usb_network import interface_carrier, interfaces_by_driver

if TYPE_CHECKING:
    from .command import RunCommand
    from .management import ManagementBaseline


class GenericUsbUpstream(UsbNetworkUpstream):
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        sys_net_root: Path = Path("/sys/class/net"),
        network_manager: NetworkManagerGenericUsb | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            run,
            network_manager
            or NetworkManagerGenericUsb(config, run, monotonic=monotonic),
            label="generic USB",
            ready_state="ready",
            monotonic=monotonic,
        )
        self.sys_net_root = sys_net_root

    def resolve(
        self,
        management: ManagementBaseline | None = None,
        downstream_interface: str | None = None,
    ) -> UpstreamResolution:
        self._begin()
        excluded = {
            interface
            for interface in (
                management.interface if management else None,
                downstream_interface,
            )
            if interface
        }
        interfaces = interfaces_by_driver(
            self.sys_net_root,
            GENERIC_USB_DRIVERS,
            excluded=excluded,
        )
        if not interfaces:
            self._forget_lease()
            return self._fail(
                "waiting_for_device",
                "Connect one supported generic USB tethering device",
            )
        if len(interfaces) > 1:
            self._forget_lease()
            return self._fail(
                "multiple_devices",
                "Multiple generic USB tethering interfaces are present",
                safe=False,
            )
        interface = interfaces[0]
        foreign = NmInventory(self.run).foreign_wired_profiles(
            interface,
            drivers=set(GENERIC_USB_DRIVERS),
            allowed_uuids={GENERIC_USB_PROFILE_UUID},
        )
        if foreign:
            self._forget_lease()
            return self._fail(
                "profile_conflict",
                "A foreign NetworkManager profile can control generic USB",
                safe=False,
            )
        return self._resolve_network(
            interface,
            interface_carrier(self.sys_net_root, interface),
            management,
            carrier_state="waiting_for_carrier",
            carrier_message=("Enable USB tethering or connect the USB network dongle"),
        )

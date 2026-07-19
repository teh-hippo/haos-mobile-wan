from __future__ import annotations

from .command import RunCommand
from .config import GatewayConfig
from .upstream_generic_usb import GenericUsbUpstream
from .upstream_iphone import IPhoneUsbUpstream
from .upstream_usb import UsbNetworkUpstream


def build_usb_upstreams(
    config: GatewayConfig,
    run: RunCommand,
) -> tuple[UsbNetworkUpstream, tuple[UsbNetworkUpstream, ...]]:
    iphone = IPhoneUsbUpstream(config, run)
    generic = GenericUsbUpstream(config, run)
    selected = generic if config.uses_generic_usb else iphone
    return selected, (iphone, generic)

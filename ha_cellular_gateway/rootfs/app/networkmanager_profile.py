from __future__ import annotations

from .nm_profile import normalise_setting
from .nm_profile_specs import (
    USB_DHCP_TIMEOUT_SECONDS,
    USB_PROFILE_NAME,
    USB_PROFILE_UUID,
    USB_ROUTE_TABLE,
    usb_profile_spec,
)

_SPEC = usb_profile_spec()

PROFILE_NAME = USB_PROFILE_NAME
PROFILE_UUID = USB_PROFILE_UUID
ROUTE_TABLE = USB_ROUTE_TABLE
DHCP_TIMEOUT_SECONDS = USB_DHCP_TIMEOUT_SECONDS
MODIFY_SETTINGS = _SPEC.settings
EXPECTED_SETTINGS = _SPEC.expected
READ_FIELDS = _SPEC.read_fields

__all__ = [
    "DHCP_TIMEOUT_SECONDS",
    "EXPECTED_SETTINGS",
    "MODIFY_SETTINGS",
    "PROFILE_NAME",
    "PROFILE_UUID",
    "READ_FIELDS",
    "ROUTE_TABLE",
    "normalise_setting",
]

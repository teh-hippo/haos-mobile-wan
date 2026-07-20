from __future__ import annotations

from .mqtt_labels import (
    ACTIVE_CONNECTION_LABELS,
    MOBILE_CONNECTION_DEFAULT_LABEL,
    MOBILE_CONNECTION_INTERNAL_LABELS,
    NO_ACTIVE_CONNECTION_LABEL,
    NO_INTERFACE_LABEL,
    NOT_CONNECTED_LABEL,
    UNKNOWN_PAIRING_LABEL,
    UPSTREAM_PAIRING_STATE_LABELS,
)

ENUM_SENSORS = (
    (
        "mobile_connection",
        "Connection method",
        "mobile_connection",
        MOBILE_CONNECTION_INTERNAL_LABELS,
        MOBILE_CONNECTION_DEFAULT_LABEL,
        "mdi:connection",
        True,
    ),
    (
        "active_connection",
        "Connected via",
        "active_connection",
        ACTIVE_CONNECTION_LABELS,
        NO_ACTIVE_CONNECTION_LABEL,
        "mdi:access-point",
        True,
    ),
    (
        "upstream_pairing_state",
        "USB status",
        "upstream_pairing_state",
        UPSTREAM_PAIRING_STATE_LABELS,
        UNKNOWN_PAIRING_LABEL,
        "mdi:usb-port",
        True,
    ),
)

TEXT_SENSORS = (
    (
        "downstream_interface",
        "Downstream interface",
        "mdi:ethernet",
        False,
        NO_INTERFACE_LABEL,
    ),
    (
        "public_ip",
        "Public IP",
        "mdi:ip-network-outline",
        True,
        NOT_CONNECTED_LABEL,
    ),
)

BINARY_SENSORS = (
    ("upstream_healthy", "Internet available", "connectivity", None, True),
    ("downstream_present", "Downstream interface present", None, "mdi:ethernet", False),
    ("rules_installed", "Gateway rules applied", "running", "mdi:firewall", False),
    ("dnsmasq_running", "DHCP server running", "running", "mdi:server-network", False),
)

REMOVED_COMPONENTS: dict[str, str] = {"enabled": "binary_sensor"}

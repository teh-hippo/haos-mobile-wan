from __future__ import annotations

from .const import DEFAULT_MOBILE_CONNECTION_OPTION, MOBILE_CONNECTION_OPTIONS

UPSTREAM_PAIRING_STATE_LABELS: dict[str, str] = {
    "not_applicable": "Not active",
    "not_ready": "Not ready",
    "waiting_for_device": "Waiting for device",
    "waiting_for_hotspot": "Waiting for Personal Hotspot",
    "waiting_for_carrier": "Waiting for USB tethering",
    "multiple_devices": "Multiple devices",
    "waiting_for_interface": "Waiting for interface",
    "waiting_for_trust": "Waiting for trust",
    "waiting_for_unlock": "Waiting for unlock",
    "pairing_failed": "Pairing failed",
    "daemon_failed": "Pairing helper failed",
    "profile_failed": "Profile failed",
    "waiting_for_profile": "Waiting for profile",
    "profile_conflict": "Profile conflict",
    "invalid_lease": "Invalid lease",
    "paired": "Paired",
    "ready": "Ready",
}

GATEWAY_STATE_LABELS: dict[str, str] = {
    "waiting": "Waiting",
    "connecting": "Connecting",
    "connected": "Connected",
    "error": "Error",
}

GATEWAY_WAITING_LABELS: dict[str, str] = {
    "iphone_usb": "Waiting for iPhone",
    "wifi_hotspot": "Waiting for hotspot",
    "iphone_usb_wifi_fallback": "Waiting",
    "generic_usb": "Waiting for USB device",
    "generic_usb_wifi_fallback": "Waiting",
}

HEALTH_LABELS: dict[str, str] = {
    "healthy": "Healthy",
    "attention": "Attention needed",
}

ACTIVE_CONNECTION_LABELS: dict[str, str] = {
    "wifi_hotspot": "Wi-Fi hotspot",
    "iphone_usb": "USB (iPhone)",
    "generic_usb": "USB (generic)",
}

MOBILE_CONNECTION_INTERNAL_LABELS: dict[str, str] = {
    internal: label for label, internal in MOBILE_CONNECTION_OPTIONS.items()
}
MOBILE_CONNECTION_DEFAULT_LABEL = DEFAULT_MOBILE_CONNECTION_OPTION

NO_ACTIVE_CONNECTION_LABEL = "Not connected"
NOT_CONNECTED_LABEL = "Not connected"
NO_INTERFACE_LABEL = "Not present"
UNKNOWN_PAIRING_LABEL = UPSTREAM_PAIRING_STATE_LABELS["not_applicable"]


def enum_options(labels: dict[str, str], default: str) -> list[str]:
    options = list(dict.fromkeys(labels.values()))
    if default not in options:
        options.append(default)
    return options


def enum_value_template(field: str, labels: dict[str, str], default: str) -> str:
    return (
        "{{ "
        + _jinja_mapping(labels)
        + ".get(value_json."
        + field
        + ", "
        + _quote(default)
        + ") }}"
    )


def fallback_value_template(field: str, fallback: str) -> str:
    expr = "value_json." + field
    return "{{ " + expr + " if " + expr + " else " + _quote(fallback) + " }}"


def gateway_state_value_template() -> str:
    return (
        "{{ "
        + _jinja_mapping(GATEWAY_WAITING_LABELS)
        + ".get(value_json.mobile_connection, 'Waiting')"
        + " if value_json.state == 'waiting' else "
        + _jinja_mapping(GATEWAY_STATE_LABELS)
        + ".get(value_json.state, 'Error') }}"
    )


def _jinja_mapping(labels: dict[str, str]) -> str:
    body = ", ".join(f"{_quote(key)}: {_quote(value)}" for key, value in labels.items())
    return "{" + body + "}"


def _quote(value: str) -> str:
    return "'" + value + "'"

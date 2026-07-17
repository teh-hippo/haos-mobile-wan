from __future__ import annotations

from .const import DEFAULT_MOBILE_CONNECTION_OPTION, MOBILE_CONNECTION_OPTIONS

UPSTREAM_PAIRING_STATE_LABELS: dict[str, str] = {
    "not_applicable": "Not applicable",
    "not_ready": "Not ready",
    "waiting_for_device": "Waiting for device",
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
}

GATEWAY_STATE_LABELS: dict[str, str] = {
    "disabled": "Disabled",
    "offline": "Offline",
    "connecting": "Connecting",
    "connected": "Connected",
}

ACTIVE_CONNECTION_LABELS: dict[str, str] = {
    "wifi_hotspot": "Wi-Fi hotspot",
    "iphone_usb": "USB (iPhone)",
}

MOBILE_CONNECTION_INTERNAL_LABELS: dict[str, str] = {
    internal: label for label, internal in MOBILE_CONNECTION_OPTIONS.items()
}
MOBILE_CONNECTION_DEFAULT_LABEL = DEFAULT_MOBILE_CONNECTION_OPTION

NO_ACTIVE_CONNECTION_LABEL = "Not connected"
OFFLINE_LABEL = "Offline"
NO_INTERFACE_LABEL = "None"
NO_ERROR_LABEL = "None"
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


def _jinja_mapping(labels: dict[str, str]) -> str:
    body = ", ".join(f"{_quote(key)}: {_quote(value)}" for key, value in labels.items())
    return "{" + body + "}"


def _quote(value: str) -> str:
    return "'" + value + "'"

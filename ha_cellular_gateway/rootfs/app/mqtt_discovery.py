from __future__ import annotations

from typing import Any

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
    "healthy": "OK",
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

OBJECT_ID = "haos_mobile_wan"
DEVICE_NAME = "HAOS Mobile WAN"
MANUFACTURER = "teh-hippo"
MODEL = "HAOS Mobile WAN"
ORIGIN_NAME = "HAOS Mobile WAN"
SUPPORT_URL = "https://github.com/teh-hippo/haos-mobile-wan"

DISCOVERY_TOPIC = f"homeassistant/device/{OBJECT_ID}/config"
AVAILABILITY_TOPIC = f"{OBJECT_ID}/availability"
STATE_TOPIC = f"{OBJECT_ID}/state"
STATUS_TOPIC = "homeassistant/status"

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"
PAYLOAD_BIRTH = "online"

STATE_FIELDS = (
    "state",
    "mobile_connection",
    "active_connection",
    "upstream_pairing_state",
    "downstream_interface",
    "public_ip",
    "health",
    "health_issues",
    "networkmanager",
    "upstream_carrier",
    "auto_disable_at",
    "upstream_healthy",
    "fallback_active",
    "fallback_reason",
    "downstream_present",
    "rules_installed",
    "dnsmasq_running",
)


def _uid(key: str) -> str:
    return f"{OBJECT_ID}_{key}"


def _bool_value(field: str) -> str:
    return "{{ 'ON' if value_json." + field + " else 'OFF' }}"


def _enum_options(labels: dict[str, str], default: str) -> list[str]:
    options = list(dict.fromkeys(labels.values()))
    if default not in options:
        options.append(default)
    return options


def _quote(value: str) -> str:
    return "'" + value + "'"


def _jinja_mapping(labels: dict[str, str]) -> str:
    body = ", ".join(f"{_quote(key)}: {_quote(value)}" for key, value in labels.items())
    return "{" + body + "}"


def _enum_value_template(
    field: str,
    labels: dict[str, str],
    default: str,
) -> str:
    return (
        "{{ "
        + _jinja_mapping(labels)
        + ".get(value_json."
        + field
        + ", "
        + _quote(default)
        + ") }}"
    )


def _fallback_value_template(field: str, fallback: str) -> str:
    expr = "value_json." + field
    return "{{ " + expr + " if " + expr + " else " + _quote(fallback) + " }}"


def _gateway_state_value_template() -> str:
    return (
        "{{ "
        + _jinja_mapping(GATEWAY_WAITING_LABELS)
        + ".get(value_json.mobile_connection, 'Waiting')"
        + " if value_json.state == 'waiting' else "
        + _jinja_mapping(GATEWAY_STATE_LABELS)
        + ".get(value_json.state, 'Error') }}"
    )


def _base(key: str, platform: str, name: str, enabled: bool) -> dict[str, Any]:
    component: dict[str, Any] = {
        "platform": platform,
        "unique_id": _uid(key),
        "name": name,
    }
    if not enabled:
        component["enabled_by_default"] = False
    return component


def _enum_sensor(spec: tuple[Any, ...]) -> dict[str, Any]:
    key, name, field, labels, default, icon, enabled = spec
    component = _base(key, "sensor", name, enabled)
    component["entity_category"] = "diagnostic"
    component["device_class"] = "enum"
    component["options"] = _enum_options(labels, default)
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _enum_value_template(field, labels, default)
    component["icon"] = icon
    return component


def _gateway_state() -> dict[str, Any]:
    component = _base("gateway_state", "sensor", "Gateway state", True)
    component["entity_category"] = "diagnostic"
    component["device_class"] = "enum"
    component["options"] = list(
        dict.fromkeys(
            [
                *GATEWAY_WAITING_LABELS.values(),
                *GATEWAY_STATE_LABELS.values(),
            ]
        )
    )
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _gateway_state_value_template()
    component["json_attributes_topic"] = STATE_TOPIC
    component["json_attributes_template"] = (
        "{{ {'auto_disable_at': value_json.auto_disable_at, "
        "'fallback_active': value_json.fallback_active, "
        "'fallback_reason': value_json.fallback_reason, "
        "'upstream_carrier': value_json.upstream_carrier} | tojson }}"
    )
    component["icon"] = "mdi:lan-connect"
    return component


def _health() -> dict[str, Any]:
    component = _base("health", "sensor", "Health", True)
    component["entity_category"] = "diagnostic"
    component["device_class"] = "enum"
    component["options"] = _enum_options(HEALTH_LABELS, "Attention needed")
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _enum_value_template(
        "health",
        HEALTH_LABELS,
        "Attention needed",
    )
    component["json_attributes_topic"] = STATE_TOPIC
    component["json_attributes_template"] = (
        "{{ {'issues': value_json.health_issues, 'networkmanager': value_json.networkmanager} | tojson }}"
    )
    component["icon"] = "mdi:heart-pulse"
    return component


def _text_sensor(spec: tuple[Any, ...]) -> dict[str, Any]:
    key, name, icon, enabled, fallback = spec
    component = _base(key, "sensor", name, enabled)
    component["entity_category"] = "diagnostic"
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _fallback_value_template(key, fallback)
    component["icon"] = icon
    return component


def _binary_sensor(spec: tuple[Any, ...]) -> dict[str, Any]:
    key, name, device_class, icon, enabled = spec
    component = _base(key, "binary_sensor", name, enabled)
    component["entity_category"] = "diagnostic"
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _bool_value(key)
    if device_class:
        component["device_class"] = device_class
    if icon:
        component["icon"] = icon
    return component


def build_components() -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {
        "gateway_state": _gateway_state(),
        "health": _health(),
    }
    for enum_spec in ENUM_SENSORS:
        components[enum_spec[0]] = _enum_sensor(enum_spec)
    for text_spec in TEXT_SENSORS:
        components[text_spec[0]] = _text_sensor(text_spec)
    for binary_spec in BINARY_SENSORS:
        components[binary_spec[0]] = _binary_sensor(binary_spec)
    for key, platform in REMOVED_COMPONENTS.items():
        components[key] = {"platform": platform}
    return components


def build_discovery_payload() -> dict[str, Any]:
    return {
        "dev": {
            "identifiers": [OBJECT_ID],
            "name": DEVICE_NAME,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        },
        "o": {"name": ORIGIN_NAME, "support_url": SUPPORT_URL},
        "availability": [
            {
                "topic": AVAILABILITY_TOPIC,
                "payload_available": PAYLOAD_ONLINE,
                "payload_not_available": PAYLOAD_OFFLINE,
            }
        ],
        "cmps": build_components(),
    }


def build_state_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {field: status.get(field) for field in STATE_FIELDS}

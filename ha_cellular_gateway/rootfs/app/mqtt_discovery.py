from __future__ import annotations

from typing import Any

from .mqtt_labels import (
    ACTIVE_CONNECTION_LABELS,
    GATEWAY_STATE_LABELS,
    HEALTH_LABELS,
    MOBILE_CONNECTION_DEFAULT_LABEL,
    MOBILE_CONNECTION_INTERNAL_LABELS,
    NO_ACTIVE_CONNECTION_LABEL,
    NO_INTERFACE_LABEL,
    NOT_CONNECTED_LABEL,
    UNKNOWN_PAIRING_LABEL,
    UPSTREAM_PAIRING_STATE_LABELS,
    enum_options,
    enum_value_template,
    fallback_value_template,
    gateway_state_value_template,
)

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
    "enabled",
    "downstream_present",
    "rules_installed",
    "dnsmasq_running",
)

_ENUM_SENSORS = (
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
        "iPhone USB pairing",
        "upstream_pairing_state",
        UPSTREAM_PAIRING_STATE_LABELS,
        UNKNOWN_PAIRING_LABEL,
        "mdi:usb-port",
        True,
    ),
)

_TEXT_SENSORS = (
    ("downstream_interface", "Downstream interface", "mdi:ethernet", False,
     NO_INTERFACE_LABEL),
    (
        "public_ip",
        "Public IP",
        "mdi:ip-network-outline",
        True,
        NOT_CONNECTED_LABEL,
    ),
)

_BINARY_SENSORS = (
    ("upstream_healthy", "Internet available", "connectivity", None, True),
    ("enabled", "Gateway enabled", None, "mdi:wan", True),
    ("downstream_present", "Downstream interface present", None, "mdi:ethernet", False),
    ("rules_installed", "Gateway rules applied", "running", "mdi:firewall", False),
    ("dnsmasq_running", "DHCP server running", "running", "mdi:server-network", False),
)


def _uid(key: str) -> str:
    return f"{OBJECT_ID}_{key}"


def _bool_value(field: str) -> str:
    return "{{ 'ON' if value_json." + field + " else 'OFF' }}"


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
    component["options"] = enum_options(labels, default)
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = enum_value_template(field, labels, default)
    component["icon"] = icon
    return component


def _gateway_state() -> dict[str, Any]:
    component = _base("gateway_state", "sensor", "Gateway state", True)
    component["entity_category"] = "diagnostic"
    component["device_class"] = "enum"
    component["options"] = [
        "Disabled",
        "Waiting for iPhone",
        "Waiting for hotspot",
        "Waiting",
        "Connecting",
        "Connected",
        "Error",
    ]
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = gateway_state_value_template()
    component["json_attributes_topic"] = STATE_TOPIC
    component["json_attributes_template"] = (
        "{{ {'auto_disable_at': value_json.auto_disable_at, "
        "'upstream_carrier': value_json.upstream_carrier} | tojson }}"
    )
    component["icon"] = "mdi:lan-connect"
    return component


def _health() -> dict[str, Any]:
    component = _base("health", "sensor", "Health", True)
    component["entity_category"] = "diagnostic"
    component["device_class"] = "enum"
    component["options"] = enum_options(HEALTH_LABELS, "Attention needed")
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = enum_value_template(
        "health",
        HEALTH_LABELS,
        "Attention needed",
    )
    component["json_attributes_topic"] = STATE_TOPIC
    component["json_attributes_template"] = (
        "{{ {'issues': value_json.health_issues, "
        "'networkmanager': value_json.networkmanager} | tojson }}"
    )
    component["icon"] = "mdi:heart-pulse"
    return component


def _text_sensor(spec: tuple[Any, ...]) -> dict[str, Any]:
    key, name, icon, enabled, fallback = spec
    component = _base(key, "sensor", name, enabled)
    component["entity_category"] = "diagnostic"
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = fallback_value_template(key, fallback)
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
    for spec in _ENUM_SENSORS:
        components[spec[0]] = _enum_sensor(spec)
    for spec in _TEXT_SENSORS:
        components[spec[0]] = _text_sensor(spec)
    for spec in _BINARY_SENSORS:
        components[spec[0]] = _binary_sensor(spec)
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

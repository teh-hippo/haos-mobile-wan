from __future__ import annotations

from typing import Any

from .mqtt_labels import (
    ACTIVE_CONNECTION_LABELS,
    GATEWAY_STATE_LABELS,
    MOBILE_CONNECTION_DEFAULT_LABEL,
    MOBILE_CONNECTION_INTERNAL_LABELS,
    NO_ACTIVE_CONNECTION_LABEL,
    NO_ERROR_LABEL,
    NO_INTERFACE_LABEL,
    OFFLINE_LABEL,
    UNKNOWN_PAIRING_LABEL,
    UPSTREAM_PAIRING_STATE_LABELS,
    enum_options,
    enum_value_template,
    fallback_value_template,
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
    "error",
    "upstream_healthy",
    "enabled",
    "downstream_present",
    "rules_installed",
    "dnsmasq_running",
    "safety_errors",
)

_ENUM_SENSORS = (
    (
        "gateway_state",
        "Gateway state",
        "state",
        GATEWAY_STATE_LABELS,
        OFFLINE_LABEL,
        "mdi:lan-connect",
        True,
    ),
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
        False,
    ),
)

_TEXT_SENSORS = (
    ("downstream_interface", "Downstream interface", "mdi:ethernet", False,
     NO_INTERFACE_LABEL),
    ("public_ip", "Public IP", "mdi:ip-network-outline", False, OFFLINE_LABEL),
    ("error", "Last error", "mdi:alert-circle-outline", True, NO_ERROR_LABEL),
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


def _safety_checks() -> dict[str, Any]:
    component = _base("safety_checks", "binary_sensor", "Safety checks", True)
    component["entity_category"] = "diagnostic"
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = "{{ 'OFF' if value_json.safety_errors else 'ON' }}"
    component["json_attributes_topic"] = STATE_TOPIC
    component["json_attributes_template"] = (
        "{{ {'errors': value_json.safety_errors} | tojson }}"
    )
    component["icon"] = "mdi:shield-check"
    return component


def build_components() -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for spec in _ENUM_SENSORS:
        components[spec[0]] = _enum_sensor(spec)
    for spec in _TEXT_SENSORS:
        components[spec[0]] = _text_sensor(spec)
    for spec in _BINARY_SENSORS:
        components[spec[0]] = _binary_sensor(spec)
    components["safety_checks"] = _safety_checks()
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

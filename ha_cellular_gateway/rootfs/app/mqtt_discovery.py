from __future__ import annotations

from typing import Any

from .mqtt_labels import (
    ACTIVE_CONNECTION_LABELS,
    GATEWAY_STATE_LABELS,
    MOBILE_CONNECTION_DEFAULT_LABEL,
    MOBILE_CONNECTION_INTERNAL_LABELS,
    MOBILE_CONNECTION_LABEL_OPTIONS,
    NO_ACTIVE_CONNECTION_LABEL,
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
ENABLED_COMMAND_TOPIC = f"{OBJECT_ID}/enabled/set"
RECONCILE_COMMAND_TOPIC = f"{OBJECT_ID}/reconcile/press"
MOBILE_CONNECTION_COMMAND_TOPIC = f"{OBJECT_ID}/mobile_connection/set"
STATUS_TOPIC = "homeassistant/status"

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"
PAYLOAD_ON = "ON"
PAYLOAD_OFF = "OFF"
PAYLOAD_PRESS = "PRESS"
PAYLOAD_BIRTH = "online"

STATE_FIELDS = (
    "state",
    "mobile_connection",
    "active_connection",
    "upstream_pairing_state",
    "downstream_interface",
    "public_ip",
    "last_error",
    "upstream_healthy",
    "downstream_present",
    "rules_installed",
    "dnsmasq_running",
    "enabled",
    "safety_errors",
)

_ENUM_SENSORS = (
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
    (
        "gateway_state",
        "Gateway state",
        "state",
        GATEWAY_STATE_LABELS,
        OFFLINE_LABEL,
        "mdi:lan-connect",
        True,
    ),
)

_TEXT_SENSORS = (
    ("downstream_interface", "Downstream interface", "mdi:ethernet", False,
     NO_INTERFACE_LABEL),
    ("public_ip", "Public IP", "mdi:ip-network-outline", False, OFFLINE_LABEL),
    ("last_error", "Last error", "mdi:alert-circle-outline", False, None),
)

_BINARY_SENSORS = (
    ("upstream_healthy", "Internet available", "connectivity", None, True),
    ("downstream_present", "Downstream interface present", None, "mdi:ethernet", False),
    ("rules_installed", "Gateway rules applied", "running", "mdi:firewall", False),
    ("dnsmasq_running", "DHCP server running", "running", "mdi:server-network", False),
)


def _uid(key: str) -> str:
    return f"{OBJECT_ID}_{key}"


def _value(field: str) -> str:
    return "{{ value_json." + field + " }}"


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
    component["value_template"] = (
        fallback_value_template(key, fallback) if fallback else _value(key)
    )
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


def _enabled_switch() -> dict[str, Any]:
    component = _base("enabled", "switch", "Enabled", True)
    component["entity_category"] = "config"
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _bool_value("enabled")
    component["command_topic"] = ENABLED_COMMAND_TOPIC
    component["icon"] = "mdi:wan"
    return component


def _mobile_connection_select() -> dict[str, Any]:
    component = _base("mobile_connection", "select", "Connection method", True)
    component["entity_category"] = "config"
    component["state_topic"] = STATE_TOPIC
    component["command_topic"] = MOBILE_CONNECTION_COMMAND_TOPIC
    component["options"] = list(MOBILE_CONNECTION_LABEL_OPTIONS)
    component["value_template"] = enum_value_template(
        "mobile_connection",
        MOBILE_CONNECTION_INTERNAL_LABELS,
        MOBILE_CONNECTION_DEFAULT_LABEL,
    )
    component["icon"] = "mdi:connection"
    return component


def _reconcile_button() -> dict[str, Any]:
    component = _base("reconcile", "button", "Reapply gateway state", False)
    component["entity_category"] = "diagnostic"
    component["command_topic"] = RECONCILE_COMMAND_TOPIC
    component["icon"] = "mdi:sync"
    return component


def build_components() -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for spec in _ENUM_SENSORS:
        components[spec[0]] = _enum_sensor(spec)
    for spec in _TEXT_SENSORS:
        components[spec[0]] = _text_sensor(spec)
    for spec in _BINARY_SENSORS:
        components[spec[0]] = _binary_sensor(spec)
    components["mobile_connection"] = _mobile_connection_select()
    components["safety_checks"] = _safety_checks()
    components["enabled"] = _enabled_switch()
    components["reconcile"] = _reconcile_button()
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

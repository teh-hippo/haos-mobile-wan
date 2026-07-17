from __future__ import annotations

from typing import Any

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
        "mobile_connection",
        "Mobile connection",
        "mobile_connection",
        ("wifi_hotspot", "iphone_usb", "iphone_usb_wifi_fallback"),
        "mdi:connection",
        False,
    ),
    (
        "active_connection",
        "Active connection",
        "active_connection",
        ("wifi_hotspot", "iphone_usb"),
        "mdi:access-point",
        True,
    ),
    (
        "upstream_pairing_state",
        "USB pairing",
        "upstream_pairing_state",
        (
            "not_applicable",
            "not_ready",
            "waiting_for_device",
            "multiple_devices",
            "waiting_for_interface",
            "waiting_for_trust",
            "waiting_for_unlock",
            "pairing_failed",
            "daemon_failed",
            "profile_failed",
            "waiting_for_profile",
            "profile_conflict",
            "invalid_lease",
            "paired",
        ),
        "mdi:usb-port",
        False,
    ),
    (
        "gateway_state",
        "Gateway state",
        "state",
        ("disabled", "offline", "connecting", "connected"),
        "mdi:lan-connect",
        True,
    ),
)

_TEXT_SENSORS = (
    ("downstream_interface", "Downstream interface", "mdi:ethernet", False),
    ("public_ip", "Public IP", "mdi:ip-network-outline", False),
    ("last_error", "Last error", "mdi:alert-circle-outline", False),
)

_BINARY_SENSORS = (
    ("upstream_healthy", "Upstream healthy", "connectivity", None, True),
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
    key, name, field, options, icon, enabled = spec
    component = _base(key, "sensor", name, enabled)
    component["entity_category"] = "diagnostic"
    component["device_class"] = "enum"
    component["options"] = list(options)
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _value(field)
    component["icon"] = icon
    return component


def _text_sensor(spec: tuple[Any, ...]) -> dict[str, Any]:
    key, name, icon, enabled = spec
    component = _base(key, "sensor", name, enabled)
    component["entity_category"] = "diagnostic"
    component["state_topic"] = STATE_TOPIC
    component["value_template"] = _value(key)
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

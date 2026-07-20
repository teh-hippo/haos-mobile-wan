"""Shared MQTT client/engine doubles and a canonical status snapshot.

Used by the publisher lifecycle and Supervisor service lookup suites, which
both need a fake `paho-mqtt` client and a stub `GatewayEngine`.
"""

from __future__ import annotations

from types import SimpleNamespace

STATUS = {
    "state": "connected",
    "mobile_connection": "iphone_usb_wifi_fallback",
    "active_connection": None,
    "upstream_pairing_state": "paired",
    "downstream_interface": "eth1",
    "public_ip": "203.0.113.10",
    "health": "healthy",
    "health_issues": [],
    "networkmanager": {
        "phase": "disabled",
        "owned_profiles": {},
        "profile_states": {
            "iphone_usb": "missing",
            "wifi_hotspot": "missing",
        },
        "legacy_wifi_profiles": 0,
    },
    "upstream_carrier": None,
    "auto_disable_at": None,
    "upstream_healthy": True,
    "downstream_present": True,
    "rules_installed": True,
    "dnsmasq_running": False,
    "ignored_extra_field": "drop-me",
}


class FakeClient:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.username: tuple[str | None, str | None] | None = None
        self.will: tuple[str, str, int, bool] | None = None
        self.tls = False
        self.connected_to: tuple[str, int] | None = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.subscriptions: list[str] = []
        self.published: list[tuple[str, str, int, bool]] = []
        self.on_connect = None
        self.on_message = None

    def username_pw_set(self, username, password):
        self.username = (username, password)

    def tls_set(self):
        self.tls = True

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def connect_async(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def trigger_connect(self, rc=0):
        self.on_connect(self, None, {}, rc)

    def trigger_message(self, topic, payload):
        message = SimpleNamespace(topic=topic, payload=payload)
        self.on_message(self, None, message)

    def last_payload(self, topic):
        for entry_topic, payload, _qos, _retain in reversed(self.published):
            if entry_topic == topic:
                return payload
        raise AssertionError(f"no payload published to {topic}")


class StubEngine:
    def __init__(self) -> None:
        self.config = SimpleNamespace(reconcile_seconds=5)

    def status(self):
        return dict(STATUS)

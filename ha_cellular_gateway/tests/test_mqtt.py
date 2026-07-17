from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from rootfs.app import mqtt_discovery
from rootfs.app.errors import GatewayError
from rootfs.app.mqtt_discovery import (
    AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    ENABLED_COMMAND_TOPIC,
    RECONCILE_COMMAND_TOPIC,
    STATE_TOPIC,
    STATUS_TOPIC,
    build_discovery_payload,
    build_state_payload,
)
from rootfs.app.mqtt_publisher import MqttPublisher
from rootfs.app.mqtt_service import MqttCredentials, read_mqtt_service

STATUS = {
    "state": "connected",
    "enabled": True,
    "mobile_connection": "iphone_usb_wifi_fallback",
    "active_connection": None,
    "upstream_pairing_state": "paired",
    "downstream_interface": "eth1",
    "public_ip": "203.0.113.10",
    "last_error": None,
    "upstream_healthy": True,
    "downstream_present": True,
    "rules_installed": True,
    "dnsmasq_running": False,
    "safety_errors": ["boom"],
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
        self.applied = False
        self.cleaned_preserve: bool | None = None
        self.reconciled = 0

    def status(self):
        return dict(STATUS)

    def apply(self):
        self.applied = True

    def cleanup(self, *, preserve_host_protection=False):
        self.cleaned_preserve = preserve_host_protection

    def reconcile(self):
        self.reconciled += 1


def make_publisher(engine=None):
    engine = engine or StubEngine()
    clients: list[FakeClient] = []

    def factory(client_id):
        client = FakeClient(client_id)
        clients.append(client)
        return client

    publisher = MqttPublisher(
        engine,
        credentials=MqttCredentials("broker", 1883, "user", "pass", False),
        client_factory=factory,
        interval=3600,
    )
    return publisher, engine, clients


class DiscoveryPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = build_discovery_payload()
        self.cmps = self.payload["cmps"]

    def test_device_and_origin(self) -> None:
        self.assertEqual(self.payload["dev"]["name"], "HAOS Mobile WAN")
        self.assertEqual(self.payload["dev"]["identifiers"], ["haos_mobile_wan"])
        self.assertEqual(self.payload["dev"]["manufacturer"], "teh-hippo")
        self.assertEqual(self.payload["o"]["name"], "HAOS Mobile WAN")

    def test_availability_matches_lwt_topic(self) -> None:
        availability = self.payload["availability"][0]
        self.assertEqual(availability["topic"], AVAILABILITY_TOPIC)
        self.assertEqual(availability["payload_available"], "online")
        self.assertEqual(availability["payload_not_available"], "offline")

    def test_every_entity_reproduced(self) -> None:
        expected = {
            "mobile_connection",
            "active_connection",
            "upstream_pairing_state",
            "downstream_interface",
            "public_ip",
            "last_error",
            "gateway_state",
            "upstream_healthy",
            "downstream_present",
            "rules_installed",
            "dnsmasq_running",
            "safety_checks",
            "enabled",
            "reconcile",
        }
        self.assertEqual(set(self.cmps), expected)

    def test_platforms_and_unique_ids(self) -> None:
        platforms = {key: comp["platform"] for key, comp in self.cmps.items()}
        self.assertEqual(platforms["gateway_state"], "sensor")
        self.assertEqual(platforms["upstream_healthy"], "binary_sensor")
        self.assertEqual(platforms["enabled"], "switch")
        self.assertEqual(platforms["reconcile"], "button")
        for key, comp in self.cmps.items():
            self.assertEqual(comp["unique_id"], f"haos_mobile_wan_{key}")

    def test_enum_options_and_device_class(self) -> None:
        gateway_state = self.cmps["gateway_state"]
        self.assertEqual(gateway_state["device_class"], "enum")
        self.assertEqual(
            gateway_state["options"],
            ["disabled", "offline", "connecting", "connected"],
        )
        self.assertEqual(gateway_state["value_template"], "{{ value_json.state }}")
        self.assertEqual(
            self.cmps["mobile_connection"]["options"],
            ["wifi_hotspot", "iphone_usb", "iphone_usb_wifi_fallback"],
        )
        self.assertEqual(len(self.cmps["upstream_pairing_state"]["options"]), 14)

    def test_binary_sensor_device_classes(self) -> None:
        self.assertEqual(
            self.cmps["upstream_healthy"]["device_class"], "connectivity"
        )
        self.assertEqual(self.cmps["rules_installed"]["device_class"], "running")
        self.assertEqual(self.cmps["dnsmasq_running"]["device_class"], "running")
        self.assertNotIn("device_class", self.cmps["downstream_present"])

    def test_entity_categories_and_enabled_default(self) -> None:
        self.assertEqual(self.cmps["enabled"]["entity_category"], "config")
        self.assertEqual(self.cmps["gateway_state"]["entity_category"], "diagnostic")
        self.assertEqual(self.cmps["mobile_connection"]["enabled_by_default"], False)
        self.assertNotIn("enabled_by_default", self.cmps["gateway_state"])
        self.assertEqual(self.cmps["reconcile"]["enabled_by_default"], False)

    def test_control_command_topics(self) -> None:
        self.assertEqual(
            self.cmps["enabled"]["command_topic"], ENABLED_COMMAND_TOPIC
        )
        self.assertEqual(
            self.cmps["reconcile"]["command_topic"], RECONCILE_COMMAND_TOPIC
        )
        self.assertNotIn("state_topic", self.cmps["reconcile"])

    def test_safety_checks_attributes(self) -> None:
        safety = self.cmps["safety_checks"]
        self.assertEqual(safety["json_attributes_topic"], STATE_TOPIC)
        self.assertIn("errors", safety["json_attributes_template"])
        self.assertEqual(
            safety["value_template"],
            "{{ 'OFF' if value_json.safety_errors else 'ON' }}",
        )

    def test_state_topic_shared_by_stateful_components(self) -> None:
        for key in ("gateway_state", "upstream_healthy", "enabled"):
            self.assertEqual(self.cmps[key]["state_topic"], STATE_TOPIC)


class StatePayloadTests(unittest.TestCase):
    def test_only_known_fields_are_published(self) -> None:
        payload = build_state_payload(dict(STATUS))
        self.assertEqual(set(payload), set(mqtt_discovery.STATE_FIELDS))
        self.assertIsNone(payload["active_connection"])
        self.assertEqual(payload["safety_errors"], ["boom"])
        self.assertNotIn("ignored_extra_field", payload)


class PublisherLifecycleTests(unittest.TestCase):
    def test_connect_sets_lwt_credentials_and_subscriptions(self) -> None:
        publisher, _engine, clients = make_publisher()
        self.assertTrue(publisher.start())
        client = clients[0]
        self.assertEqual(client.username, ("user", "pass"))
        self.assertFalse(client.tls)
        self.assertEqual(client.will, (AVAILABILITY_TOPIC, "offline", 1, True))
        self.assertEqual(client.connected_to, ("broker", 1883))
        self.assertTrue(client.loop_started)

        client.trigger_connect(rc=0)
        self.assertEqual(
            set(client.subscriptions),
            {ENABLED_COMMAND_TOPIC, RECONCILE_COMMAND_TOPIC, STATUS_TOPIC},
        )
        publisher.stop()

    def test_announce_publishes_discovery_availability_and_state(self) -> None:
        publisher, _engine, clients = make_publisher()
        publisher.start()
        client = clients[0]
        client.trigger_connect(rc=0)

        discovery = json.loads(client.last_payload(DISCOVERY_TOPIC))
        self.assertIn("cmps", discovery)
        self.assertEqual(client.last_payload(AVAILABILITY_TOPIC), "online")
        state = json.loads(client.last_payload(STATE_TOPIC))
        self.assertEqual(state, build_state_payload(dict(STATUS)))

        retained = {
            topic: retain for topic, _p, _q, retain in client.published
        }
        self.assertTrue(retained[DISCOVERY_TOPIC])
        self.assertTrue(retained[STATE_TOPIC])
        publisher.stop()

    def test_birth_message_re_announces(self) -> None:
        publisher, _engine, clients = make_publisher()
        publisher.start()
        client = clients[0]
        client.trigger_connect(rc=0)
        before = sum(t == DISCOVERY_TOPIC for t, *_ in client.published)
        client.trigger_message(STATUS_TOPIC, b"online")
        after = sum(t == DISCOVERY_TOPIC for t, *_ in client.published)
        self.assertEqual(after, before + 1)
        publisher.stop()

    def test_connection_refused_does_not_announce(self) -> None:
        publisher, _engine, clients = make_publisher()
        publisher.start()
        client = clients[0]
        client.trigger_connect(rc=5)
        self.assertEqual(client.published, [])
        self.assertEqual(client.subscriptions, [])
        publisher.stop()

    def test_stop_publishes_offline_and_disconnects(self) -> None:
        publisher, _engine, clients = make_publisher()
        publisher.start()
        client = clients[0]
        client.trigger_connect(rc=0)
        publisher.stop()
        self.assertEqual(client.published[-1], (AVAILABILITY_TOPIC, "offline", 1, True))
        self.assertTrue(client.loop_stopped)
        self.assertTrue(client.disconnected)


class PublisherCommandTests(unittest.TestCase):
    def _connected(self):
        publisher, engine, clients = make_publisher()
        publisher.start()
        client = clients[0]
        client.trigger_connect(rc=0)
        return publisher, engine, client

    def test_enable_command_applies_and_publishes_state(self) -> None:
        publisher, engine, client = self._connected()
        published_before = len(client.published)
        client.trigger_message(ENABLED_COMMAND_TOPIC, b"ON")
        self.assertTrue(engine.applied)
        self.assertGreater(len(client.published), published_before)
        self.assertEqual(client.published[-1][0], STATE_TOPIC)
        publisher.stop()

    def test_disable_command_cleans_up_preserving_host(self) -> None:
        publisher, engine, client = self._connected()
        client.trigger_message(ENABLED_COMMAND_TOPIC, b"OFF")
        self.assertIs(engine.cleaned_preserve, True)
        publisher.stop()

    def test_unknown_enable_command_is_ignored(self) -> None:
        publisher, engine, client = self._connected()
        client.trigger_message(ENABLED_COMMAND_TOPIC, b"maybe")
        self.assertFalse(engine.applied)
        self.assertIsNone(engine.cleaned_preserve)
        publisher.stop()

    def test_button_command_reconciles(self) -> None:
        publisher, engine, client = self._connected()
        client.trigger_message(RECONCILE_COMMAND_TOPIC, b"PRESS")
        self.assertEqual(engine.reconciled, 1)
        publisher.stop()

    def test_button_ignores_other_payloads(self) -> None:
        publisher, engine, client = self._connected()
        client.trigger_message(RECONCILE_COMMAND_TOPIC, b"nope")
        self.assertEqual(engine.reconciled, 0)
        publisher.stop()

    def test_command_failure_is_swallowed(self) -> None:
        publisher, engine, client = self._connected()
        engine.apply = mock.Mock(side_effect=GatewayError("nope"))
        client.trigger_message(ENABLED_COMMAND_TOPIC, b"ON")
        self.assertEqual(client.published[-1][0], STATE_TOPIC)
        publisher.stop()


class GracefulDegradationTests(unittest.TestCase):
    def test_start_without_credentials_is_noop(self) -> None:
        engine = StubEngine()
        factory = mock.Mock()
        with mock.patch.dict("os.environ", {}, clear=True):
            publisher = MqttPublisher(engine, client_factory=factory, interval=3600)
            self.assertFalse(publisher.start())
        factory.assert_not_called()
        publisher.publish_state()
        publisher.stop()

    def test_read_mqtt_service_missing_token(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(read_mqtt_service())

    def test_read_mqtt_service_handles_url_error(self) -> None:
        def boom(*_args, **_kwargs):
            raise OSError("broker down")

        self.assertIsNone(read_mqtt_service(token="t", urlopen=boom))

    def test_read_mqtt_service_parses_payload(self) -> None:
        body = json.dumps(
            {
                "result": "ok",
                "data": {
                    "host": "core-mosquitto",
                    "port": 1883,
                    "ssl": False,
                    "username": "addons",
                    "password": "secret",
                },
            }
        ).encode()

        def opener(*_args, **_kwargs):
            return SimpleNamespace(read=lambda: body)

        credentials = read_mqtt_service(token="t", urlopen=opener)
        self.assertEqual(credentials.host, "core-mosquitto")
        self.assertEqual(credentials.port, 1883)
        self.assertEqual(credentials.username, "addons")
        self.assertEqual(credentials.password, "secret")
        self.assertFalse(credentials.ssl)

    def test_read_mqtt_service_rejects_missing_host(self) -> None:
        def opener(*_args, **_kwargs):
            return SimpleNamespace(read=lambda: b'{"data": {"port": 1883}}')

        self.assertIsNone(read_mqtt_service(token="t", urlopen=opener))


if __name__ == "__main__":
    unittest.main()

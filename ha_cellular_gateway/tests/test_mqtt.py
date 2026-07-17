from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from rootfs.app import mqtt_discovery
from rootfs.app.mqtt_discovery import (
    AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    STATE_TOPIC,
    STATUS_TOPIC,
    build_discovery_payload,
    build_state_payload,
)
from rootfs.app.mqtt_publisher import MqttPublisher
from rootfs.app.mqtt_service import MqttCredentials, read_mqtt_service

try:
    from jinja2 import Environment

    _JINJA: Environment | None = Environment()
except ImportError:
    _JINJA = None

_HAS_JINJA = _JINJA is not None

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.template import Template
except ImportError:
    HomeAssistant = None
    Template = None

_HAS_HOME_ASSISTANT = HomeAssistant is not None and Template is not None


def _render(template: str, value_json: dict) -> str:
    assert _JINJA is not None
    return _JINJA.from_string(template).render(value_json=value_json)


STATUS = {
    "state": "connected",
    "enabled": True,
    "mobile_connection": "iphone_usb_wifi_fallback",
    "active_connection": None,
    "upstream_pairing_state": "paired",
    "downstream_interface": "eth1",
    "public_ip": "203.0.113.10",
    "error": None,
    "upstream_healthy": True,
    "downstream_present": True,
    "rules_installed": True,
    "dnsmasq_running": False,
    "safety_errors": ["boom"],
    "ignored_extra_field": "drop-me",
}

EXPECTED_COMPONENTS = {
    "gateway_state",
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
    "safety_checks",
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
        self.assertEqual(set(self.cmps), EXPECTED_COMPONENTS)

    def test_components_are_status_only(self) -> None:
        for key, comp in self.cmps.items():
            self.assertIn(comp["platform"], {"sensor", "binary_sensor"}, key)
            self.assertNotIn("command_topic", comp, key)

    def test_platforms_and_unique_ids(self) -> None:
        platforms = {key: comp["platform"] for key, comp in self.cmps.items()}
        self.assertEqual(platforms["gateway_state"], "sensor")
        self.assertEqual(platforms["mobile_connection"], "sensor")
        self.assertEqual(platforms["active_connection"], "sensor")
        self.assertEqual(platforms["upstream_healthy"], "binary_sensor")
        self.assertEqual(platforms["enabled"], "binary_sensor")
        for key, comp in self.cmps.items():
            self.assertEqual(comp["unique_id"], f"haos_mobile_wan_{key}")

    def test_enum_options_and_device_class(self) -> None:
        gateway_state = self.cmps["gateway_state"]
        self.assertEqual(gateway_state["device_class"], "enum")
        self.assertEqual(
            gateway_state["options"],
            ["Disabled", "Offline", "Connecting", "Connected"],
        )
        self.assertEqual(
            self.cmps["active_connection"]["options"],
            ["Wi-Fi hotspot", "USB (iPhone)", "Not connected"],
        )
        self.assertEqual(
            self.cmps["mobile_connection"]["options"],
            ["Wi-Fi hotspot", "USB (iPhone)", "USB (iPhone), Wi-Fi fallback"],
        )
        pairing = self.cmps["upstream_pairing_state"]
        self.assertEqual(len(pairing["options"]), 14)
        self.assertIn("Waiting for device", pairing["options"])
        self.assertNotIn("waiting_for_device", pairing["options"])

    def test_binary_sensor_device_classes(self) -> None:
        self.assertEqual(
            self.cmps["upstream_healthy"]["device_class"], "connectivity"
        )
        self.assertEqual(self.cmps["rules_installed"]["device_class"], "running")
        self.assertEqual(self.cmps["dnsmasq_running"]["device_class"], "running")
        self.assertNotIn("device_class", self.cmps["downstream_present"])
        self.assertNotIn("device_class", self.cmps["enabled"])

    def test_entity_categories_and_enabled_default(self) -> None:
        self.assertEqual(self.cmps["gateway_state"]["entity_category"], "diagnostic")
        self.assertEqual(self.cmps["enabled"]["entity_category"], "diagnostic")
        self.assertNotIn("enabled_by_default", self.cmps["gateway_state"])
        self.assertNotIn("enabled_by_default", self.cmps["mobile_connection"])
        self.assertNotIn("enabled_by_default", self.cmps["enabled"])
        self.assertNotIn("enabled_by_default", self.cmps["error"])
        self.assertEqual(
            self.cmps["upstream_pairing_state"]["enabled_by_default"], False
        )
        self.assertEqual(self.cmps["public_ip"]["enabled_by_default"], False)

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
        self.assertNotIn("last_error", payload)


class FriendlyLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cmps = build_discovery_payload()["cmps"]

    def test_relabelled_names(self) -> None:
        self.assertEqual(self.cmps["upstream_healthy"]["name"], "Internet available")
        self.assertEqual(
            self.cmps["upstream_healthy"]["device_class"], "connectivity"
        )
        self.assertEqual(self.cmps["active_connection"]["name"], "Connected via")
        self.assertEqual(self.cmps["gateway_state"]["name"], "Gateway state")
        self.assertEqual(self.cmps["mobile_connection"]["name"], "Connection method")
        self.assertEqual(self.cmps["enabled"]["name"], "Gateway enabled")
        self.assertEqual(self.cmps["error"]["name"], "Last error")

    def test_pairing_template_embeds_friendly_mapping(self) -> None:
        template = self.cmps["upstream_pairing_state"]["value_template"]
        self.assertIn("'waiting_for_device': 'Waiting for device'", template)
        self.assertIn("'daemon_failed': 'Pairing helper failed'", template)
        self.assertIn(
            ".get(value_json.upstream_pairing_state, 'Not applicable')", template
        )

    def test_mobile_connection_template_embeds_internal_to_label(self) -> None:
        template = self.cmps["mobile_connection"]["value_template"]
        self.assertIn(
            "'iphone_usb_wifi_fallback': 'USB (iPhone), Wi-Fi fallback'", template
        )
        self.assertIn(".get(value_json.mobile_connection,", template)

    def test_public_ip_offline_fallback(self) -> None:
        self.assertEqual(
            self.cmps["public_ip"]["value_template"],
            "{{ value_json.public_ip if value_json.public_ip else 'Offline' }}",
        )

    def test_downstream_interface_not_present_fallback(self) -> None:
        self.assertEqual(
            self.cmps["downstream_interface"]["value_template"],
            "{{ value_json.downstream_interface"
            " if value_json.downstream_interface else 'Not present' }}",
        )

    def test_error_reads_error_field_with_no_error_fallback(self) -> None:
        self.assertEqual(
            self.cmps["error"]["value_template"],
            "{{ value_json.error if value_json.error else 'No error' }}",
        )
        self.assertIn("error", mqtt_discovery.STATE_FIELDS)

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_enum_templates_render_friendly_values(self) -> None:
        pairing = self.cmps["upstream_pairing_state"]["value_template"]
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": "waiting_for_device"}),
            "Waiting for device",
        )
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": "daemon_failed"}),
            "Pairing helper failed",
        )
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": None}), "Not applicable"
        )
        gateway = self.cmps["gateway_state"]["value_template"]
        self.assertEqual(_render(gateway, {"state": "connected"}), "Connected")
        self.assertEqual(_render(gateway, {"state": None}), "Offline")

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_mobile_connection_renders_internal_to_label(self) -> None:
        template = self.cmps["mobile_connection"]["value_template"]
        self.assertEqual(
            _render(template, {"mobile_connection": "iphone_usb_wifi_fallback"}),
            "USB (iPhone), Wi-Fi fallback",
        )
        self.assertEqual(
            _render(template, {"mobile_connection": "wifi_hotspot"}), "Wi-Fi hotspot"
        )
        self.assertEqual(
            _render(template, build_state_payload(dict(STATUS))),
            "USB (iPhone), Wi-Fi fallback",
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_active_connection_null_renders_not_connected(self) -> None:
        template = self.cmps["active_connection"]["value_template"]
        self.assertEqual(
            _render(template, {"active_connection": "wifi_hotspot"}), "Wi-Fi hotspot"
        )
        self.assertEqual(
            _render(template, {"active_connection": "iphone_usb"}), "USB (iPhone)"
        )
        self.assertEqual(
            _render(template, {"active_connection": None}), "Not connected"
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_text_fallbacks_render_for_null(self) -> None:
        public_ip = self.cmps["public_ip"]["value_template"]
        self.assertEqual(_render(public_ip, {"public_ip": None}), "Offline")
        self.assertEqual(_render(public_ip, {"public_ip": ""}), "Offline")
        self.assertEqual(
            _render(public_ip, {"public_ip": "203.0.113.10"}), "203.0.113.10"
        )
        interface = self.cmps["downstream_interface"]["value_template"]
        self.assertEqual(
            _render(interface, {"downstream_interface": None}), "Not present"
        )
        self.assertEqual(_render(interface, {"downstream_interface": "eth1"}), "eth1")
        error = self.cmps["error"]["value_template"]
        self.assertEqual(_render(error, {"error": None}), "No error")
        self.assertEqual(
            _render(error, {"error": "The upstream interface is unavailable"}),
            "The upstream interface is unavailable",
        )

    @unittest.skipUnless(
        _HAS_HOME_ASSISTANT,
        "Home Assistant is not installed",
    )
    def test_text_fallbacks_remain_text_in_home_assistant(self) -> None:
        assert HomeAssistant is not None
        assert Template is not None

        async def render() -> tuple[object, object]:
            hass = HomeAssistant("/tmp")
            interface = Template(
                self.cmps["downstream_interface"]["value_template"], hass
            ).async_render(
                {"value_json": {"downstream_interface": None}},
                parse_result=True,
            )
            error = Template(
                self.cmps["error"]["value_template"], hass
            ).async_render(
                {"value_json": {"error": None}},
                parse_result=True,
            )
            return interface, error

        self.assertEqual(asyncio.run(render()), ("Not present", "No error"))

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_enabled_binary_sensor_renders_on_off(self) -> None:
        template = self.cmps["enabled"]["value_template"]
        self.assertEqual(_render(template, {"enabled": True}), "ON")
        self.assertEqual(_render(template, {"enabled": False}), "OFF")


class PublisherLifecycleTests(unittest.TestCase):
    def test_connect_sets_lwt_credentials_and_subscribes_to_status(self) -> None:
        publisher, _engine, clients = make_publisher()
        self.assertTrue(publisher.start())
        client = clients[0]
        self.assertEqual(client.username, ("user", "pass"))
        self.assertFalse(client.tls)
        self.assertEqual(client.will, (AVAILABILITY_TOPIC, "offline", 1, True))
        self.assertEqual(client.connected_to, ("broker", 1883))
        self.assertTrue(client.loop_started)

        client.trigger_connect(rc=0)
        self.assertEqual(client.subscriptions, [STATUS_TOPIC])
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

    def test_non_birth_status_payload_is_ignored(self) -> None:
        publisher, _engine, clients = make_publisher()
        publisher.start()
        client = clients[0]
        client.trigger_connect(rc=0)
        before = len(client.published)
        client.trigger_message(STATUS_TOPIC, b"offline")
        self.assertEqual(len(client.published), before)
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

        captured = {}

        def opener(request, *_args, **_kwargs):
            captured["auth"] = request.get_header("Authorization")
            return SimpleNamespace(read=lambda: body)

        credentials = read_mqtt_service(token="t", urlopen=opener)
        self.assertEqual(captured["auth"], "Bearer t")
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

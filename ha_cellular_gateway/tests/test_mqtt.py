from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rootfs.app import mqtt_discovery
from rootfs.app.addon_options import set_mobile_connection
from rootfs.app.errors import GatewayError
from rootfs.app.mqtt_discovery import (
    AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    ENABLED_COMMAND_TOPIC,
    MOBILE_CONNECTION_COMMAND_TOPIC,
    RECONCILE_COMMAND_TOPIC,
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
        self.assertEqual(platforms["mobile_connection"], "select")
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
        pairing = self.cmps["upstream_pairing_state"]
        self.assertEqual(len(pairing["options"]), 14)
        self.assertIn("Waiting for device", pairing["options"])
        self.assertIn("Pairing helper failed", pairing["options"])
        self.assertNotIn("waiting_for_device", pairing["options"])

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
        self.assertEqual(self.cmps["mobile_connection"]["entity_category"], "config")
        self.assertNotIn("enabled_by_default", self.cmps["mobile_connection"])
        self.assertNotIn("enabled_by_default", self.cmps["gateway_state"])
        self.assertEqual(self.cmps["reconcile"]["enabled_by_default"], False)

    def test_control_command_topics(self) -> None:
        self.assertEqual(
            self.cmps["enabled"]["command_topic"], ENABLED_COMMAND_TOPIC
        )
        self.assertEqual(
            self.cmps["reconcile"]["command_topic"], RECONCILE_COMMAND_TOPIC
        )
        self.assertEqual(
            self.cmps["mobile_connection"]["command_topic"],
            MOBILE_CONNECTION_COMMAND_TOPIC,
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

    def test_pairing_template_embeds_friendly_mapping(self) -> None:
        template = self.cmps["upstream_pairing_state"]["value_template"]
        self.assertIn("'waiting_for_device': 'Waiting for device'", template)
        self.assertIn("'daemon_failed': 'Pairing helper failed'", template)
        self.assertIn(
            ".get(value_json.upstream_pairing_state, 'Not applicable')", template
        )

    def test_public_ip_offline_fallback(self) -> None:
        self.assertEqual(
            self.cmps["public_ip"]["value_template"],
            "{{ value_json.public_ip if value_json.public_ip else 'Offline' }}",
        )

    def test_downstream_interface_none_fallback(self) -> None:
        self.assertEqual(
            self.cmps["downstream_interface"]["value_template"],
            "{{ value_json.downstream_interface"
            " if value_json.downstream_interface else 'None' }}",
        )

    def test_last_error_keeps_plain_template(self) -> None:
        self.assertEqual(
            self.cmps["last_error"]["value_template"],
            "{{ value_json.last_error }}",
        )

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
        self.assertEqual(_render(interface, {"downstream_interface": None}), "None")
        self.assertEqual(_render(interface, {"downstream_interface": "eth1"}), "eth1")


class MobileConnectionSelectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.select = build_discovery_payload()["cmps"]["mobile_connection"]

    def test_is_a_select_control(self) -> None:
        self.assertEqual(self.select["platform"], "select")
        self.assertEqual(
            self.select["unique_id"], "haos_mobile_wan_mobile_connection"
        )
        self.assertEqual(self.select["name"], "Connection method")
        self.assertEqual(self.select["entity_category"], "config")
        self.assertEqual(self.select["icon"], "mdi:connection")
        self.assertEqual(
            self.select["command_topic"], MOBILE_CONNECTION_COMMAND_TOPIC
        )

    def test_options_are_the_three_labels(self) -> None:
        self.assertEqual(
            self.select["options"],
            ["Wi-Fi hotspot", "USB (iPhone)", "USB (iPhone), Wi-Fi fallback"],
        )

    def test_value_template_embeds_internal_to_label_mapping(self) -> None:
        template = self.select["value_template"]
        self.assertIn(
            "'iphone_usb_wifi_fallback': 'USB (iPhone), Wi-Fi fallback'", template
        )
        self.assertIn(".get(value_json.mobile_connection,", template)

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_value_template_maps_internal_to_label(self) -> None:
        template = self.select["value_template"]
        self.assertEqual(
            _render(template, {"mobile_connection": "iphone_usb_wifi_fallback"}),
            "USB (iPhone), Wi-Fi fallback",
        )
        self.assertEqual(
            _render(template, {"mobile_connection": "iphone_usb"}), "USB (iPhone)"
        )
        state = build_state_payload(dict(STATUS))
        self.assertEqual(_render(template, state), "USB (iPhone), Wi-Fi fallback")


class SetMobileConnectionTests(unittest.TestCase):
    @staticmethod
    def _write_options(directory: str, options: dict) -> Path:
        path = Path(directory) / "options.json"
        path.write_text(json.dumps(options), encoding="utf-8")
        return path

    def test_writes_option_and_restarts_with_bearer(self) -> None:
        requests: list[urllib.request.Request] = []

        def urlopen(request, **kwargs):
            requests.append(request)
            return object()

        with tempfile.TemporaryDirectory() as directory:
            path = self._write_options(
                directory,
                {"enabled": True, "mobile_connection": "Wi-Fi hotspot"},
            )
            set_mobile_connection(
                "USB (iPhone)",
                token="secret-token",
                urlopen=urlopen,
                options_path=path,
            )

        self.assertEqual(len(requests), 2)
        options_request, restart_request = requests
        self.assertEqual(
            options_request.full_url, "http://supervisor/addons/self/options"
        )
        self.assertEqual(options_request.get_method(), "POST")
        self.assertEqual(
            options_request.get_header("Authorization"), "Bearer secret-token"
        )
        body = json.loads(options_request.data.decode("utf-8"))
        self.assertEqual(body["options"]["mobile_connection"], "USB (iPhone)")
        self.assertTrue(body["options"]["enabled"])
        self.assertEqual(
            restart_request.full_url, "http://supervisor/addons/self/restart"
        )
        self.assertEqual(restart_request.get_method(), "POST")
        self.assertEqual(
            restart_request.get_header("Authorization"), "Bearer secret-token"
        )
        self.assertIsNone(restart_request.data)

    def test_same_selection_is_ignored(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_options(
                directory, {"mobile_connection": "USB (iPhone)"}
            )
            set_mobile_connection(
                "USB (iPhone)",
                token="secret-token",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertEqual(calls, [])

    def test_missing_token_does_not_post(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_options(
                directory, {"mobile_connection": "Wi-Fi hotspot"}
            )
            set_mobile_connection(
                "USB (iPhone)",
                token="",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertEqual(calls, [])

    def test_unreadable_options_do_not_post(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            set_mobile_connection(
                "USB (iPhone)",
                token="secret-token",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertEqual(calls, [])

    def test_restart_skipped_when_options_rejected(self) -> None:
        attempts: list[str] = []

        def urlopen(request, **kwargs):
            attempts.append(request.full_url)
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {}, io.BytesIO(b"")
            )

        with tempfile.TemporaryDirectory() as directory:
            path = self._write_options(
                directory, {"mobile_connection": "Wi-Fi hotspot"}
            )
            set_mobile_connection(
                "USB (iPhone)",
                token="secret-token",
                urlopen=urlopen,
                options_path=path,
            )
        self.assertEqual(attempts, ["http://supervisor/addons/self/options"])


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
            {
                ENABLED_COMMAND_TOPIC,
                RECONCILE_COMMAND_TOPIC,
                MOBILE_CONNECTION_COMMAND_TOPIC,
                STATUS_TOPIC,
            },
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

    def test_mobile_connection_command_writes_selected_label(self) -> None:
        publisher, _engine, client = self._connected()
        with mock.patch(
            "rootfs.app.mqtt_publisher.set_mobile_connection"
        ) as writer:
            client.trigger_message(MOBILE_CONNECTION_COMMAND_TOPIC, b"USB (iPhone)")
        writer.assert_called_once_with("USB (iPhone)", token=publisher._token)
        self.assertEqual(client.published[-1][0], STATE_TOPIC)
        publisher.stop()

    def test_unknown_mobile_connection_is_ignored(self) -> None:
        publisher, _engine, client = self._connected()
        with mock.patch(
            "rootfs.app.mqtt_publisher.set_mobile_connection"
        ) as writer:
            client.trigger_message(
                MOBILE_CONNECTION_COMMAND_TOPIC, b"Carrier pigeon"
            )
        writer.assert_not_called()
        self.assertEqual(client.published[-1][0], STATE_TOPIC)
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

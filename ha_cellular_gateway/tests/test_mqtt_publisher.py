"""Publisher and fake-client connect, announce and stop lifecycle."""

from __future__ import annotations

import json
import unittest

from rootfs.app.mqtt_discovery import (
    AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    STATE_TOPIC,
    STATUS_TOPIC,
    build_state_payload,
)
from rootfs.app.mqtt_publisher import MqttPublisher
from rootfs.app.mqtt_service import MqttCredentials
from test_support.mqtt_fixtures import STATUS, FakeClient, StubEngine


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

        retained = {topic: retain for topic, _p, _q, retain in client.published}
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


if __name__ == "__main__":
    unittest.main()

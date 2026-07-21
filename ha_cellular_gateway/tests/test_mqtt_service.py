from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from rootfs.app.mqtt_publisher import MqttPublisher
from rootfs.app.mqtt_service import MqttCredentials, read_mqtt_service
from test_support.mqtt_fixtures import FakeClient, StubEngine


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

    def test_service_lookup_recovers_without_restart(self) -> None:
        engine = StubEngine()
        credentials = MqttCredentials("broker", 1883, None, None, False)
        connected = threading.Event()

        def factory(client_id):
            connected.set()
            return FakeClient(client_id)

        with mock.patch(
            "rootfs.app.mqtt_publisher.read_mqtt_service",
            side_effect=[None, credentials],
        ) as lookup:
            publisher = MqttPublisher(
                engine,
                client_factory=factory,
                interval=3600,
                retry_interval=0.01,
            )
            with self.assertLogs(
                "rootfs.app.mqtt_publisher",
                level="WARNING",
            ):
                self.assertFalse(publisher.start())
            self.assertTrue(connected.wait(1))
            self.assertGreaterEqual(lookup.call_count, 2)
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

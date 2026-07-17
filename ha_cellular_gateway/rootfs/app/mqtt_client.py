from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .mqtt_service import MqttCredentials

ClientFactory = Callable[[str], Any]
OnConnect = Callable[[Any, Any, Any, Any], None]
OnMessage = Callable[[Any, Any, Any], None]


def default_client_factory(client_id: str) -> Any:
    import paho.mqtt.client as mqtt

    return mqtt.Client(client_id=client_id)


class MqttConnection:
    def __init__(
        self,
        credentials: MqttCredentials,
        *,
        client_id: str,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._credentials = credentials
        self._client_id = client_id
        self._factory = client_factory or default_client_factory
        self._client: Any | None = None

    def connect(
        self,
        *,
        availability_topic: str,
        offline_payload: str,
        on_connect: OnConnect,
        on_message: OnMessage,
    ) -> None:
        client = self._factory(self._client_id)
        if self._credentials.username:
            client.username_pw_set(
                self._credentials.username,
                self._credentials.password,
            )
        if self._credentials.ssl:
            client.tls_set()
        client.will_set(availability_topic, offline_payload, qos=1, retain=True)
        client.on_connect = on_connect
        client.on_message = on_message
        self._client = client
        client.connect_async(self._credentials.host, self._credentials.port)
        client.loop_start()

    def subscribe(self, topic: str) -> None:
        if self._client is not None:
            self._client.subscribe(topic)

    def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        if self._client is not None:
            self._client.publish(topic, payload, qos, retain)

    def disconnect(self) -> None:
        if self._client is None:
            return
        self._client.loop_stop()
        self._client.disconnect()
        self._client = None

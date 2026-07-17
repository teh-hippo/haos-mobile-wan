from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any

from .addon_options import set_mobile_connection
from .errors import GatewayError
from .mqtt_client import ClientFactory, MqttConnection
from .mqtt_discovery import (
    AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    ENABLED_COMMAND_TOPIC,
    MOBILE_CONNECTION_COMMAND_TOPIC,
    PAYLOAD_BIRTH,
    PAYLOAD_OFFLINE,
    PAYLOAD_OFF,
    PAYLOAD_ON,
    PAYLOAD_ONLINE,
    PAYLOAD_PRESS,
    RECONCILE_COMMAND_TOPIC,
    STATE_TOPIC,
    STATUS_TOPIC,
    build_discovery_payload,
    build_state_payload,
)
from .mqtt_labels import MOBILE_CONNECTION_LABEL_OPTIONS
from .mqtt_service import MqttCredentials, read_mqtt_service

if TYPE_CHECKING:
    from .gateway import GatewayEngine

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "haos-mobile-wan"


class MqttPublisher:
    def __init__(
        self,
        engine: GatewayEngine,
        *,
        token: str | None = None,
        credentials: MqttCredentials | None = None,
        client_factory: ClientFactory | None = None,
        interval: float | None = None,
    ) -> None:
        self._engine = engine
        self._token = token
        self._credentials = credentials
        self._client_factory = client_factory
        self._interval = (
            interval if interval is not None else engine.config.reconcile_seconds
        )
        self._connection: MqttConnection | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        credentials = self._credentials or read_mqtt_service(token=self._token)
        if credentials is None:
            _LOGGER.warning("Starting without MQTT discovery")
            return False
        connection = MqttConnection(
            credentials,
            client_id=CLIENT_ID,
            client_factory=self._client_factory,
        )
        try:
            connection.connect(
                availability_topic=AVAILABILITY_TOPIC,
                offline_payload=PAYLOAD_OFFLINE,
                on_connect=self._on_connect,
                on_message=self._on_message,
            )
        except OSError as err:
            _LOGGER.warning("MQTT connection failed; starting without MQTT: %s", err)
            return False
        self._connection = connection
        self._thread = threading.Thread(
            target=self._publish_loop,
            name="mqtt-state",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        if self._connection is not None:
            self._connection.publish(
                AVAILABILITY_TOPIC,
                PAYLOAD_OFFLINE,
                qos=1,
                retain=True,
            )
            self._connection.disconnect()
            self._connection = None

    def publish_state(self) -> None:
        if self._connection is None:
            return
        payload = json.dumps(
            build_state_payload(self._engine.status()),
            separators=(",", ":"),
        )
        self._connection.publish(STATE_TOPIC, payload, qos=1, retain=True)

    def announce(self) -> None:
        if self._connection is None:
            return
        payload = json.dumps(build_discovery_payload(), separators=(",", ":"))
        self._connection.publish(DISCOVERY_TOPIC, payload, qos=1, retain=True)
        self._connection.publish(AVAILABILITY_TOPIC, PAYLOAD_ONLINE, qos=1, retain=True)
        self.publish_state()

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        if rc:
            _LOGGER.warning("MQTT broker refused the connection (code %s)", rc)
            return
        self.announce()
        for topic in (
            ENABLED_COMMAND_TOPIC,
            RECONCILE_COMMAND_TOPIC,
            MOBILE_CONNECTION_COMMAND_TOPIC,
            STATUS_TOPIC,
        ):
            client.subscribe(topic)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        payload = _decode(message.payload)
        if message.topic == ENABLED_COMMAND_TOPIC:
            self._handle_enabled(payload)
        elif message.topic == RECONCILE_COMMAND_TOPIC:
            self._handle_reconcile(payload)
        elif message.topic == MOBILE_CONNECTION_COMMAND_TOPIC:
            self._handle_mobile_connection(payload)
        elif message.topic == STATUS_TOPIC and payload == PAYLOAD_BIRTH:
            self.announce()

    def _handle_enabled(self, payload: str) -> None:
        if payload == PAYLOAD_ON:
            self._run(self._engine.apply)
        elif payload == PAYLOAD_OFF:
            self._run(lambda: self._engine.cleanup(preserve_host_protection=True))
        else:
            _LOGGER.warning("Ignoring unknown enabled command %r", payload)
            return
        self.publish_state()

    def _handle_reconcile(self, payload: str) -> None:
        if payload != PAYLOAD_PRESS:
            _LOGGER.warning("Ignoring unknown reconcile command %r", payload)
            return
        self._run(self._engine.reconcile)
        self.publish_state()

    def _handle_mobile_connection(self, payload: str) -> None:
        if payload in MOBILE_CONNECTION_LABEL_OPTIONS:
            set_mobile_connection(payload, token=self._token)
        else:
            _LOGGER.warning("Ignoring unknown connection method %r", payload)
        self.publish_state()

    def _run(self, action: Any) -> None:
        try:
            action()
        except (GatewayError, OSError, ValueError) as err:
            _LOGGER.warning("MQTT command failed: %s", err)

    def _publish_loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.publish_state()


def _decode(payload: Any) -> str:
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", "replace").strip()
    return str(payload).strip()

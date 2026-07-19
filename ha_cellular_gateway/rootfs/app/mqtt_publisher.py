from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any

from .mqtt_client import ClientFactory, MqttConnection
from .mqtt_discovery import (
    AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    PAYLOAD_BIRTH,
    PAYLOAD_OFFLINE,
    PAYLOAD_ONLINE,
    STATE_TOPIC,
    STATUS_TOPIC,
    build_discovery_payload,
    build_state_payload,
)
from .mqtt_service import MqttCredentials, read_mqtt_service

if TYPE_CHECKING:
    from .gateway import GatewayEngine

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "haos-mobile-wan"
MQTT_RETRY_SECONDS = 60.0


class MqttPublisher:
    def __init__(
        self,
        engine: GatewayEngine,
        *,
        token: str | None = None,
        credentials: MqttCredentials | None = None,
        client_factory: ClientFactory | None = None,
        interval: float | None = None,
        retry_interval: float = MQTT_RETRY_SECONDS,
    ) -> None:
        self._engine = engine
        self._token = token
        self._credentials = credentials
        self._client_factory = client_factory
        self._interval = (
            interval if interval is not None else engine.config.reconcile_seconds
        )
        self._retry_interval = retry_interval
        self._connection: MqttConnection | None = None
        self._warning_emitted = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        connected = self._connect()
        self._thread = threading.Thread(
            target=self._publish_loop,
            name="mqtt-state",
            daemon=True,
        )
        self._thread.start()
        return connected

    def _connect(self) -> bool:
        credentials = self._credentials or read_mqtt_service(
            token=self._token,
            warn=not self._warning_emitted,
        )
        if credentials is None:
            self._log_unavailable(
                "MQTT discovery is unavailable; retrying in %s seconds",
                self._retry_interval,
            )
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
            self._log_unavailable(
                "MQTT connection failed; retrying in %s seconds: %s",
                self._retry_interval,
                err,
            )
            return False
        self._connection = connection
        if self._warning_emitted:
            _LOGGER.info("MQTT discovery recovered")
        self._warning_emitted = False
        return True

    def _log_unavailable(self, message: str, *args: object) -> None:
        level = logging.DEBUG if self._warning_emitted else logging.WARNING
        _LOGGER.log(level, message, *args)
        self._warning_emitted = True

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
        client.subscribe(STATUS_TOPIC)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        payload = _decode(message.payload)
        if message.topic == STATUS_TOPIC and payload == PAYLOAD_BIRTH:
            self.announce()

    def _publish_loop(self) -> None:
        while True:
            interval = (
                self._interval
                if self._connection is not None
                else self._retry_interval
            )
            if self._stop.wait(interval):
                return
            if self._connection is None:
                self._connect()
            else:
                self.publish_state()


def _decode(payload: Any) -> str:
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", "replace").strip()
    return str(payload).strip()

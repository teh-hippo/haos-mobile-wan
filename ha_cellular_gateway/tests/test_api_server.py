import http.client
import json
import logging
import threading
import unittest

from rootfs.app import api_server
from rootfs.app.api_server import GatewayServer


class StubEngine:
    def health(self) -> dict[str, object]:
        return {"ok": True}

    def status(self) -> dict[str, object]:
        return {"enabled": False}

class ApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StubEngine()
        self.server = GatewayServer(("127.0.0.1", 0), self.engine, "token")
        self.worker = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
        )
        self.worker.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.worker.join(timeout=2)
        self.server.server_close()

    def _post(self, path: str) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(
                "POST",
                path,
                body="{}",
                headers={
                    "Authorization": "Bearer token",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body
        finally:
            connection.close()

    def _get_health(self) -> int:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_request_logging_uses_debug_level(self) -> None:
        with self.assertLogs(api_server.__name__, level="DEBUG") as captured:
            self._get_health()

        self.assertTrue(
            any("/health" in record.getMessage() for record in captured.records)
        )
        self.assertTrue(
            all(record.levelno == logging.DEBUG for record in captured.records)
        )

    def test_request_logging_is_hidden_at_info_level(self) -> None:
        with self.assertNoLogs(api_server.__name__, level="INFO"):
            self._get_health()

    def test_post_control_endpoints_are_not_available(self) -> None:
        for path in ("/v2/enabled", "/v2/reconcile"):
            with self.subTest(path=path):
                status, body = self._post(path)
                self.assertEqual(status, 404)
                self.assertEqual(body, {"error": "not_found"})


if __name__ == "__main__":
    unittest.main()

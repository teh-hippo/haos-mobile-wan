import http.client
import json
import threading
import unittest

from rootfs.app.api_server import GatewayServer


class StubEngine:
    def __init__(self) -> None:
        self.cleaned = False
        self.applied: list[str] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def status(self) -> dict[str, object]:
        return {"mode": "disabled"}

    def reconcile(self) -> None:
        return None

    def cleanup(self, **kwargs) -> None:
        self.cleaned = kwargs.get("preserve_host_protection") is True

    def apply(self, mode: str) -> None:
        self.applied.append(mode)


class ApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StubEngine()
        self.server = GatewayServer(("127.0.0.1", 0), self.engine, "token")
        self.worker = threading.Thread(target=self.server.serve_forever)
        self.worker.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.worker.join(timeout=2)
        self.server.server_close()

    def _post_mode(self, mode: str) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(
                "POST",
                "/v1/mode",
                body=json.dumps({"mode": mode}),
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

    def test_mode_rejects_unknown_values(self) -> None:
        status, body = self._post_mode("standby")

        self.assertEqual(status, 409)
        self.assertEqual(body, {"error": "Mode must be disabled or active"})
        self.assertEqual(self.engine.applied, [])
        self.assertFalse(self.engine.cleaned)

    def test_mode_accepts_disabled_and_active(self) -> None:
        disabled_status, _ = self._post_mode("disabled")
        active_status, _ = self._post_mode("active")

        self.assertEqual(disabled_status, 200)
        self.assertEqual(active_status, 200)
        self.assertTrue(self.engine.cleaned)
        self.assertEqual(self.engine.applied, ["active"])


if __name__ == "__main__":
    unittest.main()

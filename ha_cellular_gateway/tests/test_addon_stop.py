from __future__ import annotations

import http.client
import unittest

from rootfs.app.addon_stop import STOP_PATH, request_self_stop


class FakeConnection:
    def __init__(self, *, request_error: Exception | None = None) -> None:
        self.requests: list[tuple[str, str, dict[str, str] | None]] = []
        self.closed = False
        self.getresponse_called = False
        self._request_error = request_error

    def request(self, method, url, body=None, headers=None) -> None:
        self.requests.append((method, url, headers))
        if self._request_error is not None:
            raise self._request_error

    def getresponse(self):
        self.getresponse_called = True
        raise AssertionError("self-stop must not wait for a response")

    def close(self) -> None:
        self.closed = True


class RequestSelfStopTests(unittest.TestCase):
    def test_sends_post_and_closes_without_reading_response(self) -> None:
        connection = FakeConnection()

        error = request_self_stop(
            token="tok",
            connection_factory=lambda: connection,
        )

        self.assertIsNone(error)
        self.assertEqual(
            connection.requests,
            [("POST", STOP_PATH, {"Authorization": "Bearer tok"})],
        )
        self.assertTrue(connection.closed)
        self.assertFalse(connection.getresponse_called)

    def test_missing_token_is_reported(self) -> None:
        calls: list[bool] = []

        error = request_self_stop(
            token="",
            connection_factory=lambda: calls.append(True) or FakeConnection(),
        )

        self.assertEqual(error, "Supervisor token is unavailable")
        self.assertEqual(calls, [])

    def test_connection_failure_is_returned(self) -> None:
        connection = FakeConnection(
            request_error=ConnectionRefusedError("supervisor down"),
        )

        error = request_self_stop(
            token="tok",
            connection_factory=lambda: connection,
        )

        self.assertIn("supervisor down", error or "")
        self.assertTrue(connection.closed)

    def test_send_failure_is_returned(self) -> None:
        connection = FakeConnection(
            request_error=http.client.HTTPException("broken pipe"),
        )

        error = request_self_stop(
            token="tok",
            connection_factory=lambda: connection,
        )

        self.assertIn("broken pipe", error or "")
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()

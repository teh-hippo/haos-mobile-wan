import threading
import unittest
from unittest import mock

from rootfs.app import main
from rootfs.app.errors import GatewayError


class MainShutdownTests(unittest.TestCase):
    def test_request_shutdown_quiesces_engine_before_stopping_server(self) -> None:
        engine = mock.Mock()
        engine.stop_event = threading.Event()
        server = mock.Mock()
        thread = mock.Mock()
        thread.start.side_effect = lambda: self.assertTrue(engine.stop_event.is_set())

        with mock.patch.object(
            main.threading,
            "Thread",
            return_value=thread,
        ) as constructor:
            main._request_shutdown(engine, server)

        constructor.assert_called_once_with(
            target=server.shutdown,
            name="gateway-api-shutdown",
            daemon=True,
        )
        thread.start.assert_called_once_with()

    def test_shutdown_prioritises_gateway_cleanup(self) -> None:
        order: list[str] = []
        engine = mock.Mock()
        publisher = mock.Mock()
        server = mock.Mock()
        worker = mock.Mock()
        engine.stop.side_effect = lambda: order.append("engine")
        publisher.stop.side_effect = lambda: order.append("publisher")
        server.server_close.side_effect = lambda: order.append("server")
        worker.join.side_effect = lambda **_kwargs: order.append("worker")

        main._shutdown(engine, publisher, server, worker)

        self.assertEqual(order, ["engine", "publisher", "server", "worker"])
        worker.join.assert_called_once_with(timeout=10)

    def test_shutdown_finishes_teardown_after_cleanup_failure(self) -> None:
        order: list[str] = []
        engine = mock.Mock()
        publisher = mock.Mock()
        server = mock.Mock()
        worker = mock.Mock()

        def fail_cleanup() -> None:
            order.append("engine")
            raise GatewayError("cleanup failed")

        engine.stop.side_effect = fail_cleanup
        publisher.stop.side_effect = lambda: order.append("publisher")
        server.server_close.side_effect = lambda: order.append("server")
        worker.join.side_effect = lambda **_kwargs: order.append("worker")

        with self.assertRaisesRegex(GatewayError, "cleanup failed"):
            main._shutdown(engine, publisher, server, worker)

        self.assertEqual(order, ["engine", "publisher", "server", "worker"])


if __name__ == "__main__":
    unittest.main()

import threading
import unittest
from unittest import mock

from rootfs.app import main
from rootfs.app.errors import GatewayError


class ConfigureLoggingTests(unittest.TestCase):
    def test_uses_info_level_by_default(self) -> None:
        with (
            mock.patch.object(main.logging, "basicConfig") as basic_config,
            mock.patch.dict(main.os.environ, {}, clear=True),
        ):
            main.configure_logging()

        basic_config.assert_called_once_with(
            level="INFO", format="%(levelname)s %(name)s: %(message)s"
        )

    def test_honours_log_level_environment_override(self) -> None:
        with (
            mock.patch.object(main.logging, "basicConfig") as basic_config,
            mock.patch.dict(main.os.environ, {"LOG_LEVEL": "DEBUG"}),
        ):
            main.configure_logging()

        basic_config.assert_called_once_with(
            level="DEBUG", format="%(levelname)s %(name)s: %(message)s"
        )


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


class MainOrchestrationTests(unittest.TestCase):
    def test_main_wires_collaborators_serves_and_always_shuts_down(self) -> None:
        config = mock.Mock(api_bind="0.0.0.0", api_port=8443)
        engine = mock.Mock()
        server = mock.Mock()
        publisher = mock.Mock()
        worker_thread = mock.Mock()

        with (
            mock.patch.object(main, "configure_logging") as configure_logging,
            mock.patch.object(main, "CommandRunner") as command_runner_cls,
            mock.patch.object(main, "prune_legacy_options", return_value=None) as prune,
            mock.patch.object(
                main.GatewayConfig, "load_path", return_value=(config, None)
            ) as load_path,
            mock.patch.object(main, "GatewayEngine", return_value=engine) as engine_cls,
            mock.patch.object(
                main, "load_or_create_token", return_value="tok123"
            ) as load_token,
            mock.patch.object(main, "GatewayServer", return_value=server) as server_cls,
            mock.patch.object(
                main.threading, "Thread", return_value=worker_thread
            ) as thread_cls,
            mock.patch.object(
                main, "MqttPublisher", return_value=publisher
            ) as publisher_cls,
            mock.patch.object(main.signal, "signal") as signal_signal,
            mock.patch.object(main, "_request_shutdown") as request_shutdown,
            mock.patch.object(main, "_shutdown") as shutdown,
        ):
            main.main()

            self.assertEqual(signal_signal.call_count, 2)
            registered = {
                call.args[0]: call.args[1] for call in signal_signal.call_args_list
            }
            self.assertEqual(set(registered), {main.signal.SIGTERM, main.signal.SIGINT})
            request_shutdown.assert_not_called()
            registered[main.signal.SIGTERM]()
            request_shutdown.assert_called_once_with(engine, server)

        configure_logging.assert_called_once_with()
        prune.assert_called_once_with()
        command_runner_cls.assert_called_once_with()
        load_path.assert_called_once_with()
        engine_cls.assert_called_once_with(
            config, runner=command_runner_cls.return_value, config_error=None
        )
        load_token.assert_called_once_with()
        server_cls.assert_called_once_with(
            (config.api_bind, config.api_port), engine, "tok123"
        )
        thread_cls.assert_called_once_with(
            target=engine.run_loop, name="gateway-reconcile", daemon=True
        )
        worker_thread.start.assert_called_once_with()
        publisher_cls.assert_called_once_with(engine)
        publisher.start.assert_called_once_with()
        server.serve_forever.assert_called_once_with(poll_interval=0.5)
        shutdown.assert_called_once_with(engine, publisher, server, worker_thread)

    def test_main_logs_migration_warning_when_options_were_pruned(self) -> None:
        config = mock.Mock(api_bind="0.0.0.0", api_port=8443)
        engine = mock.Mock()
        server = mock.Mock()
        publisher = mock.Mock()

        with (
            mock.patch.object(main, "configure_logging"),
            mock.patch.object(main, "CommandRunner"),
            mock.patch.object(
                main, "prune_legacy_options", return_value="removed legacy_option"
            ),
            mock.patch.object(
                main.GatewayConfig, "load_path", return_value=(config, None)
            ),
            mock.patch.object(main, "GatewayEngine", return_value=engine),
            mock.patch.object(main, "load_or_create_token", return_value="tok123"),
            mock.patch.object(main, "GatewayServer", return_value=server),
            mock.patch.object(main.threading, "Thread", return_value=mock.Mock()),
            mock.patch.object(main, "MqttPublisher", return_value=publisher),
            mock.patch.object(main.signal, "signal"),
            mock.patch.object(main, "_shutdown"),
            mock.patch.object(main._LOGGER, "warning") as warning,
        ):
            main.main()

        warning.assert_called_once_with("%s", "removed legacy_option")

    def test_main_shuts_down_even_when_serve_forever_raises(self) -> None:
        config = mock.Mock(api_bind="0.0.0.0", api_port=8443)
        engine = mock.Mock()
        server = mock.Mock()
        server.serve_forever.side_effect = RuntimeError("socket closed")
        publisher = mock.Mock()
        worker_thread = mock.Mock()

        with (
            mock.patch.object(main, "configure_logging"),
            mock.patch.object(main, "CommandRunner"),
            mock.patch.object(main, "prune_legacy_options", return_value=None),
            mock.patch.object(
                main.GatewayConfig, "load_path", return_value=(config, None)
            ),
            mock.patch.object(main, "GatewayEngine", return_value=engine),
            mock.patch.object(main, "load_or_create_token", return_value="tok123"),
            mock.patch.object(main, "GatewayServer", return_value=server),
            mock.patch.object(main.threading, "Thread", return_value=worker_thread),
            mock.patch.object(main, "MqttPublisher", return_value=publisher),
            mock.patch.object(main.signal, "signal"),
            mock.patch.object(main, "_shutdown") as shutdown,
        ):
            with self.assertRaisesRegex(RuntimeError, "socket closed"):
                main.main()

        shutdown.assert_called_once_with(engine, publisher, server, worker_thread)


if __name__ == "__main__":
    unittest.main()

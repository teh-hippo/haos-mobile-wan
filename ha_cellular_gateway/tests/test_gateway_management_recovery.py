import json
import time
import unittest

from gateway_support import GatewayTestCase
from rootfs.app.errors import GatewayError
from rootfs.app.gateway import GatewayEngine
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class GatewayManagementRecoveryTests(GatewayTestCase):
    def test_running_reconcile_activates_gateway(self) -> None:
        engine = self._prepare_active_engine()
        engine.startup_cleanup_pending = False

        engine.reconcile()

        self.assertTrue(engine.applied)
        self.assertTrue(engine.dhcp.running)
        self.assertNotEqual(engine.status()["state"], "disabled")

    def test_restart_logs_interrupted_state_recovery(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        restarted = self._restart_engine()

        with self.assertLogs(
            "rootfs.app.gateway_reconcile",
            level="INFO",
        ) as captured:
            restarted.reconcile()

        messages = "\n".join(captured.output)
        self.assertIn("Interrupted gateway state detected", messages)
        self.assertIn("Interrupted gateway recovery completed", messages)

    def test_config_error_does_not_log_recovery_complete(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        restarted = self._restart_engine()
        restarted.config_error = "Invalid app configuration"

        with self.assertLogs(
            "rootfs.app.gateway_reconcile",
            level="WARNING",
        ) as captured:
            restarted.reconcile()

        messages = "\n".join(captured.output)
        self.assertIn("Interrupted gateway state detected", messages)
        self.assertNotIn("Interrupted gateway recovery completed", messages)

    def test_reconcile_skips_work_after_stop_requested(self) -> None:
        self.engine.stop_event.set()
        self.engine._resolve_management = lambda: (_ for _ in ()).throw(
            AssertionError("management resolution must be skipped")
        )
        self.engine._refresh_health_if_due = lambda: (_ for _ in ()).throw(
            AssertionError("health refresh must be skipped")
        )

        self.engine.reconcile(refresh_health=True)

        self.assertIsNone(self.engine.last_reconcile)

    def test_run_loop_skips_auto_disable_after_stop_request(self) -> None:
        def request_stop(*, refresh_health: bool = False) -> None:
            self.engine.stop_event.set()

        def fail_auto_disable(_engine: GatewayEngine) -> None:
            raise AssertionError("auto-disable must be skipped")

        self.engine.reconcile = request_stop
        self.engine.auto_disable.reconcile = fail_auto_disable

        self.engine.run_loop()

    def test_config_error_still_cleans_owned_host_state(self) -> None:
        active = self._prepare_active_engine()
        active.apply()
        values = sysctl_values()
        degraded = build_engine(
            make_config(),
            runner=active.runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        degraded.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )
        degraded.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream preparation must stay blocked")
        )

        degraded.reconcile()

        self.assertIsNone(degraded.owned_state)
        self.assertNotIn(
            "enx001122334455",
            degraded.runner.routes.interface_addresses,
        )
        self.assertFalse(degraded.firewall.host_protection_installed("enx001122334455"))
        self.assertIn("Invalid app configuration", degraded.last_error)

    def test_config_error_without_owned_state_does_not_mutate_host(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream preparation must stay blocked")
        )

        engine.reconcile()

        self.assertFalse(engine.applied)
        self.assertIsNone(engine.last_downstream)
        self.assertIn("Invalid app configuration", engine.last_error)

    def test_config_error_rejects_direct_enable_without_mutation(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream preparation must stay blocked")
        )

        with self.assertRaisesRegex(
            GatewayError,
            "Invalid app configuration",
        ):
            engine.apply()

        self.assertFalse(engine.applied)

    def test_config_error_forces_owned_only_direct_cleanup(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )

        engine.cleanup()

        self.assertFalse(engine.applied)

    def test_management_recovers_across_reconciles_without_restart(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.routes.main_default_routes = []
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, management=None, **kwargs: (
            [] if management is not None else ["Management interface is unavailable"]
        )
        runner.networkmanager.nm_wifi_cache["wlan0"] = {"Phone"}
        engine.firewall.installed = lambda downstream=None, upstream_interface=None: (
            engine.applied
        )
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )

        engine.reconcile()
        self.assertIsNone(engine.management)
        self.assertFalse(engine.applied)
        self.assertIn(
            "Management interface is unavailable",
            engine.last_safety_errors,
        )
        self.assertNotIn(
            "enx001122334455",
            runner.routes.interface_addresses,
        )

        runner.routes.main_default_routes = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}
        ]

        engine.reconcile()
        self.assertIsNotNone(engine.management)
        assert engine.management is not None
        self.assertEqual(engine.management.interface, "end0")
        self.assertTrue(engine.applied)

    def test_missing_management_blocks_profile_and_downstream_mutation(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.routes.main_default_routes = []
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must wait for management")
        )

        engine.reconcile()

        self.assertEqual(runner.networkmanager.nm_profiles, {})
        self.assertIsNone(engine.last_downstream)
        self.assertIn("Management interface is unavailable", engine.last_error)

    def test_management_interface_change_releases_profiles_and_fails_closed(
        self,
    ) -> None:
        engine = self._prepare_active_engine()
        self.assertEqual(engine.management_interface, "end0")
        self.assertTrue(engine.runner.networkmanager.nm_profiles)
        engine.runner.routes.main_default_routes = [
            {"dst": "default", "gateway": "192.168.2.1", "dev": "eth9"}
        ]
        engine.runner.routes.interface_addresses["eth9"] = ("192.168.2.2", 24)

        engine.reconcile()

        self.assertFalse(engine.applied)
        self.assertEqual(engine.runner.networkmanager.nm_profiles, {})
        self.assertIn("Management interface changed", engine.last_error)

    def test_persisted_extra_state_key_is_ignored(self) -> None:
        self.state_path.write_text(
            json.dumps(
                {
                    "unused": {
                        "started_at": time.time() - 400,
                        "deadline": time.time() - 100,
                    }
                }
            ),
            encoding="utf-8",
        )
        engine = self._prepare_active_engine()
        engine.reconcile()
        self.assertTrue(engine.applied)
        self.assertNotIn("unused", self.state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

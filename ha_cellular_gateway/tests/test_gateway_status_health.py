import json
import threading
import time
import unittest

from gateway_support import GatewayTestCase
from rootfs.app.const import IPHONE_USB, WIFI_HOTSPOT
from rootfs.app.upstream_models import ResolvedUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner


class GatewayStatusHealthTests(GatewayTestCase):
    def test_status_uses_cached_health(self) -> None:
        self.engine.upstream_healthy = True
        self.engine.public_ip = "203.0.113.10"
        before = len(self.runner.commands)
        status = self.engine.status()
        self.assertEqual(len(self.runner.commands), before)
        self.assertTrue(status["upstream_healthy"])
        self.assertEqual(status["public_ip"], "203.0.113.10")

    def test_status_never_reports_disabled_state(self) -> None:
        status = self.engine.status()
        self.assertEqual(status["state"], "connecting")
        self.assertNotIn("enabled", status)
        self.assertNotIn("configured_enabled", status)
        self.assertNotIn("enabled", status["config"])

    def test_status_reports_error_and_attention_for_genuine_fault(self) -> None:
        engine = self._prepare_active_engine()
        engine.last_safety_errors = ["Management interface is unavailable"]
        status = engine.status()
        self.assertEqual(status["state"], "error")
        self.assertEqual(status["health"], "attention")
        self.assertEqual(
            status["health_issues"],
            ["The management interface is unavailable"],
        )

    def test_status_treats_missing_upstream_as_healthy_waiting(self) -> None:
        engine = self._prepare_active_engine()
        engine.last_error = None
        engine.last_safety_errors = ["Upstream interface is unavailable"]
        status = engine.status()
        self.assertEqual(status["state"], "waiting")
        self.assertEqual(status["health"], "healthy")
        self.assertEqual(status["health_issues"], [])
        self.assertEqual(status["safety_errors"], ["Upstream interface is unavailable"])

    def test_status_keeps_combined_usb_waiting_errors_healthy(self) -> None:
        engine = self._prepare_active_engine()
        pairing_message = (
            "Connect a single trusted iPhone with Personal Hotspot enabled"
        )
        errors = [pairing_message, "Upstream interface is unavailable"]
        engine.upstream.pairing_state = "waiting_for_device"
        engine.upstream.pairing_message = pairing_message
        engine.last_safety_errors = errors
        engine.last_error = "; ".join(errors)

        status = engine.status()

        self.assertEqual(status["state"], "waiting")
        self.assertEqual(status["health"], "healthy")
        self.assertEqual(status["health_issues"], [])

    def test_status_reports_connecting_while_source_setup_is_in_progress(self) -> None:
        engine = self._prepare_active_engine()
        engine.upstream.pairing_state = "waiting_for_profile"
        self.assertEqual(engine.status()["state"], "connecting")
        engine.apply()
        self.assertTrue(engine.applied)
        self.assertFalse(engine.upstream_healthy)
        self.assertEqual(engine.status()["state"], "connected")

    def test_status_reports_connected_when_gateway_is_applied(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        engine.upstream_healthy = False
        self.assertEqual(engine.status()["state"], "connected")

    def test_upstream_change_invalidates_cached_health(self) -> None:
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        usb = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.2/28",
            gateway="172.20.10.1",
        )
        self.engine._record_upstream(wifi)
        self.engine.upstream_healthy = True
        self.engine.public_ip = "203.0.113.10"
        self.engine.last_health_probe = time.time()

        self.engine._record_upstream(usb)

        self.assertFalse(self.engine.upstream_healthy)
        self.assertIsNone(self.engine.public_ip)
        self.assertIsNone(self.engine.last_health_probe)

    def test_stale_health_probe_result_is_discarded(self) -> None:
        self.engine.applied = True
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        usb = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.2/28",
            gateway="172.20.10.1",
        )
        self.engine._record_upstream(wifi)

        def stale_probe(upstream):
            self.engine._record_upstream(usb)
            return True, "203.0.113.10"

        self.engine._health_probe = stale_probe
        self.engine._refresh_health_if_due()

        self.assertEqual(self.engine.last_upstream, usb)
        self.assertFalse(self.engine.upstream_healthy)
        self.assertIsNone(self.engine.public_ip)
        self.assertIsNone(self.engine.last_health_probe)

    def test_health_probe_result_is_discarded_after_cleanup(self) -> None:
        self.engine.applied = True
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        self.engine._record_upstream(wifi)

        def stale_probe(upstream):
            self.engine.cleanup()
            return True, "203.0.113.10"

        self.engine._health_probe = stale_probe
        self.engine._refresh_health_if_due()

        self.assertEqual(self.engine.last_upstream, wifi)
        self.assertFalse(self.engine.upstream_healthy)
        self.assertIsNone(self.engine.public_ip)
        self.assertIsNone(self.engine.last_health_probe)

    def test_manual_reconcile_does_not_run_external_health_probe(self) -> None:
        engine = self._prepare_active_engine()
        engine.startup_cleanup_pending = False
        before = len(engine.runner.commands)
        engine.reconcile()
        self.assertFalse(
            any(
                command and command[0] == "curl"
                for command in engine.runner.commands[before:]
            )
        )

    def test_status_and_state_do_not_disclose_hotspot_password(self) -> None:
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.owned_state = {"downstream": "eth1"}
        engine._persist_state()

        status_text = json.dumps(engine.status(), sort_keys=True)
        self.assertNotIn("hotspot_password", status_text)
        self.assertNotIn("supersecret", status_text)
        self.assertIn("networkmanager", engine.status())
        self.assertNotIn("supersecret", self.state_path.read_text(encoding="utf-8"))

    def test_status_remains_responsive_during_blocking_upstream_resolution(
        self,
    ) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        started = threading.Event()
        release = threading.Event()

        def slow_resolve(*_a, **_k):
            started.set()
            release.wait(timeout=2)
            return None, ["waiting for usb"]

        engine.upstream.resolve = slow_resolve
        worker = threading.Thread(target=engine.reconcile)
        worker.start()
        self.assertTrue(started.wait(timeout=1))

        began = time.time()
        status = engine.status()
        elapsed = time.time() - began

        release.set()
        worker.join(timeout=2)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(status["mobile_connection"], IPHONE_USB)


if __name__ == "__main__":
    unittest.main()

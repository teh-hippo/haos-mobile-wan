import tempfile
import unittest
from pathlib import Path

from gateway_support import GatewayTestCase
from rootfs.app.const import IPHONE_USB
from rootfs.app.errors import GatewayError
from rootfs.app.management import ManagementBaseline
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class GatewayRuntimeShutdownTests(GatewayTestCase):
    def test_stop_pending_reconcile_skips_upstream_and_health_probes(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.lifecycle_state.startup_cleanup_pending = False
        engine.auto_disable.pending = True
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream resolution must be skipped while stopping")
        )
        engine._health_probe = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("health probe must be skipped while stopping")
        )

        engine.reconcile(refresh_health=True)

        self.assertIsNone(engine.selection_state.upstream)
        self.assertIsNone(engine.health_state.last_health_probe)

    def test_stop_cleans_upstream_after_gateway_cleanup_failure(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        upstream_cleaned = False

        def fail_cleanup(**kwargs) -> None:
            raise GatewayError("host cleanup failed")

        def cleanup_upstream() -> None:
            nonlocal upstream_cleaned
            upstream_cleaned = True

        engine.cleanup = fail_cleanup
        engine.upstream.cleanup = cleanup_upstream

        with self.assertLogs(
            "rootfs.app.gateway_runtime",
            level="INFO",
        ) as captured:
            with self.assertRaisesRegex(GatewayError, "host cleanup failed"):
                engine.stop()

        self.assertTrue(upstream_cleaned)
        self.assertIn(
            "Graceful shutdown cleanup failed",
            "\n".join(captured.output),
        )

    def test_stop_deletes_app_owned_wifi_profile(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.management = ManagementBaseline("eth0", "192.168.1.2/24")
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.upstream_lifecycle.activate(engine.management)
        self.assertTrue(engine.runner.networkmanager.nm_profiles)

        with self.assertLogs(
            "rootfs.app.gateway_runtime",
            level="INFO",
        ) as captured:
            engine.stop()

        self.assertEqual(engine.runner.networkmanager.nm_profiles, {})
        self.assertIn(
            "Graceful shutdown cleanup completed",
            "\n".join(captured.output),
        )

    def test_stop_after_detected_usb_does_not_flush_external_interface(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.routes.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.routes.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usb_root = root / "dev" / "bus" / "usb"
            sys_net_root = root / "sys" / "class" / "net"
            sys_usb_root = root / "sys" / "bus" / "usb" / "devices"
            driver_root = root / "drivers"
            run_dir = root / "run"
            usb_root.mkdir(parents=True)
            sys_net_root.mkdir(parents=True)
            sys_usb_root.mkdir(parents=True)
            driver_root.mkdir(parents=True)

            target = driver_root / "ipheth"
            target.mkdir()
            interface = sys_net_root / "eth0" / "device"
            interface.mkdir(parents=True)
            (interface / "driver").symlink_to(target)

            device = sys_usb_root / "1-1"
            device.mkdir(parents=True)
            (device / "idVendor").write_text("05ac\n", encoding="utf-8")

            engine.upstream = IPhoneUsbUpstream(
                engine.config,
                lambda *args, **kwargs: runner.run(list(args), **kwargs),
                run_dir=run_dir,
                lockdown_dir=root / "lockdown",
                usb_root=usb_root,
                sys_net_root=sys_net_root,
                sys_usb_root=sys_usb_root,
                which=lambda command: f"/usr/bin/{command}",
                popen=lambda *args, **kwargs: FakeProcess(),
            )
            runner.commands.clear()
            engine.stop()

        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "del"]
                or command[:5] == ["ip", "route", "del", "default", "dev"]
                for command in runner.commands
            )
        )


if __name__ == "__main__":
    unittest.main()

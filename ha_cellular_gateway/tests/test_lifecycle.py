import tempfile
import unittest
from pathlib import Path

from rootfs.app import lifecycle
from rootfs.app.const import IPHONE_USB, WIFI_HOTSPOT
from rootfs.app.errors import GatewayError
from rootfs.app.gateway import GatewayEngine
from rootfs.app.upstream_models import ResolvedUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner

USB_UPSTREAM = ResolvedUpstream(
    connection=IPHONE_USB,
    interface="eth0",
    address="172.20.10.2/28",
    gateway="172.20.10.1",
)


class LifecycleTransitionLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _engine(self, **overrides: object) -> GatewayEngine:
        values = sysctl_values()
        engine = build_engine(
            make_config(**overrides),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *_a, **_k: []
        engine.lifecycle_state.startup_cleanup_pending = False
        return engine

    def test_iphone_connect_logs_once_on_edge(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            lifecycle.log_upstream_transitions(engine, None, None)

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            lifecycle.log_upstream_transitions(engine, USB_UPSTREAM, None)
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["iPhone USB device connected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            lifecycle.log_upstream_transitions(engine, USB_UPSTREAM, None)

    def test_wifi_connect_logs_once_on_edge(self) -> None:
        engine = self._engine(
            mobile_connection=WIFI_HOTSPOT,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            lifecycle.log_upstream_transitions(
                engine,
                None,
                {"enabled": True, "connected": False},
            )

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            lifecycle.log_upstream_transitions(
                engine,
                None,
                {"enabled": True, "connected": True},
            )
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Wi-Fi hotspot connected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            lifecycle.log_upstream_transitions(
                engine,
                None,
                {"enabled": True, "connected": True},
            )

    def test_disconnect_logs_once_when_iphone_upstream_lost(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            lifecycle.log_upstream_transitions(engine, USB_UPSTREAM, None)
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["iPhone USB device connected"],
        )

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            lifecycle.log_upstream_transitions(engine, None, None)
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Mobile upstream disconnected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            lifecycle.log_upstream_transitions(engine, None, None)

    def test_disconnect_logs_once_when_wifi_disassociates(self) -> None:
        engine = self._engine(
            mobile_connection=WIFI_HOTSPOT,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            lifecycle.log_upstream_transitions(
                engine,
                None,
                {"enabled": True, "connected": True},
            )
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Wi-Fi hotspot connected"],
        )

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            lifecycle.log_upstream_transitions(
                engine,
                None,
                {"enabled": True, "connected": False},
            )
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Mobile upstream disconnected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            lifecycle.log_upstream_transitions(
                engine,
                None,
                {"enabled": True, "connected": False},
            )

    def test_wifi_status_failure_is_non_throwing(self) -> None:
        engine = self._engine(
            mobile_connection=WIFI_HOTSPOT,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        engine.wifi.profile.active_uuid = lambda interface: (_ for _ in ()).throw(
            GatewayError("NetworkManager unavailable")
        )

        self.assertIsNone(lifecycle.wifi_interface_status(engine))


if __name__ == "__main__":
    unittest.main()

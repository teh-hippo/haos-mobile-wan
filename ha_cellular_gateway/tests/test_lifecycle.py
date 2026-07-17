import tempfile
import unittest
from pathlib import Path

from rootfs.app import lifecycle
from rootfs.app.const import IPHONE_USB, WIFI_HOTSPOT
from rootfs.app.gateway import GatewayEngine
from rootfs.app.upstream_models import ResolvedUpstream

from helpers import FakeRunner, make_config, sysctl_values

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
        engine = GatewayEngine(
            make_config(enabled=False, **overrides),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *_a, **_k: []
        engine.startup_cleanup_pending = False
        return engine

    def test_iphone_connect_logs_once_on_edge(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        states = [(None, ["waiting"]), (USB_UPSTREAM, []), (USB_UPSTREAM, [])]
        engine.upstream.resolve = lambda *_a, **_k: states.pop(0)

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            engine.reconcile()

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            engine.reconcile()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["iPhone USB device connected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            engine.reconcile()

    def test_wifi_connect_logs_once_on_edge(self) -> None:
        engine = self._engine(
            mobile_connection=WIFI_HOTSPOT,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        statuses = [
            {"enabled": True, "connected": False},
            {"enabled": True, "connected": True},
            {"enabled": True, "connected": True},
        ]
        engine._interface_status = lambda: statuses.pop(0)

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            engine.reconcile()

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            engine.reconcile()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Wi-Fi hotspot connected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            engine.reconcile()

    def test_disconnect_logs_once_when_iphone_upstream_lost(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        states = [(USB_UPSTREAM, []), (None, ["waiting"]), (None, ["waiting"])]
        engine.upstream.resolve = lambda *_a, **_k: states.pop(0)

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            engine.reconcile()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["iPhone USB device connected"],
        )

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            engine.reconcile()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Mobile upstream disconnected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            engine.reconcile()

    def test_disconnect_logs_once_when_wifi_disassociates(self) -> None:
        engine = self._engine(
            mobile_connection=WIFI_HOTSPOT,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        statuses = [
            {"enabled": True, "connected": True},
            {"enabled": True, "connected": False},
            {"enabled": True, "connected": False},
        ]
        engine._interface_status = lambda: statuses.pop(0)

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            engine.reconcile()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Wi-Fi hotspot connected"],
        )

        with self.assertLogs(lifecycle.__name__, level="INFO") as captured:
            engine.reconcile()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Mobile upstream disconnected"],
        )

        with self.assertNoLogs(lifecycle.__name__, level="INFO"):
            engine.reconcile()


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from rootfs.app.gateway import GatewayEngine
from rootfs.app.management import ManagementBaseline
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class GatewayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.json"
        self.runner = FakeRunner()
        values = sysctl_values()
        self.engine = build_engine(
            make_config(),
            runner=self.runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        self.engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _restart_waiting_engine(self) -> GatewayEngine:
        values = sysctl_values()
        restarted = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        restarted.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        restarted.safety.errors = lambda *args, **kwargs: [
            "Upstream interface is unavailable"
        ]
        return restarted

    def _prepare_active_engine(self) -> GatewayEngine:
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
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: []
        engine.management = ManagementBaseline("end0", "192.168.1.2/24")
        engine.lifecycle_state.management_interface = "end0"
        engine.runner.networkmanager.nm_wifi_cache["wlan0"] = {"Phone"}
        engine.upstream_lifecycle.activate(engine.management)
        engine._persist_state()
        engine.firewall.installed = lambda downstream=None, upstream_interface=None: (
            engine.lifecycle_state.applied
        )
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )
        return engine

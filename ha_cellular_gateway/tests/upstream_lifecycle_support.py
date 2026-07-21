from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rootfs.app.gateway import GatewayEngine
from rootfs.app.management import ManagementBaseline
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner


def genuine_profile() -> dict[str, str]:
    return {
        "connection.uuid": "A-D074",
        "connection.id": "A-D074",
        "connection.type": "802-11-wireless",
        "connection.interface-name": "wlan0",
        "ipv4.addresses": "",
    }


class UpstreamLifecycleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _engine(self, **overrides: object) -> GatewayEngine:
        runner = FakeRunner()
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
            **overrides,
        )
        return build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )

    @staticmethod
    def _management() -> ManagementBaseline:
        return ManagementBaseline("end0", "192.168.1.2/24")

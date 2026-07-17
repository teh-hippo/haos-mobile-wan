import tempfile
import unittest
from pathlib import Path

from rootfs.app.gateway import GatewayEngine
from rootfs.app.management import ManagementBaseline

from helpers import FakeRunner, make_config, sysctl_values


class SafetyManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runner = FakeRunner()
        values = sysctl_values()
        self.engine = GatewayEngine(
            make_config(),
            runner=self.runner,
            read_text=lambda path: values[path],
            state_path=Path(self.directory.name) / "state.json",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_missing_baseline_reports_management_unavailable(self) -> None:
        errors = self.engine.safety.errors(
            "enx001122334455",
            management=None,
            upstream=None,
        )
        self.assertIn("Management interface is unavailable", errors)

    def test_present_baseline_passes_management_checks(self) -> None:
        baseline = ManagementBaseline("end0", "192.168.1.2/24")

        errors = self.engine.safety.errors(
            "enx001122334455",
            management=baseline,
            upstream=None,
        )

        self.assertNotIn("Management interface is unavailable", errors)
        self.assertNotIn(
            "Management interface/address baseline does not match",
            errors,
        )
        self.assertNotIn(
            "Management interface is not the main default route",
            errors,
        )

    def test_stale_baseline_address_reports_mismatch(self) -> None:
        baseline = ManagementBaseline("end0", "192.168.1.9/24")

        errors = self.engine.safety.errors(
            "enx001122334455",
            management=baseline,
            upstream=None,
        )

        self.assertIn(
            "Management interface/address baseline does not match",
            errors,
        )

    def test_downstream_must_differ_from_management(self) -> None:
        baseline = ManagementBaseline("enx001122334455", "192.168.1.2/24")

        errors = self.engine.safety.errors(
            "enx001122334455",
            management=baseline,
            upstream=None,
        )

        self.assertIn(
            "Downstream NIC must differ from management and upstream interfaces",
            errors,
        )


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import FakeProcess, FakeRunner, make_config
from rootfs.app.dhcp import DnsmasqService
from rootfs.app.errors import GatewayError


class DnsmasqServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.runner = FakeRunner()
        self.popen_args: list[str] = []

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _service(self, process: FakeProcess) -> DnsmasqService:
        return DnsmasqService(
            make_config(),
            lambda *args, **kwargs: self.runner.run(list(args), **kwargs),
            run_dir=self.root / "run",
            lease_path=self.root / "leases",
            popen=lambda args, **kwargs: self.popen_args.extend(args) or process,
        )

    def test_running_process_is_retained(self) -> None:
        process = FakeProcess()
        service = self._service(process)

        service.start("eth0")

        self.assertTrue(service.running)
        config = (self.root / "run" / "dnsmasq.conf").read_text(encoding="utf-8")
        self.assertIn("log-facility=-\n", config)
        self.assertIn("--no-daemon", self.popen_args)

    def test_early_exit_is_reported(self) -> None:
        process = FakeProcess(running=False, returncode=2)
        service = self._service(process)

        with self.assertRaisesRegex(
            GatewayError,
            "Router DHCP service exited with status 2",
        ):
            service.start("eth0")

        self.assertIsNone(service.process)

    def test_wait_timeout_is_not_hidden(self) -> None:
        class BrokenProcess(FakeProcess):
            def wait(self, timeout: int = 5) -> int:
                raise subprocess.SubprocessError("wait failed")

        service = self._service(BrokenProcess())

        with self.assertRaisesRegex(subprocess.SubprocessError, "wait failed"):
            service.start("eth0")


if __name__ == "__main__":
    unittest.main()

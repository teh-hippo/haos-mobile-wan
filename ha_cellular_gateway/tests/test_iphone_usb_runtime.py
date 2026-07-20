"""Direct unit tests for IPhoneUsbRuntime's low-level process, pairing, and
USB-detection helpers (independent of the higher-level IPhoneUsbUpstream
orchestration already covered by test_iphone_usb_pairing.py).
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rootfs.app.errors import GatewayError
from rootfs.app.upstream_iphone_runtime import IPhoneUsbRuntime
from test_support.process import FakeProcess, Result


class IPhoneUsbRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _runtime(
        self,
        *,
        run=None,
        popen=None,
        which=None,
        usb_root: Path | None = None,
        sys_usb_root: Path | None = None,
    ) -> IPhoneUsbRuntime:
        return IPhoneUsbRuntime(
            run or (lambda *args, **kwargs: Result()),
            run_dir=self.root / "run",
            lockdown_dir=self.root / "lockdown",
            usb_root=usb_root if usb_root is not None else self.root / "usb",
            sys_net_root=self.root / "sys_net",
            sys_usb_root=(
                sys_usb_root if sys_usb_root is not None else self.root / "sys_usb"
            ),
            popen=popen,
            which=which or (lambda command: f"/usr/bin/{command}"),
        )

    def test_capability_errors_reports_missing_usb_root(self) -> None:
        runtime = self._runtime()

        errors = runtime.capability_errors()

        self.assertEqual(
            errors,
            ["USB device access is unavailable; enable the app usb permission"],
        )

    def test_ensure_usbmuxd_raises_with_generic_detail_when_log_is_empty(
        self,
    ) -> None:
        runtime = self._runtime(popen=lambda *a, **k: FakeProcess(running=False))

        with self.assertRaises(GatewayError) as excinfo:
            runtime.ensure_usbmuxd()

        self.assertIn("process exited immediately", str(excinfo.exception))

    def test_connected_udids_returns_empty_on_command_failure(self) -> None:
        runtime = self._runtime(
            run=lambda *a, **k: Result(returncode=1, stdout="udid-1\n")
        )

        self.assertEqual(runtime.connected_udids(), [])

    def test_validate_pairing_failure_does_not_clear_retry_state(self) -> None:
        def run(*args: object, **kwargs: object) -> Result:
            if args[:2] == ("idevicepair", "list"):
                return Result(stdout="phone-udid\n")
            return Result(returncode=1)

        runtime = self._runtime(run=run)
        sentinel = ("phone-udid", 1.0, None)
        runtime.pairing_retry = sentinel  # type: ignore[assignment]

        self.assertFalse(runtime.validate_pairing("phone-udid"))
        self.assertEqual(runtime.pairing_retry, sentinel)

    def test_pair_device_returns_paired_result_on_success(self) -> None:
        runtime = self._runtime(run=lambda *a, **k: Result(returncode=0))
        # A stale retry entry (well past the cooldown) must not short-circuit
        # a fresh pairing attempt, and must be cleared once pairing succeeds.
        runtime.pairing_retry = (  # type: ignore[assignment]
            "phone-udid",
            time.monotonic() - 1000.0,
            None,
        )

        result = runtime.pair_device("phone-udid")

        self.assertTrue(result.paired)
        self.assertEqual(result.state, "paired")
        self.assertIsNone(runtime.pairing_retry)

    def test_pairing_error_reports_waiting_for_unlock_on_passcode_prompt(
        self,
    ) -> None:
        runtime = self._runtime(
            run=lambda *a, **k: Result(returncode=1, stderr="Enter passcode on device")
        )

        result = runtime.pair_device("phone-udid")

        self.assertFalse(result.paired)
        self.assertEqual(result.state, "waiting_for_unlock")

    def test_pairing_error_reports_generic_failure_for_unknown_text(self) -> None:
        runtime = self._runtime(
            run=lambda *a, **k: Result(
                returncode=1, stderr="unexpected libimobiledevice error"
            )
        )

        result = runtime.pair_device("phone-udid")

        self.assertFalse(result.paired)
        self.assertEqual(result.state, "pairing_failed")

    def test_apple_usb_present_is_false_when_sys_usb_root_missing(self) -> None:
        runtime = self._runtime(sys_usb_root=self.root / "absent_sys_usb")

        self.assertFalse(runtime.apple_usb_present())

    def test_apple_usb_present_skips_a_device_with_an_unreadable_vendor_file(
        self,
    ) -> None:
        sys_usb_root = self.root / "sys_usb"
        # A device directory whose idVendor cannot be read as text (a
        # directory rather than a file) must be skipped, not fail the scan.
        (sys_usb_root / "1-1" / "idVendor").mkdir(parents=True)
        runtime = self._runtime(sys_usb_root=sys_usb_root)

        self.assertFalse(runtime.apple_usb_present())

    def test_apple_usb_present_continues_past_a_non_apple_vendor(self) -> None:
        sys_usb_root = self.root / "sys_usb"
        (sys_usb_root / "1-2").mkdir(parents=True)
        (sys_usb_root / "1-2" / "idVendor").write_text("1234\n", encoding="utf-8")
        runtime = self._runtime(sys_usb_root=sys_usb_root)

        self.assertFalse(runtime.apple_usb_present())


if __name__ == "__main__":
    unittest.main()

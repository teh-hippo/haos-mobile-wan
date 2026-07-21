from __future__ import annotations

import subprocess
import unittest
from typing import Any

from rootfs.app.command import CommandRunner, run_json_table, stop_process
from test_support.process import FakeProcess, Result


class RunJsonTableTests(unittest.TestCase):
    def test_returns_parsed_json_on_success(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            return Result(returncode=0, stdout='[{"dst": "0.0.0.0/0"}]')

        self.assertEqual(
            run_json_table(_run, "ip", "-j", "route", "show", "table", "220"),
            [{"dst": "0.0.0.0/0"}],
        )

    def test_empty_stdout_on_success_is_treated_as_empty_list(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            return Result(returncode=0, stdout="")

        self.assertEqual(run_json_table(_run, "ip", "-j", "route", "show"), [])

    def test_missing_fib_table_is_swallowed_to_empty_list(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            return Result(
                returncode=1,
                stderr="Error: ipv4: FIB table does not exist.\nDump terminated\n",
            )

        self.assertEqual(
            run_json_table(_run, "ip", "-j", "route", "show", "table", "220"), []
        )

    def test_other_failure_raises_called_process_error_with_output(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            return Result(returncode=2, stdout="partial", stderr="boom")

        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            run_json_table(_run, "ip", "-j", "route", "show", "table", "220")

        self.assertEqual(ctx.exception.returncode, 2)
        self.assertEqual(ctx.exception.output, "partial")
        self.assertEqual(ctx.exception.stderr, "boom")
        self.assertEqual(
            ctx.exception.cmd, ("ip", "-j", "route", "show", "table", "220")
        )


class StopProcessTests(unittest.TestCase):
    def test_none_process_is_a_no_op(self) -> None:
        stop_process(None)

    def test_already_exited_process_is_left_alone(self) -> None:
        process = FakeProcess(running=False, returncode=0)

        stop_process(process)

        self.assertEqual(process.terminate_calls, 0)
        self.assertEqual(process.kill_calls, 0)

    def test_running_process_is_terminated_gracefully(self) -> None:
        process = FakeProcess(running=True)

        stop_process(process)

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 0)
        self.assertFalse(process.running)

    def test_process_ignoring_terminate_is_killed_after_wait_timeout(self) -> None:
        process = FakeProcess(running=True, ignore_terminate=True)

        stop_process(process)

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertFalse(process.running)


class CommandRunnerTests(unittest.TestCase):
    def test_run_executes_a_real_subprocess_and_captures_output(self) -> None:
        result = CommandRunner().run(["echo", "hello"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")

    def test_run_raises_on_non_zero_exit_when_checked(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            CommandRunner().run(["false"])

    def test_run_does_not_raise_on_non_zero_exit_when_unchecked(self) -> None:
        result = CommandRunner().run(["false"], check=False)

        self.assertNotEqual(result.returncode, 0)

    def test_run_raises_timeout_expired_when_command_is_too_slow(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            CommandRunner().run(["sleep", "5"], timeout=1)


if __name__ == "__main__":
    unittest.main()

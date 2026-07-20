"""Behavioural tests for the fail-closed and run-loop lifecycle in
:mod:`rootfs.app.gateway_runtime`.
"""

from __future__ import annotations

import unittest
from unittest import mock

from gateway_support import GatewayTestCase
from rootfs.app.errors import GatewayError


class FailClosedTests(GatewayTestCase):
    def test_clean_cleanup_records_only_the_triggering_error(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(engine.lifecycle_state.applied)

        engine._fail_closed(GatewayError("upstream vanished"))

        self.assertFalse(engine.lifecycle_state.applied)
        self.assertIsNone(engine.selection_state.active_connection)
        self.assertEqual(engine.lifecycle_state.last_error, "upstream vanished")
        self.assertEqual(engine.selection_state.safety_errors, ["upstream vanished"])

    def test_cleanup_failure_is_appended_to_the_triggering_error(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        def fail_cleanup(**_kwargs: object) -> None:
            raise GatewayError("host cleanup failed")

        engine.cleanup = fail_cleanup

        engine._fail_closed(GatewayError("upstream vanished"))

        self.assertEqual(
            engine.lifecycle_state.last_error,
            "upstream vanished; cleanup failed: host cleanup failed",
        )
        self.assertEqual(
            engine.selection_state.safety_errors,
            [engine.lifecycle_state.last_error],
        )

    def test_lifecycle_error_is_appended_after_deactivation(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        engine.upstream_lifecycle.deactivate = lambda management: None
        engine.upstream_lifecycle.error = "profile deletion blocked"

        engine._fail_closed(GatewayError("upstream vanished"))

        self.assertEqual(
            engine.lifecycle_state.last_error,
            "upstream vanished; profile deletion blocked",
        )
        self.assertEqual(
            engine.selection_state.safety_errors,
            [engine.lifecycle_state.last_error],
        )

    def test_cleanup_failure_and_lifecycle_error_are_both_appended(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        def fail_cleanup(**_kwargs: object) -> None:
            raise GatewayError("host cleanup failed")

        engine.cleanup = fail_cleanup
        engine.upstream_lifecycle.deactivate = lambda management: None
        engine.upstream_lifecycle.error = "profile deletion blocked"

        engine._fail_closed(GatewayError("upstream vanished"))

        self.assertEqual(
            engine.lifecycle_state.last_error,
            "upstream vanished; cleanup failed: host cleanup failed; "
            "profile deletion blocked",
        )


class RunLoopTests(GatewayTestCase):
    def test_reconcile_exception_is_routed_through_fail_closed_then_stops(
        self,
    ) -> None:
        engine = self.engine
        triggering_error = GatewayError("reconcile boom")
        engine.reconcile = mock.Mock(side_effect=triggering_error)
        fail_closed_calls: list[Exception] = []

        def fake_fail_closed(err: Exception) -> None:
            fail_closed_calls.append(err)
            engine.stop_event.set()

        engine._fail_closed = fake_fail_closed
        engine.auto_disable.reconcile = mock.Mock(
            side_effect=AssertionError(
                "auto_disable.reconcile must not run after a fail-closed stop"
            )
        )

        engine.run_loop()

        self.assertEqual(fail_closed_calls, [triggering_error])

    def test_normal_iteration_runs_auto_disable_then_stops_via_wait(self) -> None:
        engine = self.engine
        engine.reconcile = mock.Mock()
        auto_disable_calls = []

        def fake_auto_disable_reconcile(eng: object) -> None:
            auto_disable_calls.append(eng)
            engine.stop_event.set()

        engine.auto_disable.reconcile = fake_auto_disable_reconcile

        engine.run_loop()

        engine.reconcile.assert_called_once_with(refresh_health=True)
        self.assertEqual(auto_disable_calls, [engine])

    def test_run_loop_exits_immediately_when_already_stopped(self) -> None:
        engine = self.engine
        engine.reconcile = mock.Mock()
        engine.stop_event.set()

        engine.run_loop()

        engine.reconcile.assert_not_called()

    def test_loop_continues_when_wait_times_out_then_stops_on_next_pass(
        self,
    ) -> None:
        engine = self.engine
        engine.reconcile = mock.Mock()
        auto_disable_calls: list[object] = []
        engine.auto_disable.reconcile = auto_disable_calls.append
        wait_calls: list[float] = []

        def fake_wait(timeout: float) -> bool:
            wait_calls.append(timeout)
            if len(wait_calls) >= 2:
                engine.stop_event.set()
                return True
            return False

        engine.stop_event.wait = fake_wait

        engine.run_loop()

        self.assertEqual(engine.reconcile.call_count, 2)
        self.assertEqual(auto_disable_calls, [engine, engine])
        self.assertEqual(
            wait_calls,
            [engine.config.reconcile_seconds, engine.config.reconcile_seconds],
        )


if __name__ == "__main__":
    unittest.main()

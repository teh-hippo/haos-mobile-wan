from __future__ import annotations

import threading
import unittest

from rootfs.app.auto_disable import RETRY_SECONDS, AutoDisable
from test_support.engine_fixtures import make_config


class FakeLifecycle:
    def __init__(self) -> None:
        self.error: str | None = None
        self.deactivate_calls = 0

    def deactivate(self, management_interface) -> None:
        self.deactivate_calls += 1


class FakeLifecycleState:
    def __init__(self) -> None:
        self.applied = False


class FakeEngine:
    gateway_error = RuntimeError

    def __init__(self, events: list[str] | None = None) -> None:
        self.operation_lock = threading.RLock()
        self.lifecycle_state = FakeLifecycleState()
        self.management = None
        self.upstream_lifecycle = FakeLifecycle()
        self.persist_calls = 0
        self.cleanup_calls = 0
        self.cleanup_raises: Exception | None = None
        self.persist_error: Exception | None = None
        self.events = events if events is not None else []

    def _persist_state(self) -> None:
        self.persist_calls += 1
        if self.persist_error is not None:
            raise self.persist_error

    def cleanup(self, *, preserve_host_protection: bool = False) -> None:
        self.cleanup_calls += 1
        self.events.append("cleanup")
        if self.cleanup_raises is not None:
            raise self.cleanup_raises


class AutoDisableTests(unittest.TestCase):
    def _controller(
        self,
        now: list[float],
        *,
        minutes: int = 30,
        stop_requester=None,
    ) -> AutoDisable:
        return AutoDisable(
            make_config(auto_disable_minutes=minutes),
            clock=lambda: now[0],
            stop_requester=stop_requester or (lambda: None),
        )

    def _expire(
        self, controller: AutoDisable, engine: FakeEngine, now: list[float]
    ) -> None:
        controller.reconcile(engine)
        now[0] = (controller.deadline or now[0]) + 1
        controller.reconcile(engine)

    def test_waiting_starts_fixed_deadline_and_applied_clears_it(self) -> None:
        now = [100.0]
        controller = self._controller(now)
        engine = FakeEngine()

        controller.reconcile(engine)
        first_deadline = controller.deadline
        now[0] += 30
        controller.reconcile(engine)

        self.assertEqual(first_deadline, 1900.0)
        self.assertEqual(controller.deadline, first_deadline)
        engine.lifecycle_state.applied = True
        controller.reconcile(engine)
        self.assertIsNone(controller.deadline)
        self.assertFalse(controller.pending)
        self.assertEqual(engine.cleanup_calls, 0)

    def test_zero_timeout_never_starts_countdown(self) -> None:
        now = [100.0]
        controller = self._controller(now, minutes=0)
        engine = FakeEngine()

        controller.reconcile(engine)

        self.assertIsNone(controller.deadline)
        self.assertFalse(controller.pending)

    def test_expiry_releases_before_requesting_stop(self) -> None:
        now = [100.0]
        events: list[str] = []
        engine = FakeEngine(events)
        controller = self._controller(
            now,
            stop_requester=lambda: events.append("stop") or None,
        )

        self._expire(controller, engine, now)

        self.assertTrue(controller.pending)
        self.assertIsNone(controller.deadline)
        self.assertEqual(engine.cleanup_calls, 1)
        self.assertEqual(engine.upstream_lifecycle.deactivate_calls, 1)
        self.assertEqual(events, ["cleanup", "stop"])
        self.assertIsNone(controller.error)

    def test_no_option_writer_is_involved(self) -> None:
        controller = self._controller([100.0])
        self.assertFalse(hasattr(controller, "write_enabled"))
        self.assertFalse(hasattr(controller, "read_current_options"))

    def test_stop_request_failure_surfaces_and_rate_limits_retry(self) -> None:
        now = [100.0]
        attempts: list[float] = []
        engine = FakeEngine()
        controller = self._controller(
            now,
            stop_requester=lambda: (
                attempts.append(now[0]),
                "Supervisor token is unavailable",
            )[1],
        )

        self._expire(controller, engine, now)

        self.assertTrue(controller.pending)
        self.assertEqual(len(attempts), 1)
        self.assertIn("Auto-stop request failed", controller.error or "")

        controller.reconcile(engine)
        self.assertEqual(len(attempts), 1)

        now[0] += RETRY_SECONDS
        controller.reconcile(engine)
        self.assertEqual(len(attempts), 2)

    def test_cleanup_failure_retries_without_requesting_stop(self) -> None:
        now = [100.0]
        events: list[str] = []
        engine = FakeEngine(events)
        engine.cleanup_raises = RuntimeError("still dirty")
        controller = self._controller(
            now,
            stop_requester=lambda: events.append("stop") or None,
        )

        self._expire(controller, engine, now)

        self.assertTrue(controller.pending)
        self.assertEqual(events, ["cleanup"])
        self.assertIn("cleanup failed", controller.error or "")

        controller.reconcile(engine)
        self.assertEqual(events, ["cleanup", "cleanup"])
        self.assertNotIn("stop", events)

    def test_upstream_release_failure_blocks_stop(self) -> None:
        now = [100.0]
        events: list[str] = []
        engine = FakeEngine(events)
        engine.upstream_lifecycle.error = "wifi restoration pending"
        controller = self._controller(
            now,
            stop_requester=lambda: events.append("stop") or None,
        )

        self._expire(controller, engine, now)

        self.assertTrue(controller.pending)
        self.assertNotIn("stop", events)
        self.assertEqual(controller.error, "wifi restoration pending")

    def test_pending_never_reactivates_even_when_applied(self) -> None:
        now = [100.0]
        engine = FakeEngine()
        controller = self._controller(now)

        self._expire(controller, engine, now)
        self.assertTrue(controller.pending)

        engine.lifecycle_state.applied = True
        controller.reconcile(engine)

        self.assertTrue(controller.pending)
        self.assertIsNone(controller.deadline)

    def test_later_manual_start_gets_a_fresh_timer(self) -> None:
        now = [100.0]
        first = self._controller(now)
        self._expire(first, FakeEngine(), now)
        self.assertTrue(first.pending)

        restarted = self._controller([100.0])

        self.assertFalse(restarted.pending)
        self.assertIsNone(restarted.deadline)
        restarted.reconcile(FakeEngine())
        self.assertEqual(restarted.deadline, 1900.0)


if __name__ == "__main__":
    unittest.main()

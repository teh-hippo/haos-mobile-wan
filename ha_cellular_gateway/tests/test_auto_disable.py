from __future__ import annotations

import threading
import unittest

from helpers import make_config
from rootfs.app.auto_disable import AutoDisable, RETRY_SECONDS


class FakeLifecycle:
    def __init__(self) -> None:
        self.error: str | None = None
        self.deactivate_calls = 0

    def deactivate(self, management_interface) -> None:
        self.deactivate_calls += 1


class FakeEngine:
    gateway_error = RuntimeError

    def __init__(self) -> None:
        self.operation_lock = threading.RLock()
        self.enabled = True
        self.applied = False
        self.management = None
        self.upstream_lifecycle = FakeLifecycle()
        self.persist_calls = 0
        self.cleanup_calls = 0

    def _persist_state(self) -> None:
        self.persist_calls += 1

    def cleanup(self, *, preserve_host_protection=False) -> None:
        self.cleanup_calls += 1
        self.enabled = False
        self.applied = False


class AutoDisableTests(unittest.TestCase):
    def _controller(
        self,
        now: list[float],
        *,
        minutes: int = 30,
        state: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
        writer=None,
    ) -> AutoDisable:
        current = options if options is not None else {"enabled": True}
        return AutoDisable(
            make_config(enabled=True, auto_disable_minutes=minutes),
            state or {},
            clock=lambda: now[0],
            write_enabled=writer or (lambda enabled: None),
            read_current_options=lambda: dict(current),
        )

    def test_waiting_starts_fixed_deadline_and_connection_clears_it(self) -> None:
        now = [100.0]
        controller = self._controller(now)
        engine = FakeEngine()

        controller.reconcile(engine)
        first_deadline = controller.deadline
        now[0] += 30
        controller.reconcile(engine)

        self.assertEqual(first_deadline, 1900.0)
        self.assertEqual(controller.deadline, first_deadline)
        engine.applied = True
        controller.reconcile(engine)
        self.assertIsNone(controller.deadline)

    def test_expiry_latches_and_disables_runtime(self) -> None:
        now = [200.0]
        writes: list[bool] = []
        controller = self._controller(
            now,
            state={"auto_disable": {"deadline": 100.0}},
            writer=lambda enabled: writes.append(enabled) or None,
        )
        engine = FakeEngine()

        controller.reconcile(engine)

        self.assertTrue(controller.pending)
        self.assertFalse(engine.enabled)
        self.assertEqual(engine.cleanup_calls, 1)
        self.assertEqual(engine.upstream_lifecycle.deactivate_calls, 1)
        self.assertEqual(writes, [False])

    def test_reflected_disabled_option_clears_latch(self) -> None:
        now = [200.0]
        controller = self._controller(
            now,
            state={"auto_disable": {"pending": True}},
            options={"enabled": False},
        )
        engine = FakeEngine()

        controller.reconcile(engine)

        self.assertFalse(controller.pending)
        self.assertIsNone(controller.error)

    def test_failed_option_write_is_retained_and_rate_limited(self) -> None:
        now = [200.0]
        writes: list[bool] = []
        controller = self._controller(
            now,
            state={"auto_disable": {"pending": True}},
            writer=lambda enabled: writes.append(enabled) or "write failed",
        )
        engine = FakeEngine()

        controller.reconcile(engine)
        controller.reconcile(engine)
        now[0] += RETRY_SECONDS
        controller.reconcile(engine)

        self.assertEqual(writes, [False, False])
        self.assertEqual(controller.error, "write failed")
        self.assertTrue(controller.pending)

    def test_zero_timeout_never_starts_countdown(self) -> None:
        now = [100.0]
        controller = self._controller(now, minutes=0)
        engine = FakeEngine()

        controller.reconcile(engine)

        self.assertIsNone(controller.deadline)
        self.assertFalse(controller.pending)

    def test_deadline_and_pending_state_survive_restart(self) -> None:
        now = [100.0]
        first = self._controller(now)
        first.reconcile(FakeEngine())
        persisted = first.state()
        assert persisted is not None

        restarted = self._controller(
            now,
            state={"auto_disable": persisted},
        )

        self.assertEqual(restarted.deadline, first.deadline)
        self.assertEqual(restarted.deadline_iso, "1970-01-01T00:31:40+00:00")

    def test_invalid_persistent_state_fails_closed(self) -> None:
        now = [100.0]
        controller = self._controller(
            now,
            state={"auto_disable": {"deadline": "bad"}},
        )

        self.assertTrue(controller.latched)
        self.assertIn("invalid", controller.error or "")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import time
import unittest
from pathlib import Path

from rootfs.app.errors import GatewayError, SafetyError
from rootfs.app.gateway import GatewayEngine

from helpers import (
    FakeProcess,
    FakeRunner,
    install_realistic_firewall_state,
    make_config,
    prepend_chain_rule,
    sysctl_values,
)


class GatewayEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.json"
        self.runner = FakeRunner()
        values = sysctl_values()
        self.engine = GatewayEngine(
            make_config(),
            runner=self.runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        self.engine.safety.find_downstream = lambda: "enx001122334455"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _prepare_active_engine(self, mode: str = "active") -> GatewayEngine:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(mode=mode, dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda: "enx001122334455"
        engine.safety.errors = lambda downstream=None, state_error=None: []
        engine.firewall.installed = lambda downstream=None: engine.applied
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )
        return engine

    def test_dry_run_refuses_mutation(self) -> None:
        with self.assertRaisesRegex(SafetyError, "dry_run"):
            self.engine.apply("trial")

    def test_fresh_dry_run_reconcile_does_not_mutate_host(self) -> None:
        self.engine.reconcile()
        mutating_commands = [
            command
            for command in self.runner.commands
            if (
                command[:3]
                in (
                    ["ip", "rule", "del"],
                    ["ip", "route", "del"],
                )
                or (
                    command[0] in {"iptables", "ip6tables"}
                    and any(
                        operation in command
                        for operation in ("-A", "-D", "-I", "-N", "-F", "-X")
                    )
                )
            )
        ]
        self.assertEqual(mutating_commands, [])

    def test_status_uses_cached_health(self) -> None:
        self.engine.upstream_healthy = True
        self.engine.public_ip = "203.0.113.10"
        before = len(self.runner.commands)
        status = self.engine.status()
        self.assertEqual(len(self.runner.commands), before)
        self.assertTrue(status["upstream_healthy"])
        self.assertEqual(status["public_ip"], "203.0.113.10")

    def test_manual_reconcile_does_not_run_external_health_probe(self) -> None:
        self.engine.startup_cleanup_pending = False
        self.engine.safety.errors = lambda downstream=None, state_error=None: []
        self.engine.reconcile()
        self.assertFalse(
            any(command and command[0] == "curl" for command in self.runner.commands)
        )

    def test_active_mode_recovers_after_transient_safety_failure(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        self.assertEqual(engine.mode, "active")

        engine.safety.errors = (
            lambda downstream=None, state_error=None: ["Upstream unavailable"]
        )
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertEqual(engine.mode, "disabled")
        self.assertEqual(engine.desired_mode, "active")

        engine.safety.errors = lambda downstream=None, state_error=None: []
        engine.reconcile()
        self.assertEqual(engine.mode, "active")
        self.assertTrue(engine.applied)

    def test_activation_failure_is_cleaned_and_retried(self) -> None:
        engine = self._prepare_active_engine()

        def fail_firewall(downstream: str) -> None:
            raise OSError("firewall unavailable")

        engine.firewall.apply = fail_firewall
        with self.assertRaisesRegex(GatewayError, "Activation failed"):
            engine.apply("active")
        self.assertEqual(engine.mode, "disabled")
        self.assertEqual(engine.desired_mode, "active")

        engine.firewall.apply = lambda downstream: None
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertEqual(engine.mode, "active")

    def test_active_mode_reapplies_when_policy_state_is_missing(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        before = len(engine.runner.commands)

        engine.startup_cleanup_pending = False
        engine.policy.installed = lambda downstream: False
        engine.firewall.installed = lambda downstream=None: True
        engine.reconcile()

        reapplied = engine.runner.commands[before:]
        self.assertTrue(
            any(command[:3] == ["ip", "rule", "add"] for command in reapplied)
        )
        self.assertTrue(
            any(command[:3] == ["ip", "route", "replace"] for command in reapplied)
        )

    def test_active_mode_reconcile_does_not_reapply_realistic_firewall_state(self) -> None:
        engine = self._prepare_active_engine()
        install_realistic_firewall_state(engine.runner, engine.firewall, "enx001122334455")
        engine.firewall.installed = engine.firewall.__class__.installed.__get__(
            engine.firewall,
            engine.firewall.__class__,
        )
        engine.mode = "active"
        engine.desired_mode = "active"
        engine.applied = True
        engine.startup_cleanup_pending = False
        engine.policy.installed = lambda downstream: True
        engine.dhcp.process = FakeProcess()
        before = len(engine.runner.commands)

        engine.reconcile()

        mutating_commands = [
            command
            for command in engine.runner.commands[before:]
            if (
                command[:3] == ["ip", "rule", "add"]
                or command[:3] == ["ip", "route", "replace"]
                or (
                    command[0] in {"iptables", "ip6tables"}
                    and any(
                        operation in command
                        for operation in ("-A", "-D", "-I", "-N", "-F", "-X")
                    )
                )
            )
        ]
        self.assertEqual(mutating_commands, [])

    def test_disabled_mode_preserves_live_host_protection(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        engine.firewall.netfilter.chain_exists = lambda family, chain: True
        engine.safety.find_downstream = lambda: (_ for _ in ()).throw(
            OSError("adapter probe failed")
        )
        before = len(engine.runner.commands)

        engine.cleanup(preserve_host_protection=True)

        commands = [" ".join(command) for command in engine.runner.commands[before:]]
        self.assertTrue(
            any(command == "iptables -F HA_CELLGW" for command in commands)
        )
        self.assertTrue(
            any(command == "ip6tables -F HA_CELLGW6" for command in commands)
        )
        self.assertFalse(
            any(
                "HA_CELLGW_LOCAL" in command or "HA_CELLGW6_LOCAL" in command
                for command in commands
            )
        )

    def test_disabled_mode_reconcile_does_not_flush_realistic_host_guard(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(mode="disabled", dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda: "enx001122334455"
        engine.safety.errors = lambda downstream=None, state_error=None: []
        install_realistic_firewall_state(
            engine.runner,
            engine.firewall,
            "enx001122334455",
        )
        engine.startup_cleanup_pending = False
        before = len(engine.runner.commands)

        engine.reconcile()

        mutating_commands = [
            command
            for command in engine.runner.commands[before:]
            if command[0] in {"iptables", "ip6tables"} and any(
                operation in command
                for operation in ("-A", "-D", "-I", "-N", "-F", "-X")
            )
        ]
        self.assertEqual(mutating_commands, [])

    def test_disabled_restart_cleanup_preserves_valid_host_guard(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")

        values = sysctl_values()
        restarted = GatewayEngine(
            make_config(mode="disabled", dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        restarted.safety.find_downstream = lambda: "enx001122334455"
        restarted.safety.errors = lambda downstream=None, state_error=None: []
        install_realistic_firewall_state(
            restarted.runner,
            restarted.firewall,
            "enx001122334455",
        )
        before = len(restarted.runner.commands)

        restarted.reconcile()

        guard_mutations = [
            command
            for command in restarted.runner.commands[before:]
            if command[0] in {"iptables", "ip6tables"}
            and any(operation in command for operation in ("-F", "-D", "-X"))
            and any(
                chain in command
                for chain in (
                    "INPUT",
                    restarted.firewall.INPUT_CHAIN,
                    restarted.firewall.INPUT6_CHAIN,
                )
            )
        ]
        self.assertEqual(guard_mutations, [])

    def test_disabled_mode_reconcile_repairs_late_parent_jumps_without_flushing_guard(
        self,
    ) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(mode="disabled", dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda: "enx001122334455"
        engine.safety.errors = lambda downstream=None, state_error=None: []
        install_realistic_firewall_state(
            engine.runner,
            engine.firewall,
            "enx001122334455",
        )
        prepend_chain_rule(engine.runner, "iptables", "INPUT", "-A INPUT -j ACCEPT")
        prepend_chain_rule(engine.runner, "ip6tables", "INPUT", "-A INPUT -j ACCEPT")
        engine.startup_cleanup_pending = False
        before = len(engine.runner.commands)

        engine.reconcile()

        guard_flushes = [
            command
            for command in engine.runner.commands[before:]
            if command[:3] in (
                ["iptables", "-F", engine.firewall.INPUT_CHAIN],
                ["iptables", "-X", engine.firewall.INPUT_CHAIN],
                ["ip6tables", "-F", engine.firewall.INPUT6_CHAIN],
                ["ip6tables", "-X", engine.firewall.INPUT6_CHAIN],
            )
        ]
        self.assertEqual(guard_flushes, [])
        self.assertTrue(
            any(
                command[:4] == ["iptables", "-I", "INPUT", "1"]
                for command in engine.runner.commands[before:]
            )
        )
        self.assertTrue(
            any(
                command[:4] == ["ip6tables", "-I", "INPUT", "1"]
                for command in engine.runner.commands[before:]
            )
        )

    def test_trial_deadline_survives_restart(self) -> None:
        engine = self._prepare_active_engine("trial")
        engine.apply("trial")
        deadline = engine.trial_deadline
        self.assertIsNotNone(deadline)

        values = sysctl_values()
        restarted = GatewayEngine(
            make_config(mode="trial", dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        self.assertEqual(restarted.trial_deadline, deadline)

    def test_expired_trial_rolls_back_after_restart(self) -> None:
        started_at = time.time() - 400
        self.state_path.write_text(
            json.dumps(
                {
                    "trial": {
                        "started_at": started_at,
                        "deadline": started_at + 300,
                    }
                }
            ),
            encoding="utf-8",
        )
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(mode="trial", dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda: "enx001122334455"
        engine.safety.errors = lambda downstream=None, state_error=None: []
        engine.reconcile()
        self.assertEqual(engine.mode, "disabled")
        self.assertEqual(engine.desired_mode, "disabled")
        self.assertIsNone(engine.trial_deadline)

    def test_unexpected_reconcile_error_fails_closed(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        engine.safety.errors = lambda downstream=None, state_error=None: (_ for _ in ()).throw(
            OSError("inspection failed")
        )
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertEqual(engine.mode, "disabled")
        self.assertFalse(engine.applied)
        self.assertIn("Safety inspection failed", engine.last_error)


if __name__ == "__main__":
    unittest.main()

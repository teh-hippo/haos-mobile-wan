import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rootfs.app.errors import GatewayError, SafetyError
from rootfs.app.gateway import GatewayEngine
from rootfs.app.upstream import IPhoneUsbUpstream

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

    def _restart_disabled_engine(self) -> GatewayEngine:
        values = sysctl_values()
        restarted = GatewayEngine(
            make_config(mode="disabled", dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        restarted.safety.find_downstream = lambda: "enx001122334455"
        restarted.safety.errors = lambda *args, **kwargs: []
        return restarted

    def _prepare_active_engine(self, mode: str = "active") -> GatewayEngine:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(mode=mode, dry_run=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: []
        engine.firewall.installed = (
            lambda downstream=None, upstream_interface=None: engine.applied
        )
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )
        return engine

    def _assert_disabled_restart_preserves_repairable_host_guard(
        self,
        ipv4_input_rules: tuple[str, ...],
        ipv6_input_rules: tuple[str, ...],
    ) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")

        restarted = self._restart_disabled_engine()
        install_realistic_firewall_state(
            restarted.runner,
            restarted.firewall,
            "enx001122334455",
        )
        restarted.runner.chain_listings[("iptables", "INPUT")] = "\n".join(
            ipv4_input_rules
        )
        restarted.runner.chain_listings[("ip6tables", "INPUT")] = "\n".join(
            ipv6_input_rules
        )
        before = len(restarted.runner.commands)

        restarted.reconcile()

        commands = restarted.runner.commands[before:]
        guard_mutations = [
            command
            for command in commands
            if command[0] in {"iptables", "ip6tables"}
            and any(operation in command for operation in ("-F", "-X"))
            and any(
                chain in command
                for chain in (
                    restarted.firewall.INPUT_CHAIN,
                    restarted.firewall.INPUT6_CHAIN,
                )
            )
        ]
        self.assertEqual(guard_mutations, [])
        cleanup_hook_deletions = [
            command
            for command in commands
            if command[0] in {"iptables", "ip6tables"}
            and command[1:3] == ["-D", "INPUT"]
            and (len(command) < 4 or not command[3].isdigit())
        ]
        self.assertEqual(cleanup_hook_deletions, [])
        self.assertTrue(
            restarted.firewall.netfilter.rule_is_first_unique(
                "iptables",
                "INPUT",
                restarted.firewall.netfilter.jump_rule(
                    restarted.firewall.INPUT_CHAIN,
                    "ha-cellgw:local-jump",
                    ["-i", "enx001122334455"],
                ),
            )
        )
        self.assertTrue(
            restarted.firewall.netfilter.rule_is_first_unique(
                "ip6tables",
                "INPUT",
                restarted.firewall.netfilter.jump_rule(
                    restarted.firewall.INPUT6_CHAIN,
                    "ha-cellgw:v6-local-jump",
                    ["-i", "enx001122334455"],
                ),
            )
        )

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
        self.engine.safety.errors = lambda *args, **kwargs: []
        self.engine.reconcile()
        self.assertFalse(
            any(command and command[0] == "curl" for command in self.runner.commands)
        )

    def test_active_mode_recovers_after_transient_safety_failure(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        self.assertEqual(engine.mode, "active")

        engine.safety.errors = lambda *args, **kwargs: ["Upstream unavailable"]
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertEqual(engine.mode, "disabled")
        self.assertEqual(engine.desired_mode, "active")

        engine.safety.errors = lambda *args, **kwargs: []
        engine.reconcile()
        self.assertEqual(engine.mode, "active")
        self.assertTrue(engine.applied)

    def test_activation_failure_is_cleaned_and_retried(self) -> None:
        engine = self._prepare_active_engine()

        def fail_firewall(downstream: str, upstream_interface: str | None = None) -> None:
            raise OSError("firewall unavailable")

        engine.firewall.apply = fail_firewall
        with self.assertRaisesRegex(GatewayError, "Activation failed"):
            engine.apply("active")
        self.assertEqual(engine.mode, "disabled")
        self.assertEqual(engine.desired_mode, "active")

        engine.firewall.apply = lambda downstream, upstream_interface=None: None
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertEqual(engine.mode, "active")

    def test_active_mode_reapplies_when_policy_state_is_missing(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        before = len(engine.runner.commands)

        engine.startup_cleanup_pending = False
        engine.policy.installed = lambda downstream, upstream=None: False
        engine.firewall.installed = lambda downstream=None, upstream_interface=None: True
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
        engine.policy.installed = lambda downstream, upstream=None: True
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
        engine.safety.errors = lambda *args, **kwargs: []
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

        restarted = self._restart_disabled_engine()
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

    def test_disabled_restart_preserves_duplicate_first_repairable_host_guard(
        self,
    ) -> None:
        self._assert_disabled_restart_preserves_repairable_host_guard(
            (
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:local-jump -j HA_CELLGW_LOCAL",
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:local-jump -j HA_CELLGW_LOCAL",
            ),
            (
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:v6-local-jump -j HA_CELLGW6_LOCAL",
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:v6-local-jump -j HA_CELLGW6_LOCAL",
            ),
        )

    def test_disabled_restart_preserves_late_repairable_host_guard(self) -> None:
        self._assert_disabled_restart_preserves_repairable_host_guard(
            (
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:local-jump -j HA_CELLGW_LOCAL",
            ),
            (
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:v6-local-jump -j HA_CELLGW6_LOCAL",
            ),
        )

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
        engine.safety.errors = lambda *args, **kwargs: []
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
        engine.safety.errors = lambda *args, **kwargs: []
        engine.reconcile()
        self.assertEqual(engine.mode, "disabled")
        self.assertEqual(engine.desired_mode, "disabled")
        self.assertIsNone(engine.trial_deadline)

    def test_unexpected_reconcile_error_fails_closed(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply("active")
        engine.safety.errors = lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("inspection failed")
        )
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertEqual(engine.mode, "disabled")
        self.assertFalse(engine.applied)
        self.assertIn("Safety inspection failed", engine.last_error)

    def test_status_remains_responsive_during_blocking_upstream_resolution(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(mode="disabled", dry_run=False, upstream_mode="iphone_usb"),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda: "enx001122334455"
        started = threading.Event()
        release = threading.Event()

        def slow_resolve(*, allow_mutation: bool):
            started.set()
            release.wait(timeout=2)
            return None, ["waiting for usb"]

        engine.upstream.resolve = slow_resolve
        worker = threading.Thread(target=engine.reconcile)
        worker.start()
        self.assertTrue(started.wait(timeout=1))

        began = time.time()
        status = engine.status()
        elapsed = time.time() - began

        release.set()
        worker.join(timeout=2)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(status["mode"], "disabled")

    def test_stop_after_dry_run_detected_usb_does_not_flush_external_interface(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        engine = GatewayEngine(
            make_config(upstream_mode="iphone_usb"),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usb_root = root / "dev" / "bus" / "usb"
            sys_net_root = root / "sys" / "class" / "net"
            sys_usb_root = root / "sys" / "bus" / "usb" / "devices"
            driver_root = root / "drivers"
            udhcpc_script = root / "udhcpc.script"
            run_dir = root / "run"
            usb_root.mkdir(parents=True)
            sys_net_root.mkdir(parents=True)
            sys_usb_root.mkdir(parents=True)
            driver_root.mkdir(parents=True)
            udhcpc_script.write_text("#!/bin/sh\n", encoding="utf-8")

            target = driver_root / "ipheth"
            target.mkdir()
            interface = sys_net_root / "eth0" / "device"
            interface.mkdir(parents=True)
            (interface / "driver").symlink_to(target)

            device = sys_usb_root / "1-1"
            device.mkdir(parents=True)
            (device / "idVendor").write_text("05ac\n", encoding="utf-8")

            engine.upstream = IPhoneUsbUpstream(
                engine.config,
                lambda *args, **kwargs: runner.run(list(args), **kwargs),
                run_dir=run_dir,
                lockdown_dir=root / "lockdown",
                usb_root=usb_root,
                sys_net_root=sys_net_root,
                sys_usb_root=sys_usb_root,
                udhcpc_script=udhcpc_script,
                which=lambda command: f"/usr/bin/{command}",
                popen=lambda *args, **kwargs: FakeProcess(),
            )
            resolved, errors = engine.upstream.resolve(allow_mutation=False)
            self.assertEqual(errors, [])
            self.assertIsNotNone(resolved)

            runner.commands.clear()
            engine.stop()

        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "flush"]
                or command[:5] == ["ip", "route", "del", "default", "dev"]
                for command in runner.commands
            )
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from gateway_support import GatewayTestCase
from rootfs.app.const import IPHONE_USB
from rootfs.app.errors import GatewayError
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.firewall_fixtures import (
    install_realistic_firewall_state,
    prepend_chain_rule,
)
from test_support.runner import FakeRunner


class GatewayCleanupHostProtectionTests(GatewayTestCase):
    def _assert_restart_repairs_host_guard(
        self,
        ipv4_input_rules: tuple[str, ...],
        ipv6_input_rules: tuple[str, ...],
    ) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        restarted = self._restart_waiting_engine()
        install_realistic_firewall_state(
            restarted.runner,
            restarted.firewall,
            "enx001122334455",
        )
        restarted.runner.firewall.chain_listings[("iptables", "INPUT")] = "\n".join(
            ipv4_input_rules
        )
        restarted.runner.firewall.chain_listings[("ip6tables", "INPUT")] = "\n".join(
            ipv6_input_rules
        )

        restarted.reconcile()

        self.assertTrue(restarted.firewall.host_protection_installed("enx001122334455"))
        self.assertNotIn(
            "enx001122334455",
            restarted.runner.routes.interface_addresses,
        )

    def test_cleanup_warns_and_continues_when_downstream_discovery_fails(
        self,
    ) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        persisted_ownership = dict(engine.lifecycle_state.owned_state or {})
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            OSError("adapter probe failed")
        )

        with self.assertLogs(
            "rootfs.app.gateway_cleanup",
            level="WARNING",
        ) as captured:
            engine.cleanup()

        messages = "\n".join(captured.output)
        self.assertIn("Downstream discovery failed during cleanup", messages)
        self.assertIn("adapter probe failed", messages)
        self.assertFalse(engine.lifecycle_state.applied)
        self.assertNotIn(
            persisted_ownership["downstream"],
            engine.runner.routes.interface_addresses,
        )

    def test_cleanup_removes_host_protection_when_adapter_probe_fails(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        engine.firewall.netfilter.chain_exists = lambda family, chain: True
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            OSError("adapter probe failed")
        )
        before = len(engine.runner.commands)

        engine.cleanup()

        commands = [" ".join(command) for command in engine.runner.commands[before:]]
        self.assertTrue(any(command == "iptables -F HA_CELLGW" for command in commands))
        self.assertTrue(
            any(command == "ip6tables -F HA_CELLGW6" for command in commands)
        )
        self.assertTrue(
            any(
                "HA_CELLGW_LOCAL" in command or "HA_CELLGW6_LOCAL" in command
                for command in commands
            )
        )
        self.assertNotIn("enx001122334455", engine.runner.routes.interface_addresses)

    def test_cleanup_keeps_host_guard_if_address_removal_fails(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        def fail_address_cleanup(ownership) -> None:
            raise GatewayError("address still present")

        engine.downstream.cleanup = fail_address_cleanup

        with self.assertRaisesRegex(GatewayError, "address still present"):
            engine.cleanup()

        self.assertIsNotNone(engine.lifecycle_state.owned_state)
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))

    def test_usb_cleanup_ignores_unused_invalid_wifi_settings(self) -> None:
        values = sysctl_values()
        config = make_config(
            mobile_connection=IPHONE_USB,
            upstream_address="not-an-address",
            upstream_gateway="not-a-gateway",
        )
        config.validate()
        engine = build_engine(
            config,
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.cleanup()

        self.assertFalse(engine.lifecycle_state.applied)
        self.assertIsNone(engine.lifecycle_state.owned_state)

    def test_waiting_reconcile_preserves_host_guard(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: [
            "Upstream interface is unavailable"
        ]
        install_realistic_firewall_state(
            engine.runner,
            engine.firewall,
            "enx001122334455",
        )
        engine.lifecycle_state.startup_cleanup_pending = False
        before = len(engine.runner.commands)

        engine.reconcile()

        mutating_commands = [
            command
            for command in engine.runner.commands[before:]
            if command[0] in {"iptables", "ip6tables"}
            and any(
                operation in command
                for operation in ("-A", "-D", "-I", "-N", "-F", "-X")
            )
        ]
        self.assertTrue(mutating_commands)
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))
        before = len(engine.runner.commands)

        engine.reconcile()

        repeated_mutations = [
            command
            for command in engine.runner.commands[before:]
            if command[0] in {"iptables", "ip6tables"}
            and any(
                operation in command
                for operation in ("-A", "-D", "-I", "-N", "-F", "-X")
            )
        ]
        self.assertEqual(repeated_mutations, [])

    def test_restart_cleanup_preserves_valid_host_guard(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        restarted = self._restart_waiting_engine()
        install_realistic_firewall_state(
            restarted.runner,
            restarted.firewall,
            "enx001122334455",
        )
        before = len(restarted.runner.commands)

        restarted.reconcile()

        self.assertFalse(
            any(
                command[:3]
                in (
                    ["iptables", "-X", restarted.firewall.INPUT_CHAIN],
                    ["ip6tables", "-X", restarted.firewall.INPUT6_CHAIN],
                )
                for command in restarted.runner.commands[before:]
            )
        )
        self.assertTrue(restarted.firewall.host_protection_installed("enx001122334455"))

    def test_management_loss_preserves_existing_downstream_host_guard(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        engine = build_engine(
            make_config(),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.lifecycle_state.startup_cleanup_pending = False
        install_realistic_firewall_state(
            runner,
            engine.firewall,
            "enx001122334455",
        )
        engine.selection_state.downstream = "enx001122334455"
        runner.routes.main_default_routes = []

        engine.reconcile()

        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))

    def test_restart_repairs_duplicate_host_guard(
        self,
    ) -> None:
        self._assert_restart_repairs_host_guard(
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

    def test_restart_repairs_late_host_guard(self) -> None:
        self._assert_restart_repairs_host_guard(
            (
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:local-jump -j HA_CELLGW_LOCAL",
            ),
            (
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:v6-local-jump -j HA_CELLGW6_LOCAL",
            ),
        )

    def test_waiting_reconcile_repairs_late_parent_jumps(
        self,
    ) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: [
            "Upstream interface is unavailable"
        ]
        install_realistic_firewall_state(
            engine.runner,
            engine.firewall,
            "enx001122334455",
        )
        prepend_chain_rule(engine.runner, "iptables", "INPUT", "-A INPUT -j ACCEPT")
        prepend_chain_rule(engine.runner, "ip6tables", "INPUT", "-A INPUT -j ACCEPT")
        engine.lifecycle_state.startup_cleanup_pending = False
        before = len(engine.runner.commands)

        engine.reconcile()

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
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))


if __name__ == "__main__":
    unittest.main()

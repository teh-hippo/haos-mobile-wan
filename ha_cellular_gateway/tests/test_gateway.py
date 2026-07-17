import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rootfs.app.const import (
    IPHONE_USB,
    IPHONE_USB_WIFI_FALLBACK,
    WIFI_HOTSPOT,
)
from rootfs.app.errors import GatewayError, SafetyError
from rootfs.app.gateway import GatewayEngine
from rootfs.app.hotspot import WIFI_ADAPTER_DISABLED, WIFI_NOT_ASSOCIATED
from rootfs.app.management import ManagementBaseline
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from rootfs.app.upstream_models import ResolvedUpstream

from helpers import (
    FakeProcess,
    FakeRunner,
    install_realistic_firewall_state,
    install_realistic_policy_state,
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
        self.engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _restart_disabled_engine(self) -> GatewayEngine:
        values = sysctl_values()
        restarted = GatewayEngine(
            make_config(enabled=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        restarted.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        restarted.safety.errors = lambda *args, **kwargs: []
        return restarted

    def _prepare_active_engine(self, enabled: bool = True) -> GatewayEngine:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=enabled),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
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

    def _assert_disabled_restart_repairs_host_guard(
        self,
        ipv4_input_rules: tuple[str, ...],
        ipv6_input_rules: tuple[str, ...],
    ) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

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
        self.assertTrue(
            restarted.firewall.host_protection_installed(
                "enx001122334455"
            )
        )
        self.assertNotIn(
            "enx001122334455",
            restarted.runner.interface_addresses,
        )

    def test_disabled_reconcile_does_not_activate_gateway(self) -> None:
        self.engine.safety.errors = lambda *args, **kwargs: []
        self.engine.reconcile()
        self.assertFalse(self.engine.enabled)
        self.assertFalse(self.engine.applied)
        self.assertFalse(self.engine.dhcp.running)
        self.assertNotIn(
            "enx001122334455",
            self.runner.interface_addresses,
        )
        self.assertFalse(
            any(
                command[:3] in (["ip", "rule", "add"], ["ip", "route", "replace"])
                for command in self.runner.commands
            )
        )
        self.assertTrue(
            self.engine.firewall.host_protection_installed(
                "enx001122334455"
            )
        )

    def test_config_error_still_cleans_owned_host_state(self) -> None:
        active = self._prepare_active_engine()
        active.apply()
        values = sysctl_values()
        degraded = GatewayEngine(
            make_config(enabled=True),
            runner=active.runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        degraded.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )
        degraded.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream preparation must stay blocked")
        )

        degraded.reconcile()

        self.assertFalse(degraded.enabled)
        self.assertIsNone(degraded.owned_state)
        self.assertNotIn(
            "enx001122334455",
            degraded.runner.interface_addresses,
        )
        self.assertFalse(
            degraded.firewall.host_protection_installed(
                "enx001122334455"
            )
        )
        self.assertIn("Invalid app configuration", degraded.last_error)

    def test_config_error_without_owned_state_does_not_mutate_host(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=True),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream preparation must stay blocked")
        )

        engine.reconcile()

        self.assertFalse(engine.enabled)
        self.assertFalse(engine.applied)
        self.assertIsNone(engine.last_downstream)
        self.assertIn("Invalid app configuration", engine.last_error)

    def test_config_error_rejects_direct_enable_without_mutation(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=True),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream preparation must stay blocked")
        )

        with self.assertRaisesRegex(
            GatewayError,
            "Invalid app configuration",
        ):
            engine.apply()

        self.assertFalse(engine.enabled)
        self.assertFalse(engine.applied)

    def test_config_error_forces_owned_only_direct_cleanup(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
            config_error="Invalid app configuration: unusable options",
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must stay blocked")
        )

        engine.cleanup()

        self.assertFalse(engine.enabled)
        self.assertFalse(engine.applied)

    def test_status_uses_cached_health(self) -> None:
        self.engine.upstream_healthy = True
        self.engine.public_ip = "203.0.113.10"
        before = len(self.runner.commands)
        status = self.engine.status()
        self.assertEqual(len(self.runner.commands), before)
        self.assertTrue(status["upstream_healthy"])
        self.assertEqual(status["public_ip"], "203.0.113.10")

    def test_status_reports_disabled_state_when_not_enabled(self) -> None:
        self.assertFalse(self.engine.enabled)
        self.assertEqual(self.engine.status()["state"], "disabled")

    def test_status_reports_error_and_attention_for_genuine_fault(self) -> None:
        engine = self._prepare_active_engine()
        engine.last_safety_errors = ["Management interface is unavailable"]
        status = engine.status()
        self.assertEqual(status["state"], "error")
        self.assertEqual(status["health"], "attention")
        self.assertEqual(
            status["health_issues"],
            ["The management interface is unavailable"],
        )

    def test_status_treats_missing_upstream_as_healthy_waiting(self) -> None:
        engine = self._prepare_active_engine()
        engine.last_error = None
        engine.last_safety_errors = ["Upstream interface is unavailable"]
        status = engine.status()
        self.assertEqual(status["state"], "waiting")
        self.assertEqual(status["health"], "healthy")
        self.assertEqual(status["health_issues"], [])
        self.assertEqual(
            status["safety_errors"], ["Upstream interface is unavailable"]
        )

    def test_status_reports_connecting_while_source_setup_is_in_progress(self) -> None:
        engine = self._prepare_active_engine()
        engine.upstream.pairing_state = "waiting_for_profile"
        self.assertEqual(engine.status()["state"], "connecting")
        engine.apply()
        self.assertTrue(engine.applied)
        self.assertFalse(engine.upstream_healthy)
        self.assertEqual(engine.status()["state"], "connected")

    def test_status_reports_connected_when_gateway_is_applied(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        engine.upstream_healthy = False
        self.assertEqual(engine.status()["state"], "connected")

    def test_upstream_change_invalidates_cached_health(self) -> None:
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        usb = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.2/28",
            gateway="172.20.10.1",
        )
        self.engine._record_upstream(wifi)
        self.engine.upstream_healthy = True
        self.engine.public_ip = "203.0.113.10"
        self.engine.last_health_probe = time.time()

        self.engine._record_upstream(usb)

        self.assertFalse(self.engine.upstream_healthy)
        self.assertIsNone(self.engine.public_ip)
        self.assertIsNone(self.engine.last_health_probe)

    def test_stale_health_probe_result_is_discarded(self) -> None:
        self.engine.enabled = True
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        usb = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.2/28",
            gateway="172.20.10.1",
        )
        self.engine._record_upstream(wifi)

        def stale_probe(upstream):
            self.engine._record_upstream(usb)
            return True, "203.0.113.10"

        self.engine._health_probe = stale_probe
        self.engine._refresh_health_if_due()

        self.assertEqual(self.engine.last_upstream, usb)
        self.assertFalse(self.engine.upstream_healthy)
        self.assertIsNone(self.engine.public_ip)
        self.assertIsNone(self.engine.last_health_probe)

    def test_health_probe_result_is_discarded_after_cleanup(self) -> None:
        self.engine.enabled = True
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        self.engine._record_upstream(wifi)

        def stale_probe(upstream):
            self.engine.cleanup()
            return True, "203.0.113.10"

        self.engine._health_probe = stale_probe
        self.engine._refresh_health_if_due()

        self.assertEqual(self.engine.last_upstream, wifi)
        self.assertFalse(self.engine.upstream_healthy)
        self.assertIsNone(self.engine.public_ip)
        self.assertIsNone(self.engine.last_health_probe)

    def test_manual_reconcile_does_not_run_external_health_probe(self) -> None:
        self.engine.startup_cleanup_pending = False
        self.engine.safety.errors = lambda *args, **kwargs: []
        self.engine.reconcile()
        self.assertFalse(
            any(command and command[0] == "curl" for command in self.runner.commands)
        )

    def test_active_mode_recovers_after_transient_safety_failure(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(engine.applied)

        engine.safety.errors = lambda *args, **kwargs: ["Upstream unavailable"]
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertFalse(engine.applied)
        self.assertTrue(engine.enabled)

        engine.safety.errors = lambda *args, **kwargs: []
        engine.reconcile()
        self.assertTrue(engine.applied)

    def test_management_recovers_across_reconciles_without_restart(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.main_default_routes = []
        engine = GatewayEngine(
            make_config(enabled=True),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, management=None, **kwargs: (
            [] if management is not None else ["Management interface is unavailable"]
        )
        engine.firewall.installed = (
            lambda downstream=None, upstream_interface=None: engine.applied
        )
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )

        engine.reconcile()
        self.assertIsNone(engine.management)
        self.assertFalse(engine.applied)
        self.assertTrue(engine.enabled)
        self.assertIn(
            "Management interface is unavailable",
            engine.last_safety_errors,
        )
        self.assertNotIn(
            "enx001122334455",
            runner.interface_addresses,
        )

        runner.main_default_routes = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}
        ]

        engine.reconcile()
        self.assertIsNotNone(engine.management)
        assert engine.management is not None
        self.assertEqual(engine.management.interface, "end0")
        self.assertTrue(engine.applied)

    def test_activation_failure_is_cleaned_and_retried(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(
            engine.firewall.host_protection_installed("enx001122334455")
        )

        def fail_firewall(downstream: str, upstream_interface: str | None = None) -> None:
            raise OSError("firewall unavailable")

        engine.firewall.apply = fail_firewall
        with self.assertRaisesRegex(GatewayError, "Activation failed"):
            engine.apply()
        self.assertFalse(engine.applied)
        self.assertTrue(engine.enabled)
        self.assertTrue(
            engine.firewall.host_protection_installed("enx001122334455")
        )
        self.assertNotIn("enx001122334455", engine.runner.interface_addresses)

        engine.firewall.apply = lambda downstream, upstream_interface=None: None
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertTrue(engine.applied)

    def test_apply_safety_failure_cleans_host_state(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(
            engine.firewall.host_protection_installed("enx001122334455")
        )
        self.assertIn("enx001122334455", engine.runner.interface_addresses)

        engine.safety.errors = lambda *args, **kwargs: ["Upstream unavailable"]

        with self.assertRaisesRegex(SafetyError, "Upstream unavailable"):
            engine.apply()

        self.assertFalse(engine.applied)
        self.assertTrue(engine.enabled)
        self.assertTrue(
            engine.firewall.host_protection_installed("enx001122334455")
        )
        self.assertNotIn("enx001122334455", engine.runner.interface_addresses)

    def test_active_mode_reapplies_when_policy_state_is_missing(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
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
        engine.enabled = True
        engine.applied = True
        engine.active_connection = WIFI_HOTSPOT
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

    def test_iphone_usb_reconcile_is_idempotent_with_dynamic_upstream_interface(
        self,
    ) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=True, mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: []
        resolved = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.6/28",
            gateway="172.20.10.1",
        )
        engine.upstream.resolve = lambda *_a, **_k: (resolved, [])
        install_realistic_firewall_state(
            engine.runner,
            engine.firewall,
            "enx001122334455",
            resolved.interface,
        )
        install_realistic_policy_state(
            engine.runner,
            engine.policy,
            "enx001122334455",
            resolved,
        )
        engine.firewall.installed = engine.firewall.__class__.installed.__get__(
            engine.firewall,
            engine.firewall.__class__,
        )
        engine.policy.installed = engine.policy.__class__.installed.__get__(
            engine.policy,
            engine.policy.__class__,
        )
        engine.enabled = True
        engine.applied = True
        engine.active_connection = IPHONE_USB
        engine.startup_cleanup_pending = False
        engine.owned_state = engine.policy.ownership("enx001122334455", resolved)
        engine.dhcp.process = FakeProcess()
        dnsmasq_starts: list[str] = []

        def track_dnsmasq_start(downstream: str) -> None:
            dnsmasq_starts.append(downstream)
            engine.dhcp.process = FakeProcess()

        engine.dhcp.start = track_dnsmasq_start
        before = len(engine.runner.commands)

        engine.reconcile()

        commands = engine.runner.commands[before:]
        mutating_commands = [
            command
            for command in commands
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
        self.assertEqual(dnsmasq_starts, [])

    def test_combined_connection_fails_over_and_returns_to_usb(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(
                enabled=True,
                mobile_connection=IPHONE_USB_WIFI_FALLBACK,
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        def safety_errors(*args, upstream=None, **kwargs):
            if (
                upstream is not None
                and engine.owned_state
                and engine.active_connection != upstream.connection
            ):
                return ["Previous connection ownership is still installed"]
            return []

        engine.safety.errors = safety_errors
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )
        usb = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.2/28",
            gateway="172.20.10.1",
        )
        results = [
            (usb, []),
            (None, ["waiting for device"]),
            (usb, []),
        ]
        engine.upstream.resolve = lambda *_a, **_k: results.pop(0)

        engine.reconcile()
        self.assertEqual(engine.active_connection, IPHONE_USB)
        self.assertFalse(engine.status()["fallback_active"])

        engine.reconcile()
        self.assertEqual(engine.active_connection, WIFI_HOTSPOT)
        self.assertTrue(engine.status()["fallback_active"])
        self.assertEqual(engine.fallback_reason, "waiting for device")

        engine.reconcile()
        self.assertEqual(engine.active_connection, IPHONE_USB)
        self.assertFalse(engine.status()["fallback_active"])
        self.assertIsNone(engine.fallback_reason)

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
        self.assertTrue(
            any(command == "iptables -F HA_CELLGW" for command in commands)
        )
        self.assertTrue(
            any(command == "ip6tables -F HA_CELLGW6" for command in commands)
        )
        self.assertTrue(
            any(
                "HA_CELLGW_LOCAL" in command or "HA_CELLGW6_LOCAL" in command
                for command in commands
            )
        )
        self.assertNotIn("enx001122334455", engine.runner.interface_addresses)

    def test_cleanup_keeps_host_guard_if_address_removal_fails(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        def fail_address_cleanup(ownership) -> None:
            raise GatewayError("address still present")

        engine.downstream.cleanup = fail_address_cleanup

        with self.assertRaisesRegex(GatewayError, "address still present"):
            engine.cleanup()

        self.assertIsNotNone(engine.owned_state)
        self.assertTrue(
            engine.firewall.host_protection_installed(
                "enx001122334455"
            )
        )

    def test_usb_cleanup_ignores_unused_invalid_wifi_settings(self) -> None:
        values = sysctl_values()
        config = make_config(
            mobile_connection=IPHONE_USB,
            upstream_address="not-an-address",
            upstream_gateway="not-a-gateway",
        )
        config.validate()
        engine = GatewayEngine(
            config,
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.cleanup()

        self.assertFalse(engine.applied)
        self.assertIsNone(engine.owned_state)

    def test_disabled_mode_reconcile_preserves_host_guard(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
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
        self.assertTrue(mutating_commands)
        self.assertTrue(
            engine.firewall.host_protection_installed(
                "enx001122334455"
            )
        )
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

    def test_disabled_restart_cleanup_preserves_valid_host_guard(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        restarted = self._restart_disabled_engine()
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
        self.assertTrue(
            restarted.firewall.host_protection_installed(
                "enx001122334455"
            )
        )

    def test_disabled_restart_repairs_duplicate_host_guard(
        self,
    ) -> None:
        self._assert_disabled_restart_repairs_host_guard(
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

    def test_disabled_restart_repairs_late_host_guard(self) -> None:
        self._assert_disabled_restart_repairs_host_guard(
            (
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:local-jump -j HA_CELLGW_LOCAL",
            ),
            (
                "-A INPUT -j ACCEPT",
                "-A INPUT -i enx001122334455 -m comment --comment ha-cellgw:v6-local-jump -j HA_CELLGW6_LOCAL",
            ),
        )

    def test_disabled_mode_reconcile_repairs_late_parent_jumps(
        self,
    ) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=False),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
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
        self.assertTrue(
            engine.firewall.host_protection_installed(
                "enx001122334455"
            )
        )

    def test_persisted_extra_state_key_is_ignored(self) -> None:
        self.state_path.write_text(
            json.dumps(
                {
                    "unused": {
                        "started_at": time.time() - 400,
                        "deadline": time.time() - 100,
                    }
                }
            ),
            encoding="utf-8",
        )
        engine = self._prepare_active_engine()
        engine.reconcile()
        self.assertTrue(engine.applied)
        self.assertTrue(engine.enabled)
        self.assertNotIn("unused", self.state_path.read_text(encoding="utf-8"))

    def test_status_and_state_do_not_disclose_hotspot_password(self) -> None:
        engine = GatewayEngine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.owned_state = {"downstream": "eth1"}
        engine._persist_state()

        status_text = json.dumps(engine.status(), sort_keys=True)
        self.assertNotIn("hotspot_password", status_text)
        self.assertNotIn("supersecret", status_text)
        self.assertNotIn("supersecret", self.state_path.read_text(encoding="utf-8"))

    def test_unexpected_reconcile_error_fails_closed(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        engine.safety.errors = lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("inspection failed")
        )
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertFalse(engine.applied)
        self.assertTrue(engine.enabled)
        self.assertIn("Safety inspection failed", engine.last_error)

    def test_status_remains_responsive_during_blocking_upstream_resolution(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=True, mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        started = threading.Event()
        release = threading.Event()

        def slow_resolve(*_a, **_k):
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
        self.assertTrue(status["enabled"])

    def test_disabled_reconcile_skips_upstream_and_health_probes(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(enabled=False, mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.startup_cleanup_pending = False
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream resolution must remain dormant")
        )
        engine._health_probe = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("health probe must remain dormant")
        )

        engine.reconcile(refresh_health=True)

        self.assertFalse(engine.enabled)
        self.assertIsNone(engine.last_upstream)
        self.assertIsNone(engine.last_health_probe)

    def test_stop_cleans_upstream_after_gateway_cleanup_failure(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        upstream_cleaned = False

        def fail_cleanup(**kwargs) -> None:
            raise GatewayError("host cleanup failed")

        def cleanup_upstream() -> None:
            nonlocal upstream_cleaned
            upstream_cleaned = True

        engine.cleanup = fail_cleanup
        engine.upstream.cleanup = cleanup_upstream

        with self.assertRaisesRegex(GatewayError, "host cleanup failed"):
            engine.stop()

        self.assertTrue(upstream_cleaned)

    def test_stop_deactivates_managed_hotspot(self) -> None:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(
                enabled=False,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.management = ManagementBaseline("eth0", "192.168.1.2/24")
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        calls: list[bool] = []
        engine.upstream_lifecycle.configure = (
            lambda config, *, enabled: calls.append(enabled) or None
        )

        engine.stop()

        self.assertEqual(calls, [False])

    def test_stop_after_detected_usb_does_not_flush_external_interface(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        engine = GatewayEngine(
            make_config(mobile_connection=IPHONE_USB),
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
            run_dir = root / "run"
            usb_root.mkdir(parents=True)
            sys_net_root.mkdir(parents=True)
            sys_usb_root.mkdir(parents=True)
            driver_root.mkdir(parents=True)

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
                which=lambda command: f"/usr/bin/{command}",
                popen=lambda *args, **kwargs: FakeProcess(),
            )
            runner.commands.clear()
            engine.stop()

        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "del"]
                or command[:5] == ["ip", "route", "del", "default", "dev"]
                or command[:1] == ["nmcli"]
                for command in runner.commands
            )
        )

    def _wifi_hotspot_engine(self) -> GatewayEngine:
        values = sysctl_values()
        engine = GatewayEngine(
            make_config(
                enabled=True,
                mobile_connection=WIFI_HOTSPOT,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: [
            "Upstream interface/address is not active"
        ]
        return engine

    def test_wifi_reconcile_reports_disabled_adapter(self) -> None:
        engine = self._wifi_hotspot_engine()
        engine._interface_status = lambda: {"enabled": False, "connected": False}

        engine.reconcile()

        self.assertIn(WIFI_ADAPTER_DISABLED, engine.last_safety_errors)
        self.assertNotIn(
            "Upstream interface/address is not active",
            engine.last_safety_errors,
        )
        issue_ids = {issue["id"] for issue in engine.status()["issues"]}
        self.assertIn("hotspot_adapter_disabled", issue_ids)
        self.assertNotIn("upstream_interface_inactive", issue_ids)

    def test_wifi_reconcile_reports_association_failure(self) -> None:
        engine = self._wifi_hotspot_engine()
        engine._interface_status = lambda: {"enabled": True, "connected": False}

        engine.reconcile()

        self.assertIn(WIFI_NOT_ASSOCIATED, engine.last_safety_errors)
        self.assertNotIn(
            "Upstream interface/address is not active",
            engine.last_safety_errors,
        )
        issue_ids = {issue["id"] for issue in engine.status()["issues"]}
        self.assertIn("hotspot_not_associated", issue_ids)
        self.assertNotIn("upstream_interface_inactive", issue_ids)

    def test_wifi_reconcile_falls_back_when_supervisor_unavailable(self) -> None:
        engine = self._wifi_hotspot_engine()
        engine._interface_status = lambda: None

        engine.reconcile()

        self.assertIn(
            "Upstream interface/address is not active",
            engine.last_safety_errors,
        )
        self.assertNotIn(WIFI_ADAPTER_DISABLED, engine.last_safety_errors)
        self.assertNotIn(WIFI_NOT_ASSOCIATED, engine.last_safety_errors)
        issue_ids = {issue["id"] for issue in engine.status()["issues"]}
        self.assertIn("upstream_interface_inactive", issue_ids)
        self.assertNotIn("hotspot_adapter_disabled", issue_ids)
        self.assertNotIn("hotspot_not_associated", issue_ids)


if __name__ == "__main__":
    unittest.main()

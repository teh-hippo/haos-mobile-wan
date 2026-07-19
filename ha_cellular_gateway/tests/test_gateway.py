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
from rootfs.app.gateway_reconcile import apply as apply_gateway
from rootfs.app.management import ManagementBaseline
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from rootfs.app.upstream_models import ResolvedUpstream

from helpers import (
    build_engine,
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
        self.engine = build_engine(
            make_config(),
            runner=self.runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        self.engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _restart_engine(self) -> GatewayEngine:
        values = sysctl_values()
        restarted = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        restarted.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        # Stay in the running-but-waiting state so the data plane is not applied
        # and only the host-protection guard behaviour is exercised.
        restarted.safety.errors = lambda *args, **kwargs: [
            "Upstream interface is unavailable"
        ]
        return restarted

    def _prepare_active_engine(self) -> GatewayEngine:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, **kwargs: []
        engine.management = ManagementBaseline("end0", "192.168.1.2/24")
        engine.management_interface = "end0"
        engine.runner.nm_wifi_cache["wlan0"] = {"Phone"}
        engine.upstream_lifecycle.activate(engine.management)
        engine._persist_state()
        engine.firewall.installed = (
            lambda downstream=None, upstream_interface=None: engine.applied
        )
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )
        return engine

    def _assert_restart_repairs_host_guard(
        self,
        ipv4_input_rules: tuple[str, ...],
        ipv6_input_rules: tuple[str, ...],
    ) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        restarted = self._restart_engine()
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

    def test_running_reconcile_activates_gateway(self) -> None:
        engine = self._prepare_active_engine()
        engine.startup_cleanup_pending = False

        engine.reconcile()

        self.assertTrue(engine.applied)
        self.assertTrue(engine.dhcp.running)
        self.assertNotEqual(engine.status()["state"], "disabled")

    def test_config_error_still_cleans_owned_host_state(self) -> None:
        active = self._prepare_active_engine()
        active.apply()
        values = sysctl_values()
        degraded = build_engine(
            make_config(),
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
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
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

        self.assertFalse(engine.applied)
        self.assertIsNone(engine.last_downstream)
        self.assertIn("Invalid app configuration", engine.last_error)

    def test_config_error_rejects_direct_enable_without_mutation(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(),
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

        self.assertFalse(engine.applied)

    def test_config_error_forces_owned_only_direct_cleanup(self) -> None:
        values = sysctl_values()
        engine = build_engine(
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

        self.assertFalse(engine.applied)

    def test_status_uses_cached_health(self) -> None:
        self.engine.upstream_healthy = True
        self.engine.public_ip = "203.0.113.10"
        before = len(self.runner.commands)
        status = self.engine.status()
        self.assertEqual(len(self.runner.commands), before)
        self.assertTrue(status["upstream_healthy"])
        self.assertEqual(status["public_ip"], "203.0.113.10")

    def test_status_never_reports_disabled_state(self) -> None:
        status = self.engine.status()
        self.assertEqual(status["state"], "connecting")
        self.assertNotIn("enabled", status)
        self.assertNotIn("configured_enabled", status)
        self.assertNotIn("enabled", status["config"])

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

    def test_status_keeps_combined_usb_waiting_errors_healthy(self) -> None:
        engine = self._prepare_active_engine()
        pairing_message = (
            "Connect a single trusted iPhone with Personal Hotspot enabled"
        )
        errors = [pairing_message, "Upstream interface is unavailable"]
        engine.upstream.pairing_state = "waiting_for_device"
        engine.upstream.pairing_message = pairing_message
        engine.last_safety_errors = errors
        engine.last_error = "; ".join(errors)

        status = engine.status()

        self.assertEqual(status["state"], "waiting")
        self.assertEqual(status["health"], "healthy")
        self.assertEqual(status["health_issues"], [])

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
        self.engine.applied = True
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
        self.engine.applied = True
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
        engine = self._prepare_active_engine()
        engine.startup_cleanup_pending = False
        before = len(engine.runner.commands)
        engine.reconcile()
        self.assertFalse(
            any(
                command and command[0] == "curl"
                for command in engine.runner.commands[before:]
            )
        )

    def test_active_mode_recovers_after_transient_safety_failure(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(engine.applied)

        engine.safety.errors = lambda *args, **kwargs: ["Upstream unavailable"]
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertFalse(engine.applied)

        engine.safety.errors = lambda *args, **kwargs: []
        engine.reconcile()
        self.assertTrue(engine.applied)

    def test_management_recovers_across_reconciles_without_restart(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.main_default_routes = []
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = lambda *args, management=None, **kwargs: (
            [] if management is not None else ["Management interface is unavailable"]
        )
        runner.nm_wifi_cache["wlan0"] = {"Phone"}
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

    def test_missing_management_blocks_profile_and_downstream_mutation(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.main_default_routes = []
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("downstream discovery must wait for management")
        )

        engine.reconcile()

        self.assertEqual(runner.nm_profiles, {})
        self.assertIsNone(engine.last_downstream)
        self.assertIn("Management interface is unavailable", engine.last_error)

    def test_management_interface_change_releases_profiles_and_fails_closed(self) -> None:
        engine = self._prepare_active_engine()
        self.assertEqual(engine.management_interface, "end0")
        self.assertTrue(engine.runner.nm_profiles)
        engine.runner.main_default_routes = [
            {"dst": "default", "gateway": "192.168.2.1", "dev": "eth9"}
        ]
        engine.runner.interface_addresses["eth9"] = ("192.168.2.2", 24)

        engine.reconcile()

        self.assertFalse(engine.applied)
        self.assertEqual(engine.runner.nm_profiles, {})
        self.assertIn("Management interface changed", engine.last_error)

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
        engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
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
        engine = build_engine(
            make_config(
                mobile_connection=IPHONE_USB_WIFI_FALLBACK,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        def safety_errors(
            *args,
            upstream=None,
            upstream_errors=None,
            **kwargs,
        ):
            if upstream is None and upstream_errors:
                return list(upstream_errors)
            if (
                upstream is not None
                and engine.owned_state
                and engine.active_connection != upstream.connection
            ):
                return ["Previous connection ownership is still installed"]
            return []

        engine.safety.errors = safety_errors
        engine.runner.nm_wifi_cache["wlan0"] = {"Phone"}
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

    def _switch_upstream_commands(
        self,
        old: ResolvedUpstream,
        new: ResolvedUpstream,
    ) -> list[list[str]]:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                mobile_connection=IPHONE_USB_WIFI_FALLBACK,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        downstream = "enx001122334455"
        engine.management = ManagementBaseline("end0", "192.168.1.2/24")
        engine._resolve_management = lambda: engine.management
        engine.safety.find_downstream = lambda *_a, **_k: downstream
        engine.safety.errors = lambda *args, **kwargs: []
        engine.dhcp.start = lambda _downstream: setattr(
            engine.dhcp,
            "process",
            FakeProcess(),
        )
        engine.firewall.protect_host(downstream)
        engine.firewall.apply(downstream, old.interface)
        engine.policy.apply(downstream, old)
        engine.owned_state = engine.policy.ownership(downstream, old)
        engine.owned_state["downstream_address_owned"] = True
        engine.last_upstream = old
        engine.active_connection = old.connection
        engine.applied = True
        engine.startup_cleanup_pending = False
        before = len(engine.runner.commands)

        apply_gateway(engine, upstream=new, upstream_errors=[])

        self.assertEqual(engine.owned_state["upstream_interface"], new.interface)
        return engine.runner.commands[before:]

    @staticmethod
    def _first_index(commands, predicate):
        for index, command in enumerate(commands):
            if predicate(command):
                return index
        return None

    def _assert_old_removed_before_new_installed(
        self,
        old: ResolvedUpstream,
        new: ResolvedUpstream,
    ) -> None:
        commands = self._switch_upstream_commands(old, new)

        old_nat_del = self._first_index(
            commands,
            lambda c: c[:5] == ["iptables", "-t", "nat", "-D", "POSTROUTING"]
            and old.interface in c,
        )
        new_nat_add = self._first_index(
            commands,
            lambda c: c[:5] == ["iptables", "-t", "nat", "-A", "POSTROUTING"]
            and new.interface in c,
        )
        old_policy_del = self._first_index(
            commands,
            lambda c: c[:3] in (["ip", "rule", "del"], ["ip", "route", "del"])
            and old.interface in c,
        )
        new_policy_install = self._first_index(
            commands,
            lambda c: c[:3] in (["ip", "rule", "add"], ["ip", "route", "replace"]),
        )

        for label, index in (
            ("old NAT delete", old_nat_del),
            ("new NAT add", new_nat_add),
            ("old policy delete", old_policy_del),
            ("new policy install", new_policy_install),
        ):
            self.assertIsNotNone(index, f"missing {label} command")
        self.assertLess(old_nat_del, new_nat_add)
        self.assertLess(old_nat_del, new_policy_install)
        self.assertLess(old_policy_del, new_policy_install)

    def test_usb_to_wifi_promotion_removes_old_ownership_before_installing(
        self,
    ) -> None:
        usb = ResolvedUpstream(
            connection=IPHONE_USB,
            interface="eth0",
            address="172.20.10.2/28",
            gateway="172.20.10.1",
        )
        wifi = ResolvedUpstream(
            connection=WIFI_HOTSPOT,
            interface="wlan0",
            address="172.20.10.4/28",
            gateway="172.20.10.1",
        )
        self._assert_old_removed_before_new_installed(usb, wifi)

    def test_wifi_to_usb_promotion_removes_old_ownership_before_installing(
        self,
    ) -> None:
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
        self._assert_old_removed_before_new_installed(wifi, usb)

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
        engine = build_engine(
            config,
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.cleanup()

        self.assertFalse(engine.applied)
        self.assertIsNone(engine.owned_state)

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

    def test_restart_cleanup_preserves_valid_host_guard(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()

        restarted = self._restart_engine()
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
        engine.startup_cleanup_pending = False
        install_realistic_firewall_state(
            runner,
            engine.firewall,
            "enx001122334455",
        )
        engine.last_downstream = "enx001122334455"
        runner.main_default_routes = []

        engine.reconcile()

        self.assertTrue(
            engine.firewall.host_protection_installed(
                "enx001122334455"
            )
        )

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
        self.assertNotIn("unused", self.state_path.read_text(encoding="utf-8"))

    def test_status_and_state_do_not_disclose_hotspot_password(self) -> None:
        engine = build_engine(
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
        self.assertIn("networkmanager", engine.status())
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
        self.assertIn("Safety inspection failed", engine.last_error)

    def test_status_remains_responsive_during_blocking_upstream_resolution(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
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
        self.assertEqual(status["mobile_connection"], IPHONE_USB)

    def test_stop_pending_reconcile_skips_upstream_and_health_probes(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.startup_cleanup_pending = False
        engine.auto_disable.pending = True
        engine.upstream.resolve = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("upstream resolution must be skipped while stopping")
        )
        engine._health_probe = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("health probe must be skipped while stopping")
        )

        engine.reconcile(refresh_health=True)

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

    def test_stop_deletes_app_owned_wifi_profile(self) -> None:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.management = ManagementBaseline("eth0", "192.168.1.2/24")
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.upstream_lifecycle.activate(engine.management)
        self.assertTrue(engine.runner.nm_profiles)

        engine.stop()

        self.assertEqual(engine.runner.nm_profiles, {})

    def test_stop_after_detected_usb_does_not_flush_external_interface(self) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        engine = build_engine(
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
                for command in runner.commands
            )
        )

    def _wifi_hotspot_engine(self) -> GatewayEngine:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                mobile_connection=WIFI_HOTSPOT,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = (
            lambda *args, upstream_errors=None, **kwargs: list(
                upstream_errors or []
            )
        )
        engine.runner.nm_auto_activate = False
        return engine

    def test_wifi_reconcile_reports_association_failure(self) -> None:
        engine = self._wifi_hotspot_engine()

        engine.reconcile()

        self.assertIn(
            "The hotspot network is not currently visible",
            engine.last_safety_errors,
        )
        issue_ids = {issue["id"] for issue in engine.status()["issues"]}
        self.assertIn("hotspot_target_absent", issue_ids)
        self.assertEqual(engine.status()["state"], "waiting")


if __name__ == "__main__":
    unittest.main()

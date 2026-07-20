import unittest

from gateway_support import GatewayTestCase
from rootfs.app.const import IPHONE_USB, WIFI_HOTSPOT
from rootfs.app.errors import GatewayError, SafetyError
from rootfs.app.gateway import GatewayEngine
from rootfs.app.upstream_models import ResolvedUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.firewall_fixtures import (
    install_realistic_firewall_state,
    install_realistic_policy_state,
)
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class GatewayReconcileTests(GatewayTestCase):
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

    def test_activation_failure_is_cleaned_and_retried(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))

        def fail_firewall(
            downstream: str, upstream_interface: str | None = None
        ) -> None:
            raise OSError("firewall unavailable")

        engine.firewall.apply = fail_firewall
        with self.assertRaisesRegex(GatewayError, "Activation failed"):
            engine.apply()
        self.assertFalse(engine.applied)
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))
        self.assertNotIn("enx001122334455", engine.runner.routes.interface_addresses)

        engine.firewall.apply = lambda downstream, upstream_interface=None: None
        engine.startup_cleanup_pending = False
        engine.reconcile()
        self.assertTrue(engine.applied)

    def test_apply_safety_failure_cleans_host_state(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))
        self.assertIn("enx001122334455", engine.runner.routes.interface_addresses)

        engine.safety.errors = lambda *args, **kwargs: ["Upstream unavailable"]

        with self.assertRaisesRegex(SafetyError, "Upstream unavailable"):
            engine.apply()

        self.assertFalse(engine.applied)
        self.assertTrue(engine.firewall.host_protection_installed("enx001122334455"))
        self.assertNotIn("enx001122334455", engine.runner.routes.interface_addresses)

    def test_active_mode_reapplies_when_policy_state_is_missing(self) -> None:
        engine = self._prepare_active_engine()
        engine.apply()
        before = len(engine.runner.commands)

        engine.startup_cleanup_pending = False
        engine.policy.installed = lambda downstream, upstream=None: False
        engine.firewall.installed = lambda downstream=None, upstream_interface=None: (
            True
        )
        engine.reconcile()

        reapplied = engine.runner.commands[before:]
        self.assertTrue(
            any(command[:3] == ["ip", "rule", "add"] for command in reapplied)
        )
        self.assertTrue(
            any(command[:3] == ["ip", "route", "replace"] for command in reapplied)
        )

    def test_active_mode_reconcile_does_not_reapply_realistic_firewall_state(
        self,
    ) -> None:
        engine = self._prepare_active_engine()
        install_realistic_firewall_state(
            engine.runner, engine.firewall, "enx001122334455"
        )
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
        engine.safety.errors = lambda *args, upstream_errors=None, **kwargs: list(
            upstream_errors or []
        )
        engine.runner.networkmanager.nm_auto_activate = False
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

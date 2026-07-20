import unittest

from gateway_support import GatewayTestCase
from rootfs.app.const import IPHONE_USB, IPHONE_USB_WIFI_FALLBACK, WIFI_HOTSPOT
from rootfs.app.gateway_reconcile import apply as apply_gateway
from rootfs.app.management import ManagementBaseline
from rootfs.app.upstream_models import ResolvedUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class GatewayFailoverTests(GatewayTestCase):
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
        engine.runner.networkmanager.nm_wifi_cache["wlan0"] = {"Phone"}
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

    def test_combined_connection_reports_unavailable_fallback_truthfully(
        self,
    ) -> None:
        values = sysctl_values()
        runner = FakeRunner()
        runner.networkmanager.nm_radio_query_fail = True
        engine = build_engine(
            make_config(
                mobile_connection=IPHONE_USB_WIFI_FALLBACK,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
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
        ]
        engine.upstream.resolve = lambda *_a, **_k: results.pop(0)

        engine.reconcile()
        status = engine.status()
        self.assertEqual(status["state"], "connected")
        self.assertEqual(status["health"], "attention")
        self.assertEqual(
            status["health_issues"],
            ["NetworkManager Wi-Fi radio inspection is unavailable"],
        )
        self.assertTrue(engine.applied)

        engine.reconcile()
        status = engine.status()
        self.assertEqual(status["state"], "error")
        self.assertEqual(status["health"], "attention")
        self.assertFalse(engine.applied)

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
            lambda c: (
                c[:5] == ["iptables", "-t", "nat", "-D", "POSTROUTING"]
                and old.interface in c
            ),
        )
        new_nat_add = self._first_index(
            commands,
            lambda c: (
                c[:5] == ["iptables", "-t", "nat", "-A", "POSTROUTING"]
                and new.interface in c
            ),
        )
        old_policy_del = self._first_index(
            commands,
            lambda c: (
                c[:3] in (["ip", "rule", "del"], ["ip", "route", "del"])
                and old.interface in c
            ),
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rootfs.app import safety_checks
from rootfs.app.const import IPHONE_USB
from rootfs.app.errors import GatewayError
from rootfs.app.management import ManagementBaseline
from rootfs.app.upstream_models import ResolvedUpstream
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner

UPSTREAM = ResolvedUpstream(
    connection="wifi_hotspot",
    interface="wlan0",
    address="172.20.10.4/28",
    gateway="172.20.10.1",
)


class SafetyChecksTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        values = sysctl_values()
        engine = build_engine(
            make_config(),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=Path(self.directory.name) / "state.json",
        )
        self.inspector = engine.safety


class ResolveUpstreamInterfaceTests(SafetyChecksTestCase):
    def test_returns_the_resolved_upstream_interface_when_present(self) -> None:
        self.assertEqual(
            safety_checks.resolve_upstream_interface(self.inspector, UPSTREAM),
            "wlan0",
        )

    def test_falls_back_to_configured_interface_without_a_resolved_upstream(
        self,
    ) -> None:
        self.assertEqual(
            safety_checks.resolve_upstream_interface(self.inspector, None),
            "wlan0",
        )

    def test_returns_none_when_wifi_is_not_used_and_no_upstream_resolved(
        self,
    ) -> None:
        values = sysctl_values()
        usb_engine = build_engine(
            make_config(mobile_connection=IPHONE_USB),
            runner=FakeRunner(),
            read_text=lambda path: values[path],
            state_path=Path(self.directory.name) / "usb-state.json",
        )

        self.assertIsNone(
            safety_checks.resolve_upstream_interface(usb_engine.safety, None)
        )


class PriorErrorsTests(unittest.TestCase):
    def test_combines_state_error_before_upstream_errors(self) -> None:
        errors = safety_checks.prior_errors(
            "Persistent state is invalid", ["Upstream resolution failed"]
        )

        self.assertEqual(
            errors,
            ["Persistent state is invalid", "Upstream resolution failed"],
        )

    def test_no_errors_when_nothing_is_reported(self) -> None:
        self.assertEqual(safety_checks.prior_errors(None, None), [])


class ManagementErrorsTests(SafetyChecksTestCase):
    def test_reports_unavailable_when_address_lookup_raises(self) -> None:
        def _fail(interface: str, family: int = 4) -> set[str]:
            raise OSError("no such interface")

        self.inspector.interface_addresses = _fail
        baseline = ManagementBaseline("end0", "192.168.1.2/24")

        errors = safety_checks.management_errors(self.inspector, baseline)

        self.assertEqual(errors, ["Management interface is unavailable"])


class IpForwardErrorsTests(SafetyChecksTestCase):
    def test_reports_when_forwarding_is_not_enabled(self) -> None:
        self.inspector.ip_forward = lambda: 0

        self.assertEqual(
            safety_checks.ip_forward_errors(self.inspector),
            ["Host IPv4 forwarding is not enabled"],
        )

    def test_reports_when_forwarding_state_is_unreadable(self) -> None:
        def _fail() -> int:
            raise OSError("no proc entry")

        self.inspector.ip_forward = _fail

        self.assertEqual(
            safety_checks.ip_forward_errors(self.inspector),
            ["Cannot verify host IPv4 forwarding"],
        )


class RpFilterErrorsTests(SafetyChecksTestCase):
    def test_reports_strict_interfaces_and_unreadable_interfaces_independently(
        self,
    ) -> None:
        def fake_rp_filter(interface: str) -> int:
            if interface == "all":
                return 1
            if interface == "default":
                raise OSError("no proc entry")
            return 0

        self.inspector.rp_filter = fake_rp_filter

        errors = safety_checks.rp_filter_errors(self.inspector, "end0", "wlan0")

        self.assertIn("Strict rp_filter is enabled on all", errors)
        self.assertIn("Cannot read rp_filter for default", errors)
        self.assertEqual(len(errors), 2)


class FirewallErrorsTests(SafetyChecksTestCase):
    def test_reports_non_nftables_backend(self) -> None:
        self.inspector.firewall.backend_ok = lambda: False
        self.inspector.firewall.chain_exists = lambda family, chain: True

        self.assertEqual(
            safety_checks.firewall_errors(self.inspector),
            ["iptables is not using the nf_tables backend"],
        )

    def test_reports_missing_docker_chain(self) -> None:
        self.inspector.firewall.backend_ok = lambda: True
        self.inspector.firewall.chain_exists = lambda family, chain: False

        self.assertEqual(
            safety_checks.firewall_errors(self.inspector),
            ["Docker DOCKER-USER chain is missing"],
        )

    def test_reports_inspection_failure(self) -> None:
        def _fail() -> bool:
            raise GatewayError("iptables missing")

        self.inspector.firewall.backend_ok = _fail

        self.assertEqual(
            safety_checks.firewall_errors(self.inspector),
            ["Cannot inspect the host firewall backend"],
        )


class UpstreamAvailabilityErrorsTests(SafetyChecksTestCase):
    def test_active_upstream_reports_no_errors(self) -> None:
        self.inspector.interface_addresses = lambda interface, family=4: {
            UPSTREAM.address
        }

        self.assertEqual(
            safety_checks.upstream_availability_errors(self.inspector, UPSTREAM), []
        )

    def test_reports_inactive_address(self) -> None:
        self.inspector.interface_addresses = lambda interface, family=4: {"10.0.0.5/24"}

        self.assertEqual(
            safety_checks.upstream_availability_errors(self.inspector, UPSTREAM),
            ["Upstream interface/address is not active"],
        )

    def test_reports_unavailable_on_exception(self) -> None:
        def _fail(interface: str, family: int = 4) -> set[str]:
            raise OSError("no such interface")

        self.inspector.interface_addresses = _fail

        self.assertEqual(
            safety_checks.upstream_availability_errors(self.inspector, UPSTREAM),
            ["Upstream interface is unavailable"],
        )


class DefaultRouteErrorsTests(SafetyChecksTestCase):
    def test_flags_upstream_holding_the_main_default_route(self) -> None:
        self.inspector.main_default_interfaces = lambda: {"wlan0"}

        errors = safety_checks.default_route_errors(self.inspector, None, "wlan0")

        self.assertEqual(errors, ["Mobile upstream has a main-table default route"])

    def test_reports_inspection_failure(self) -> None:
        def _fail() -> set[str]:
            raise OSError("no route table")

        self.inspector.main_default_interfaces = _fail

        errors = safety_checks.default_route_errors(self.inspector, "end0", "wlan0")

        self.assertEqual(errors, ["Cannot inspect main-table default routes"])


class DownstreamSectionErrorsTests(SafetyChecksTestCase):
    def test_delegates_to_selection_error_when_downstream_is_missing(self) -> None:
        self.inspector.downstream.selection_error = lambda management_interface: (
            "custom selection message"
        )

        errors = safety_checks.downstream_section_errors(
            self.inspector,
            None,
            "wlan0",
            management_interface="end0",
            downstream_address_owned=False,
            current_upstream=None,
        )

        self.assertEqual(errors, ["custom selection message"])


class PolicyConflictErrorsTests(SafetyChecksTestCase):
    def test_returns_conflicts_reported_by_policy_routing(self) -> None:
        self.inspector.policy.conflicts = lambda downstream, upstream: [
            "policy conflict detected"
        ]

        errors = safety_checks.policy_conflict_errors(
            self.inspector, "enx001122334455", UPSTREAM
        )

        self.assertEqual(errors, ["policy conflict detected"])

    def test_reports_inspection_failure(self) -> None:
        def _fail(downstream: str, upstream: object) -> list[str]:
            raise OSError("cannot inspect rules")

        self.inspector.policy.conflicts = _fail

        errors = safety_checks.policy_conflict_errors(
            self.inspector, "enx001122334455", UPSTREAM
        )

        self.assertEqual(errors, ["Cannot inspect policy-routing ownership"])


class UpstreamIpv6ErrorsTests(SafetyChecksTestCase):
    def test_flags_non_link_local_address(self) -> None:
        self.inspector.has_non_link_local_ipv6 = lambda interface: True

        self.assertEqual(
            safety_checks.upstream_ipv6_errors(self.inspector, "wlan0"),
            ["IPv6 is active on mobile upstream"],
        )

    def test_reports_verification_failure(self) -> None:
        def _fail(interface: str) -> bool:
            raise OSError("no such interface")

        self.inspector.has_non_link_local_ipv6 = _fail

        self.assertEqual(
            safety_checks.upstream_ipv6_errors(self.inspector, "wlan0"),
            ["Cannot verify upstream IPv6 state"],
        )


class DownstreamErrorsTests(SafetyChecksTestCase):
    def test_flags_strict_rp_filter_on_downstream_nic(self) -> None:
        self.inspector.downstream.address_errors = lambda downstream, owned: []
        self.inspector.rp_filter = lambda interface: 1
        self.inspector.has_non_link_local_ipv6 = lambda interface: False

        errors = safety_checks.downstream_errors(
            self.inspector,
            "enx001122334455",
            "wlan0",
            management_interface="end0",
            address_owned=True,
        )

        self.assertIn("Strict rp_filter is enabled on downstream NIC", errors)

    def test_reports_unavailable_when_address_or_rp_filter_lookup_raises(
        self,
    ) -> None:
        def _fail(downstream: str, owned: bool) -> list[str]:
            raise OSError("no such interface")

        self.inspector.downstream.address_errors = _fail
        self.inspector.has_non_link_local_ipv6 = lambda interface: False

        errors = safety_checks.downstream_errors(
            self.inspector,
            "enx001122334455",
            "wlan0",
            management_interface="end0",
            address_owned=True,
        )

        self.assertIn("Downstream interface is unavailable", errors)

    def test_flags_non_link_local_ipv6_on_downstream_nic(self) -> None:
        self.inspector.downstream.address_errors = lambda downstream, owned: []
        self.inspector.rp_filter = lambda interface: 0
        self.inspector.has_non_link_local_ipv6 = lambda interface: True

        errors = safety_checks.downstream_errors(
            self.inspector,
            "enx001122334455",
            "wlan0",
            management_interface="end0",
            address_owned=True,
        )

        self.assertIn("IPv6 is active on downstream NIC", errors)

    def test_reports_ipv6_verification_failure(self) -> None:
        def _fail(interface: str) -> bool:
            raise OSError("no such interface")

        self.inspector.downstream.address_errors = lambda downstream, owned: []
        self.inspector.rp_filter = lambda interface: 0
        self.inspector.has_non_link_local_ipv6 = _fail

        errors = safety_checks.downstream_errors(
            self.inspector,
            "enx001122334455",
            "wlan0",
            management_interface="end0",
            address_owned=True,
        )

        self.assertIn("Cannot verify downstream IPv6 state", errors)


if __name__ == "__main__":
    unittest.main()

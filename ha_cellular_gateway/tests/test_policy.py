import tempfile
import unittest
from pathlib import Path

from rootfs.app.errors import GatewayError
from rootfs.app.policy import PolicyRouting
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.process import Result
from test_support.runner import FakeRunner


class PolicyRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runner = FakeRunner()
        values = sysctl_values()
        self.engine = build_engine(
            make_config(),
            runner=self.runner,
            read_text=lambda path: values[path],
            state_path=Path(self.directory.name) / "state.json",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_policy_routes_only_owned_traffic(self) -> None:
        self.engine.policy.apply("enx001122334455")
        commands = [" ".join(command) for command in self.runner.commands]

        self.assertIn(
            "ip route replace 192.168.80.0/24 dev enx001122334455 src 192.168.80.1 table 201",
            commands,
        )
        self.assertIn(
            "ip rule add pref 20100 iif enx001122334455 lookup 201",
            commands,
        )
        self.assertIn(
            "ip rule add pref 20110 from 192.168.80.0/24 lookup 201",
            commands,
        )
        self.assertFalse(any("end0" in command for command in commands))

    def test_cleanup_never_deletes_by_priority_alone(self) -> None:
        ownership = self.engine.policy.ownership("enx001122334455")
        self.engine.policy.cleanup(ownership)
        delete_commands = [
            command
            for command in self.runner.commands
            if command[:3] == ["ip", "rule", "del"]
        ]
        self.assertTrue(delete_commands)
        self.assertTrue(all(len(command) > 5 for command in delete_commands))
        self.assertFalse(
            any(
                command == ["ip", "rule", "del", "pref", "20100"]
                for command in delete_commands
            )
        )

    def test_foreign_priority_is_reported_without_mutation(self) -> None:
        self.runner.routes.policy_rules = [
            {
                "priority": 20100,
                "iifname": "wg0",
                "table": 51820,
            }
        ]
        errors = self.engine.policy.conflicts("enx001122334455")
        self.assertEqual(errors, ["Policy priority 20100 is already in use"])
        self.assertFalse(
            any(
                command[:3] == ["ip", "rule", "del"] for command in self.runner.commands
            )
        )

    def test_foreign_rule_using_owned_table_is_reported(self) -> None:
        self.runner.routes.policy_rules = [
            {
                "priority": 10000,
                "src": "10.0.0.0",
                "srclen": 8,
                "table": "201",
            }
        ]
        self.assertEqual(
            self.engine.policy.conflicts("enx001122334455"),
            ["Routing table 201 already has a foreign policy rule"],
        )

    def test_owned_rules_from_iproute_json_are_accepted(self) -> None:
        self.runner.routes.policy_rules = [
            {
                "priority": 20100,
                "src": "all",
                "iif": "enx001122334455",
                "table": "201",
            },
            {
                "priority": 20110,
                "src": "192.168.80.0",
                "srclen": 24,
                "table": "201",
            },
            {
                "priority": 20120,
                "src": "172.20.10.4",
                "table": "201",
            },
        ]
        self.assertEqual(
            self.engine.policy.conflicts("enx001122334455"),
            [],
        )

    def test_value_raises_when_ownership_state_is_missing_a_key(self) -> None:
        with self.assertRaises(GatewayError) as excinfo:
            self.engine.policy.rule_args({})

        self.assertIn("downstream", str(excinfo.exception))

    def test_installed_is_false_without_a_downstream_interface(self) -> None:
        self.assertFalse(self.engine.policy.installed(None))
        self.assertFalse(self.engine.policy.installed(""))
        self.assertEqual(self.runner.commands, [])

    def test_rule_conflicts_skips_non_dict_entries(self) -> None:
        self.runner.routes.policy_rules = ["not-a-rule", 42]

        self.assertEqual(self.engine.policy.conflicts("enx001122334455"), [])

    def test_route_conflicts_reports_foreign_routes_while_ignoring_owned_ones(
        self,
    ) -> None:
        self.runner.routes.policy_routes = [
            {
                "dst": "192.168.80.0/24",
                "dev": "enx001122334455",
                "prefsrc": "192.168.80.1",
            },
            {
                "dst": "10.0.0.0/24",
                "dev": "wg0",
                "prefsrc": "10.0.0.1",
            },
        ]

        self.assertEqual(
            self.engine.policy.conflicts("enx001122334455"),
            ["Routing table 201 contains an unexpected route"],
        )

    def test_cleanup_with_no_ownership_is_a_no_op(self) -> None:
        self.engine.policy.cleanup(None)
        self.engine.policy.cleanup({})

        self.assertEqual(self.runner.commands, [])

    def test_cleanup_retries_deletion_while_the_kernel_still_reports_success(
        self,
    ) -> None:
        counts: dict[tuple[str, ...], int] = {}

        def run(*args: str, check: bool = True) -> Result:
            argv = tuple(args)
            counts[argv] = counts.get(argv, 0) + 1
            if argv[:3] in (("ip", "rule", "del"), ("ip", "route", "del")):
                return Result(returncode=0 if counts[argv] <= 2 else 1)
            return Result()

        policy = PolicyRouting(make_config(), run)
        ownership = policy.ownership("enx001122334455")

        policy.cleanup(ownership)

        rule_deletes = {
            argv: count
            for argv, count in counts.items()
            if argv[:3] == ("ip", "rule", "del")
        }
        route_deletes = {
            argv: count
            for argv, count in counts.items()
            if argv[:3] == ("ip", "route", "del")
        }
        self.assertTrue(rule_deletes)
        self.assertTrue(route_deletes)
        self.assertTrue(all(count == 3 for count in rule_deletes.values()))
        self.assertTrue(all(count == 3 for count in route_deletes.values()))


if __name__ == "__main__":
    unittest.main()

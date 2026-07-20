import tempfile
import unittest
from pathlib import Path

from helpers import FakeRunner, build_engine, make_config, sysctl_values


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
        self.runner.policy_rules = [
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
        self.runner.policy_rules = [
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
        self.runner.policy_rules = [
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


if __name__ == "__main__":
    unittest.main()

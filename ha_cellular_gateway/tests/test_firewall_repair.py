import tempfile
import unittest
from pathlib import Path

from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.firewall_fixtures import (
    install_realistic_firewall_state,
    prepend_chain_rule,
)
from test_support.runner import FakeRunner


class FirewallRepairTests(unittest.TestCase):
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

    def _assert_parent_jump_repair(
        self,
        family: str,
        parent: str,
        child: str,
        comment: str,
        initial_rules: list[str],
        match: list[str] | None = None,
    ) -> None:
        rule = self.engine.firewall.netfilter.jump_rule(child, comment, match)
        self.runner.firewall.chain_listings[(family, parent)] = "\n".join(initial_rules)

        self.engine.firewall.netfilter.ensure_jump(
            family,
            parent,
            child,
            comment,
            match,
        )

        self.assertTrue(
            self.engine.firewall.netfilter.rule_is_first_unique(
                family,
                parent,
                rule,
            )
        )

    def test_protect_host_repairs_parent_jump_without_flushing_live_guard(self) -> None:
        firewall = self.engine.firewall
        install_realistic_firewall_state(self.runner, firewall, "enx001122334455")
        prepend_chain_rule(
            self.runner,
            "iptables",
            "INPUT",
            "-A INPUT -j ACCEPT",
        )
        prepend_chain_rule(
            self.runner,
            "ip6tables",
            "INPUT",
            "-A INPUT -j ACCEPT",
        )
        before = len(self.runner.commands)

        firewall.protect_host("enx001122334455")

        commands = self.runner.commands[before:]
        self.assertFalse(
            any(
                command[:3]
                in (
                    ["iptables", "-F", firewall.INPUT_CHAIN],
                    ["iptables", "-X", firewall.INPUT_CHAIN],
                    ["ip6tables", "-F", firewall.INPUT6_CHAIN],
                    ["ip6tables", "-X", firewall.INPUT6_CHAIN],
                )
                for command in commands
            )
        )
        self.assertIn(
            [
                "iptables",
                "-I",
                "INPUT",
                "1",
                "-i",
                "enx001122334455",
                "-j",
                firewall.INPUT_CHAIN,
                "-m",
                "comment",
                "--comment",
                "ha-cellgw:local-jump",
            ],
            commands,
        )
        self.assertIn(
            [
                "ip6tables",
                "-I",
                "INPUT",
                "1",
                "-i",
                "enx001122334455",
                "-j",
                firewall.INPUT6_CHAIN,
                "-m",
                "comment",
                "--comment",
                "ha-cellgw:v6-local-jump",
            ],
            commands,
        )

    def test_ensure_jump_repairs_stateful_parent_hooks(self) -> None:
        firewall = self.engine.firewall
        downstream = "enx001122334455"
        cases = (
            (
                "iptables",
                "INPUT",
                firewall.INPUT_CHAIN,
                "ha-cellgw:local-jump",
                [
                    "-A INPUT -j ACCEPT",
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:local-jump -j {firewall.INPUT_CHAIN}",
                ],
                ["-i", downstream],
            ),
            (
                "iptables",
                "INPUT",
                firewall.INPUT_CHAIN,
                "ha-cellgw:local-jump",
                [
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:local-jump -j {firewall.INPUT_CHAIN}",
                    "-A INPUT -j ACCEPT",
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:local-jump -j {firewall.INPUT_CHAIN}",
                ],
                ["-i", downstream],
            ),
            (
                "iptables",
                "DOCKER-USER",
                firewall.FORWARD_CHAIN,
                "ha-cellgw:jump",
                [
                    "-A DOCKER-USER -j RETURN",
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:jump -j {firewall.FORWARD_CHAIN}",
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:jump -j {firewall.FORWARD_CHAIN}",
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:jump -j {firewall.FORWARD_CHAIN}",
                ],
                None,
            ),
            (
                "ip6tables",
                "INPUT",
                firewall.INPUT6_CHAIN,
                "ha-cellgw:v6-local-jump",
                [
                    "-A INPUT -j ACCEPT",
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:v6-local-jump -j {firewall.INPUT6_CHAIN}",
                ],
                ["-i", downstream],
            ),
            (
                "ip6tables",
                "DOCKER-USER",
                firewall.FORWARD6_CHAIN,
                "ha-cellgw:v6-jump",
                [
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:v6-jump -j {firewall.FORWARD6_CHAIN}",
                    "-A DOCKER-USER -j RETURN",
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:v6-jump -j {firewall.FORWARD6_CHAIN}",
                ],
                None,
            ),
        )

        for family, parent, child, comment, initial_rules, match in cases:
            with self.subTest(
                family=family, parent=parent, initial_rules=initial_rules
            ):
                self.runner.firewall.chain_listings.pop((family, parent), None)
                self._assert_parent_jump_repair(
                    family,
                    parent,
                    child,
                    comment,
                    initial_rules,
                    match,
                )

    def test_apply_repairs_forward_jump_without_flushing_live_chains(self) -> None:
        firewall = self.engine.firewall
        install_realistic_firewall_state(self.runner, firewall, "enx001122334455")
        prepend_chain_rule(
            self.runner,
            "iptables",
            "DOCKER-USER",
            "-A DOCKER-USER -j RETURN",
        )
        prepend_chain_rule(
            self.runner,
            "ip6tables",
            "DOCKER-USER",
            "-A DOCKER-USER -j RETURN",
        )
        before = len(self.runner.commands)

        firewall.apply("enx001122334455")

        commands = self.runner.commands[before:]
        self.assertFalse(
            any(
                command[:3]
                in (
                    ["iptables", "-F", firewall.INPUT_CHAIN],
                    ["iptables", "-X", firewall.INPUT_CHAIN],
                    ["iptables", "-F", firewall.FORWARD_CHAIN],
                    ["iptables", "-X", firewall.FORWARD_CHAIN],
                    ["ip6tables", "-F", firewall.INPUT6_CHAIN],
                    ["ip6tables", "-X", firewall.INPUT6_CHAIN],
                    ["ip6tables", "-F", firewall.FORWARD6_CHAIN],
                    ["ip6tables", "-X", firewall.FORWARD6_CHAIN],
                )
                for command in commands
            )
        )
        self.assertIn(
            [
                "iptables",
                "-I",
                "DOCKER-USER",
                "1",
                "-j",
                firewall.FORWARD_CHAIN,
                "-m",
                "comment",
                "--comment",
                "ha-cellgw:jump",
            ],
            commands,
        )
        self.assertIn(
            [
                "ip6tables",
                "-I",
                "DOCKER-USER",
                "1",
                "-j",
                firewall.FORWARD6_CHAIN,
                "-m",
                "comment",
                "--comment",
                "ha-cellgw:v6-jump",
            ],
            commands,
        )


if __name__ == "__main__":
    unittest.main()

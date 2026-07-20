import tempfile
import unittest
from pathlib import Path

from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.firewall_fixtures import (
    install_realistic_firewall_state,
    prepend_chain_rule,
)
from test_support.runner import FakeRunner


class FirewallStateTests(unittest.TestCase):
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

    def test_firewall_is_scoped_and_protects_host(self) -> None:
        self.engine.firewall.apply("enx001122334455")
        commands = [" ".join(command) for command in self.runner.commands]

        self.assertIn(
            "iptables -I INPUT 1 -i enx001122334455 -j HA_CELLGW_LOCAL -m comment --comment ha-cellgw:local-jump",
            commands,
        )
        self.assertTrue(
            any(
                "HA_CELLGW_LOCAL -p udp --sport 68 --dport 67 -j ACCEPT" in command
                for command in commands
            )
        )
        self.assertTrue(
            any("HA_CELLGW_LOCAL -p icmp -j ACCEPT" in command for command in commands)
        )
        self.assertTrue(
            any("HA_CELLGW_LOCAL -j DROP" in command for command in commands)
        )
        self.assertTrue(
            any(
                "-i enx001122334455 -o wlan0 -s 192.168.80.0/24" in command
                and "TCPMSS" in command
                for command in commands
            )
        )
        self.assertFalse(
            any(
                "INPUT 1 -i end0" in command or "INPUT 1 -i wlan0" in command
                for command in commands
            )
        )

    def test_ipv6_is_blocked_on_downstream(self) -> None:
        self.engine.firewall.apply("enx001122334455")
        commands = [" ".join(command) for command in self.runner.commands]
        self.assertIn(
            "ip6tables -I INPUT 1 -i enx001122334455 -j HA_CELLGW6_LOCAL -m comment --comment ha-cellgw:v6-local-jump",
            commands,
        )
        self.assertIn(
            "ip6tables -A HA_CELLGW6_LOCAL -j DROP",
            commands,
        )

    def test_installed_requires_owned_local_rules(self) -> None:
        firewall = self.engine.firewall
        existing = {
            (
                "iptables",
                "DOCKER-USER",
                tuple(),
                tuple(
                    firewall.netfilter.jump_rule(
                        firewall.FORWARD_CHAIN, "ha-cellgw:jump"
                    )
                ),
            ),
            (
                "iptables",
                "INPUT",
                tuple(),
                tuple(
                    firewall.netfilter.jump_rule(
                        firewall.INPUT_CHAIN,
                        "ha-cellgw:local-jump",
                        ["-i", "enx001122334455"],
                    )
                ),
            ),
            ("iptables", "POSTROUTING", ("-t", "nat"), tuple(firewall._nat_rule())),
            *{
                ("iptables", "FORWARD", ("-t", "mangle"), tuple(rule))
                for rule in firewall._mss_rules("enx001122334455")
            },
        }
        firewall.netfilter.chain_exists = lambda family, chain: family == "iptables"
        firewall.netfilter.rule_exists = lambda family, chain, rule, table_args=None: (
            (
                family,
                chain,
                tuple(table_args or ()),
                tuple(rule),
            )
            in existing
        )
        firewall.netfilter.chain_rules = lambda family, chain, table_args=None: []

        self.assertFalse(firewall.installed("enx001122334455"))

    def test_installed_accepts_realistic_iptables_s_output(self) -> None:
        firewall = self.engine.firewall
        install_realistic_firewall_state(self.runner, firewall, "enx001122334455")

        self.assertTrue(firewall.installed("enx001122334455"))

    def test_installed_accepts_realistic_dynamic_usb_upstream(self) -> None:
        firewall = self.engine.firewall
        install_realistic_firewall_state(
            self.runner,
            firewall,
            "enx001122334455",
            "eth0",
        )

        self.assertTrue(firewall.installed("enx001122334455", "eth0"))

    def test_host_protection_rejects_unexpected_local_accept(self) -> None:
        firewall = self.engine.firewall
        firewall.netfilter.chain_exists = lambda family, chain: family == "iptables"
        firewall.netfilter.rule_exists = lambda family, chain, rule, table_args=None: (
            (
                family,
                chain,
                tuple(rule),
            )
            == (
                "iptables",
                "INPUT",
                tuple(
                    firewall.netfilter.jump_rule(
                        firewall.INPUT_CHAIN,
                        "ha-cellgw:local-jump",
                        ["-i", "enx001122334455"],
                    )
                ),
            )
        )
        firewall.netfilter.chain_rules = lambda family, chain, table_args=None: [
            *firewall._input_rules()[:-1],
            ["-j", "ACCEPT"],
            firewall._input_rules()[-1],
        ]

        self.assertFalse(firewall.host_protection_installed("enx001122334455"))

    def test_host_protection_accepts_realistic_iptables_s_output(self) -> None:
        firewall = self.engine.firewall
        install_realistic_firewall_state(self.runner, firewall, "enx001122334455")

        self.assertTrue(firewall.host_protection_installed("enx001122334455"))

    def test_host_protection_rejects_bypass_rule_before_parent_jump(self) -> None:
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

        self.assertFalse(firewall.host_protection_installed("enx001122334455"))

    def test_installed_rejects_bypass_rule_before_forward_jump(self) -> None:
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

        self.assertFalse(firewall.installed("enx001122334455"))


if __name__ == "__main__":
    unittest.main()

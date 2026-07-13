from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class Netfilter:
    _ARG_COUNTS = {
        "-d": 1,
        "-i": 1,
        "-j": 1,
        "-m": 1,
        "-o": 1,
        "-p": 1,
        "-s": 1,
        "--comment": 1,
        "--ctstate": 1,
        "--dport": 1,
        "--sport": 1,
        "--tcp-flags": 2,
    }
    _FLAG_ARGS = {"--clamp-mss-to-pmtu": 0}
    _IMPLICIT_PROTOCOL_MODULES = {"icmp", "icmpv6", "tcp", "udp"}

    def __init__(self, run: RunCommand, comment_prefix: str) -> None:
        self.run = run
        self.comment_prefix = comment_prefix

    def backend_ok(self) -> bool:
        result = self.run("iptables", "--version", check=False)
        return result.returncode == 0 and "nf_tables" in result.stdout

    def chain_exists(self, family: str, chain: str) -> bool:
        return self.run(family, "-S", chain, check=False).returncode == 0

    def jump_rule(
        self,
        child: str,
        comment: str,
        match: list[str] | None = None,
    ) -> list[str]:
        return [
            *(match or []),
            "-j",
            child,
            "-m",
            "comment",
            "--comment",
            comment,
        ]

    def rule_exists(
        self,
        family: str,
        chain: str,
        rule: list[str],
        table_args: list[str] | None = None,
    ) -> bool:
        return (
            self.run(
                family,
                *(table_args or []),
                "-C",
                chain,
                *rule,
                check=False,
            ).returncode
            == 0
        )

    def chain_rules(
        self,
        family: str,
        chain: str,
        table_args: list[str] | None = None,
    ) -> list[list[str]] | None:
        result = self.run(family, *(table_args or []), "-S", chain, check=False)
        if result.returncode != 0:
            return None
        rules: list[list[str]] = []
        for line in result.stdout.splitlines():
            try:
                arguments = shlex.split(line)
            except ValueError:
                return None
            if len(arguments) >= 2 and arguments[:2] == ["-A", chain]:
                rules.append(arguments[2:])
        return rules

    def chain_matches(
        self,
        family: str,
        chain: str,
        expected: tuple[list[str], ...],
    ) -> bool:
        actual = self.chain_rules(family, chain)
        if actual is None or len(actual) != len(expected):
            return False
        normalized_expected = [self._normalize_rule(rule) for rule in expected]
        normalized_actual = [self._normalize_rule(rule) for rule in actual]
        return (
            None not in normalized_expected
            and None not in normalized_actual
            and normalized_expected == normalized_actual
        )

    def _normalize_rule(
        self,
        rule: list[str],
    ) -> tuple[tuple[str, ...], ...] | None:
        clauses: list[tuple[str, ...]] = []
        jump: tuple[str, ...] | None = None
        protocol: str | None = None
        negate = False
        index = 0
        while index < len(rule):
            token = rule[index]
            if token == "!":
                negate = True
                index += 1
                continue
            if token in self._FLAG_ARGS:
                clauses.append((("!" if negate else ""), token))
                negate = False
                index += 1
                continue
            argc = self._ARG_COUNTS.get(token)
            if argc is None:
                return None
            values = rule[index + 1 : index + 1 + argc]
            if len(values) != argc:
                return None
            prefix = ("!" if negate else "")
            if token == "-p":
                protocol = values[0]
            if token == "--ctstate":
                values = [",".join(sorted(values[0].split(",")))]
            clause = (prefix, token, *values)
            if token == "-j":
                jump = clause
            else:
                clauses.append(clause)
            negate = False
            index += 1 + argc
        if negate or jump is None:
            return None
        if protocol:
            clauses = [
                clause
                for clause in clauses
                if not (
                    len(clause) == 3
                    and clause[0] == ""
                    and clause[1] == "-m"
                    and clause[2] == protocol
                    and protocol in self._IMPLICIT_PROTOCOL_MODULES
                )
            ]
        return tuple(sorted([*clauses, jump]))

    def ensure_chain(self, family: str, chain: str) -> None:
        if not self.chain_exists(family, chain):
            self.run(family, "-N", chain)
        self.run(family, "-F", chain)

    def ensure_jump(
        self,
        family: str,
        parent: str,
        child: str,
        comment: str,
        match: list[str] | None = None,
    ) -> None:
        rule = self.jump_rule(child, comment, match)
        if not self.rule_exists(family, parent, rule):
            self.run(family, "-I", parent, "1", *rule)

    def ensure_rule(
        self,
        family: str,
        table_args: list[str],
        chain: str,
        rule: list[str],
    ) -> None:
        if not self.rule_exists(family, chain, rule, table_args):
            self.run(family, *table_args, "-A", chain, *rule)

    def delete_tagged_rules(
        self,
        family: str,
        chain: str,
        table_args: list[str] | None = None,
    ) -> None:
        table_args = table_args or []
        result = self.run(
            family,
            *table_args,
            "-S",
            chain,
            check=False,
        )
        if result.returncode != 0:
            return
        for line in result.stdout.splitlines():
            try:
                arguments = shlex.split(line)
            except ValueError:
                continue
            if (
                len(arguments) < 3
                or arguments[0] != "-A"
                or arguments[1] != chain
                or not any(
                    value.startswith(self.comment_prefix)
                    for value in arguments
                )
            ):
                continue
            self.run(
                family,
                *table_args,
                "-D",
                chain,
                *arguments[2:],
                check=False,
            )

    def remove_chains(self, family: str, chains: tuple[str, ...]) -> None:
        for chain in chains:
            if not self.chain_exists(family, chain):
                continue
            self.run(family, "-F", chain, check=False)
            self.run(family, "-X", chain, check=False)

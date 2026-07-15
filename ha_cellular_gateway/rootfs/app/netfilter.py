from __future__ import annotations

import shlex

from .command import RunCommand
from .netfilter_normalize import normalize_rule


class Netfilter:
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

    def rule_is_first_unique(
        self,
        family: str,
        chain: str,
        rule: list[str],
        table_args: list[str] | None = None,
    ) -> bool:
        rule_indexes = self._matching_rule_indexes(family, chain, rule, table_args)
        return len(rule_indexes) == 1 and rule_indexes[0] == 0

    def _matching_rule_indexes(
        self,
        family: str,
        chain: str,
        rule: list[str],
        table_args: list[str] | None = None,
    ) -> list[int]:
        actual = self.chain_rules(family, chain, table_args)
        normalized_rule = self._normalize_rule(rule)
        if actual is None or normalized_rule is None:
            return []
        matches: list[int] = []
        for index, actual_rule in enumerate(actual):
            if self._normalize_rule(actual_rule) == normalized_rule:
                matches.append(index)
        return matches

    def _normalize_rule(
        self,
        rule: list[str],
    ) -> tuple[tuple[str, ...], ...] | None:
        return normalize_rule(rule)

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
        rule_indexes = self._matching_rule_indexes(family, parent, rule)
        if rule_indexes == [0]:
            return
        if not rule_indexes or rule_indexes[0] != 0:
            self.run(family, "-I", parent, "1", *rule)
            rule_indexes = self._matching_rule_indexes(family, parent, rule)
        for index in reversed(rule_indexes[1:]):
            self.run(family, "-D", parent, str(index + 1), check=False)

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

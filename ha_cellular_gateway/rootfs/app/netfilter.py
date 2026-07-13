from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


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

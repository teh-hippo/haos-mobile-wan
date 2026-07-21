from __future__ import annotations

import shlex

from .process import Result

ChainKey = tuple[str, str]
RuleCheckKey = tuple[str, tuple[str, ...], tuple[str, ...]]


class FirewallCommandState:
    def __init__(self) -> None:
        self.chain_listings: dict[ChainKey, str] = {}
        self.rule_checks: set[RuleCheckKey] = set()

    def dispatch(self, args: list[str]) -> Result | None:
        if args[:2] == ["iptables", "--version"]:
            return Result(stdout="iptables v1.8.13 (nf_tables)\n")
        family = args[0] if args else ""
        if family not in {"iptables", "ip6tables"}:
            return None
        action_index = 1
        if len(args) >= 3 and args[1] == "-t":
            action_index = 3
        listing = self._listing_result(family, args, action_index)
        if listing is not None:
            return listing
        check = self._rule_check_result(args)
        if check is not None:
            return check
        self._mutate(family, args, action_index)
        return Result()

    def _listing_result(
        self,
        family: str,
        args: list[str],
        action_index: int,
    ) -> Result | None:
        if len(args) <= action_index + 1 or args[action_index] != "-S":
            return None
        chain = args[action_index + 1]
        listing = self.chain_listings.get((family, chain))
        if listing is not None:
            return Result(stdout=listing)
        if (family, chain) in {
            ("iptables", "DOCKER-USER"),
            ("iptables", "INPUT"),
            ("ip6tables", "DOCKER-USER"),
            ("ip6tables", "INPUT"),
        }:
            return Result()
        if chain.startswith("HA_CELL"):
            return Result(returncode=1)
        return None

    def _rule_check_result(self, args: list[str]) -> Result | None:
        if "-C" not in args:
            return None
        index = args.index("-C")
        key = (args[0], tuple(args[1:index]), tuple(args[index + 1 :]))
        if key in self.rule_checks:
            return Result()
        return Result(returncode=1)

    def _mutate(self, family: str, args: list[str], action_index: int) -> None:
        if len(args) <= action_index:
            return
        action = args[action_index]
        command = args[action_index + 1 :]
        if action == "-N" and command:
            self.chain_listings.setdefault((family, command[0]), f"-N {command[0]}")
        elif action == "-F" and command:
            self._flush_chain(family, command[0])
        elif action == "-X" and command:
            self.chain_listings.pop((family, command[0]), None)
        elif action == "-A" and len(command) >= 2:
            self._append_rule(family, command[0], command[1:])
        elif action == "-I" and len(command) >= 3:
            self._insert_rule(family, command[0], int(command[1]), command[2:])
        elif action == "-D" and len(command) >= 1:
            self._delete_rule(family, command[0], command[1:])

    def _chain_lines(self, family: str, chain: str) -> list[str]:
        listing = self.chain_listings.get((family, chain))
        return [] if not listing else listing.splitlines()

    def _set_chain_lines(self, family: str, chain: str, lines: list[str]) -> None:
        self.chain_listings[(family, chain)] = "\n".join(lines)

    def _append_rule(self, family: str, chain: str, rule: list[str]) -> None:
        lines = self._chain_lines(family, chain)
        lines.append(self._rule_line(chain, rule))
        self._set_chain_lines(family, chain, lines)

    def _insert_rule(
        self,
        family: str,
        chain: str,
        position: int,
        rule: list[str],
    ) -> None:
        lines = self._chain_lines(family, chain)
        header = 1 if lines[:1] == [f"-N {chain}"] else 0
        insert_at = min(header + max(position - 1, 0), len(lines))
        lines.insert(insert_at, self._rule_line(chain, rule))
        self._set_chain_lines(family, chain, lines)

    def _delete_rule(self, family: str, chain: str, spec: list[str]) -> None:
        lines = self._chain_lines(family, chain)
        rule_indexes = [
            index for index, line in enumerate(lines) if line.startswith(f"-A {chain} ")
        ]
        if not rule_indexes:
            return
        if len(spec) == 1 and spec[0].isdigit():
            position = int(spec[0])
            if 1 <= position <= len(rule_indexes):
                del lines[rule_indexes[position - 1]]
                self._set_chain_lines(family, chain, lines)
            return
        target = self._rule_line(chain, spec)
        for index in rule_indexes:
            if lines[index] == target:
                del lines[index]
                self._set_chain_lines(family, chain, lines)
                return

    def _flush_chain(self, family: str, chain: str) -> None:
        lines = self._chain_lines(family, chain)
        if lines[:1] == [f"-N {chain}"]:
            self._set_chain_lines(family, chain, [lines[0]])
            return
        self._set_chain_lines(family, chain, [])

    @staticmethod
    def _rule_line(chain: str, rule: list[str]) -> str:
        return shlex.join(["-A", chain, *rule])

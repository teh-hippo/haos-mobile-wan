from __future__ import annotations

ARG_COUNTS = {
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
FLAG_ARGS = {"--clamp-mss-to-pmtu": 0}
IMPLICIT_PROTOCOL_MODULES = {"icmp", "icmpv6", "tcp", "udp"}


def normalize_rule(rule: list[str]) -> tuple[tuple[str, ...], ...] | None:
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
        if token in FLAG_ARGS:
            clauses.append((("!" if negate else ""), token))
            negate = False
            index += 1
            continue
        argc = ARG_COUNTS.get(token)
        if argc is None:
            return None
        values = rule[index + 1 : index + 1 + argc]
        if len(values) != argc:
            return None
        prefix = "!" if negate else ""
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
                and protocol in IMPLICIT_PROTOCOL_MODULES
            )
        ]
    return tuple(sorted([*clauses, jump]))

"""Check the release dispatch inputs against the channel being published.

This ran as an inline script inside the release workflow, where neither ruff,
mypy nor the test suite could see it, despite being the gate that decides
whether a stable release may proceed.
"""

from __future__ import annotations

import os
import sys

from tools.app_metadata import version as config_version
from tools.release_contract import ContractError, is_beta_version, parse_version

BETA_REQUIRED = "Beta releases require a -beta.N version"
STABLE_REJECTS_BETA = "Stable releases cannot use a beta version"
ACCEPTANCE_REQUIRED = "Stable releases require an acceptance reference"


def dispatch_errors(
    *,
    channel: str,
    requested: str,
    acceptance_reference: str,
    declared: str,
) -> list[str]:
    try:
        parse_version(requested)
    except ContractError as error:
        return [str(error)]

    errors: list[str] = []
    beta = is_beta_version(requested)
    if channel == "beta" and not beta:
        errors.append(BETA_REQUIRED)
    if channel == "stable" and beta:
        errors.append(STABLE_REJECTS_BETA)
    if channel == "stable" and not acceptance_reference.strip():
        errors.append(ACCEPTANCE_REQUIRED)
    if declared != requested:
        errors.append(
            f"Input version {requested} does not match "
            f"ha_cellular_gateway/config.yaml version {declared}"
        )
    return errors


def main() -> int:
    errors = dispatch_errors(
        channel=os.environ["CHANNEL"],
        requested=os.environ["VERSION"],
        acceptance_reference=os.environ.get("ACCEPTANCE_REFERENCE", ""),
        declared=config_version(),
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release dispatch inputs accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

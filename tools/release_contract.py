from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

CONFIG_PATH = "ha_cellular_gateway/config.yaml"
CHANGELOG_PATH = Path("ha_cellular_gateway/CHANGELOG.md")
STABLE_IMAGE = "ghcr.io/teh-hippo/haos-mobile-wan"
RELEASE_FILES = {
    CONFIG_PATH,
    "ha_cellular_gateway/Dockerfile",
    "ha_cellular_gateway/apparmor.txt",
}
RELEASE_PREFIXES = (
    "ha_cellular_gateway/rootfs/",
    "ha_cellular_gateway/translations/",
)
VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-beta\.(0|[1-9]\d*))?$"
)


class ContractError(ValueError):
    pass


def parse_version(value: str) -> tuple[int, int, int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ContractError(f"Invalid semantic version: {value}")
    beta = match.group(4)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        1 if beta is None else 0,
        int(beta or 0),
    )


def is_beta_version(value: str) -> bool:
    return parse_version(value)[3] == 0


def config_data(text: str) -> dict[str, object]:
    data: object = yaml.safe_load(text)
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise ContractError(f"{CONFIG_PATH} must contain an object")
    return {key: value for key, value in data.items() if isinstance(key, str)}


def config_version(text: str) -> str:
    version = config_data(text).get("version")
    if not isinstance(version, str):
        raise ContractError(f"{CONFIG_PATH} must contain a string version")
    return version


def stable_release_errors(config: dict[str, object]) -> list[str]:
    version = config.get("version")
    if not isinstance(version, str):
        raise ContractError(f"{CONFIG_PATH} must contain a string version")
    parsed = parse_version(version)
    if parsed[0] < 1 or parsed[3] == 0:
        return []

    errors: list[str] = []
    if config.get("stage", "stable") != "stable":
        errors.append("Stable releases require stage: stable")
    if config.get("image") != STABLE_IMAGE:
        errors.append(f"Stable releases require image: {STABLE_IMAGE}")
    return errors


def is_release_file(path: str) -> bool:
    return path in RELEASE_FILES or path.startswith(RELEASE_PREFIXES)


def validate_contract(
    *,
    base_version: str,
    current_version: str,
    changed_files: list[str],
    changelog: str,
    tags: set[str],
) -> list[str]:
    base = parse_version(base_version)
    current = parse_version(current_version)
    version_changed = current != base
    version_increased = current > base
    release_changed = any(is_release_file(path) for path in changed_files)
    errors: list[str] = []

    if current < base:
        errors.append(f"App version decreased from {base_version} to {current_version}")
    if release_changed and not version_changed:
        errors.append(
            f"Release payload changed without increasing {CONFIG_PATH} from {base_version}"
        )
    if version_increased and f"v{current_version}" in tags:
        errors.append(f"Version v{current_version} already has a Git tag")
    if version_increased and not re.search(
        rf"^## {re.escape(current_version)}$",
        changelog,
        re.MULTILINE,
    ):
        errors.append(f"{CHANGELOG_PATH} needs a ## {current_version} heading")
    return errors


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _base_file(base: str, path: str) -> str:
    return _git("show", f"{base}:{path}")


def main() -> int:
    if len(sys.argv) != 2:
        raise ContractError("Usage: release_contract.py BASE_COMMIT")
    base = sys.argv[1]
    current_text = Path(CONFIG_PATH).read_text(encoding="utf-8")
    current_config = config_data(current_text)
    changed_files = _git(
        "diff",
        "--name-only",
        f"{base}...HEAD",
    ).splitlines()
    errors = validate_contract(
        base_version=config_version(_base_file(base, CONFIG_PATH)),
        current_version=config_version(current_text),
        changed_files=changed_files,
        changelog=CHANGELOG_PATH.read_text(encoding="utf-8"),
        tags=set(_git("tag", "--list", "v*").splitlines()),
    )
    errors.extend(stable_release_errors(current_config))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

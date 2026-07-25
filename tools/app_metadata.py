"""Read the published add-on metadata.

Workflows need the app version in several places. Reading it here keeps that
lookup linted, type-checked and tested rather than repeated inline in YAML.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

CONFIG_PATH = Path("ha_cellular_gateway/config.yaml")


class MetadataError(ValueError):
    pass


def config(path: Path = CONFIG_PATH) -> dict[str, object]:
    data: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MetadataError(f"{path} must contain an object")
    return {key: value for key, value in data.items() if isinstance(key, str)}


def version(path: Path = CONFIG_PATH) -> str:
    value = config(path).get("version")
    if not isinstance(value, str):
        raise MetadataError(f"{path} must contain a string version")
    return value


def main() -> int:
    try:
        print(version())
    except (MetadataError, OSError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

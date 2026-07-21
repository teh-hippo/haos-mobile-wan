from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG_PATH = Path("ha_cellular_gateway/CHANGELOG.md")
HEADING_PATTERN = re.compile(r"^## (?P<version>\S+)\s*$", re.MULTILINE)


class ReleaseNotesError(ValueError):
    pass


def extract_section(changelog: str, version: str) -> str:
    heading = f"## {version}"
    for match in HEADING_PATTERN.finditer(changelog):
        if match.group("version") != version:
            continue
        start = match.end()
        next_match = HEADING_PATTERN.search(changelog, start)
        end = next_match.start() if next_match else len(changelog)
        return changelog[start:end].strip("\n")
    raise ReleaseNotesError(f"{heading} heading not found in changelog")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: release_notes.py VERSION", file=sys.stderr)
        return 2
    version = argv[1]
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    try:
        section = extract_section(changelog, version)
    except ReleaseNotesError as error:
        print(error, file=sys.stderr)
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

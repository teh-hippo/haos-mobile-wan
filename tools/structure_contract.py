from __future__ import annotations

from pathlib import Path

BUDGETS = (
    ("runtime", Path("ha_cellular_gateway/rootfs/app"), "*.py", 250),
    ("unit test", Path("ha_cellular_gateway/tests"), "test_*.py", 400),
    ("test support", Path("ha_cellular_gateway/tests"), "*_support.py", 300),
    (
        "test support",
        Path("ha_cellular_gateway/tests/test_support"),
        "*.py",
        400,
    ),
    (
        "NetworkManager lab",
        Path("ha_cellular_gateway/integration/networkmanager"),
        "*.py",
        350,
    ),
    (
        "QEMU guest lab",
        Path("ha_cellular_gateway/integration/networkmanager_wifi/guest"),
        "*.py",
        300,
    ),
)


def violations(root: Path = Path(".")) -> list[str]:
    errors: list[str] = []
    for label, directory, pattern, maximum in BUDGETS:
        for path in sorted((root / directory).glob(pattern)):
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            if line_count > maximum:
                errors.append(
                    f"{path.relative_to(root)} has {line_count} lines; "
                    f"{label} limit is {maximum}"
                )
    return errors


def main() -> int:
    errors = violations()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Structure contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

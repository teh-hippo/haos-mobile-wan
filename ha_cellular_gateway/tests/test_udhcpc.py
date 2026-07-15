from __future__ import annotations

import fcntl
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rootfs.app.udhcpc import (
    ERROR_NAME,
    LEASE_NAME,
    LOCK_NAME,
    handle_event,
)


class FakeIp:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.commands: list[list[str]] = []
        self.locked: list[bool] = []
        self.fail_add = False
        self.fail_delete = False
        self.addresses: set[str] = set()

    def __call__(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 5,
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        self.commands.append(args)
        with (self.run_dir / LOCK_NAME).open("a+", encoding="utf-8") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.locked.append(True)
            else:
                self.locked.append(False)
                fcntl.flock(probe, fcntl.LOCK_UN)
        operation = args[3] if args[:3] == ["ip", "-4", "address"] else ""
        returncode = int(
            (self.fail_add and operation == "add")
            or (self.fail_delete and operation == "del")
        )
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, args)
        stdout = ""
        if args[1:5] == ["-4", "-j", "address", "show"]:
            stdout = json.dumps(
                [
                    {
                        "addr_info": [
                            {
                                "family": "inet",
                                "local": address.rsplit("/", 1)[0],
                                "prefixlen": int(address.rsplit("/", 1)[1]),
                            }
                            for address in sorted(self.addresses)
                        ]
                    }
                ]
            )
        elif returncode == 0 and operation in {"add", "replace"}:
            self.addresses.add(args[4])
        elif returncode == 0 and operation == "del":
            self.addresses.discard(args[4])
        return subprocess.CompletedProcess(args, returncode, stdout, "")


class UdhcpcHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name)
        self.run = FakeIp(self.run_dir)
        self.environment = {
            "interface": "eth0",
            "ip": "172.20.10.2",
            "subnet": "255.255.255.240",
            "router": "172.20.10.1",
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    @property
    def lease_path(self) -> Path:
        return self.run_dir / LEASE_NAME

    @property
    def error_path(self) -> Path:
        return self.run_dir / ERROR_NAME

    def _event(self, event: str, environment=None) -> None:
        handle_event(
            event,
            environment=environment or self.environment,
            run_dir=self.run_dir,
            run=self.run,
        )

    def test_bound_adds_address_and_publishes_owned_lease(self) -> None:
        self.error_path.write_text("stale error", encoding="utf-8")
        self._event("bound")

        self.assertEqual(
            json.loads(self.lease_path.read_text(encoding="utf-8")),
            {
                "owner": "app",
                "interface": "eth0",
                "address": "172.20.10.2/28",
                "gateway": "172.20.10.1",
            },
        )
        self.assertEqual(
            self.run.commands,
            [
                [
                    "ip",
                    "-4",
                    "address",
                    "add",
                    "172.20.10.2/28",
                    "dev",
                    "eth0",
                ]
            ],
        )
        self.assertTrue(all(self.run.locked))
        self.assertFalse(self.error_path.exists())
        self.assertFalse(
            self.lease_path.with_name(f".{LEASE_NAME}.tmp").exists()
        )

    def test_renew_replaces_only_the_owned_address(self) -> None:
        self._event("bound")
        self.run.commands.clear()
        self.run.locked.clear()

        self._event("renew")

        self.assertEqual(
            self.run.commands,
            [
                [
                    "ip",
                    "-4",
                    "address",
                    "replace",
                    "172.20.10.2/28",
                    "dev",
                    "eth0",
                ]
            ],
        )
        self.assertTrue(all(self.run.locked))

    def test_deconfig_removes_only_the_recorded_address(self) -> None:
        self._event("bound")
        self.run.commands.clear()

        self._event("deconfig", {"interface": "eth0"})

        self.assertFalse(self.lease_path.exists())
        self.assertEqual(
            self.run.commands,
            [
                [
                    "ip",
                    "-4",
                    "address",
                    "del",
                    "172.20.10.2/28",
                    "dev",
                    "eth0",
                ]
            ],
        )

    def test_failed_address_add_does_not_claim_the_lease(self) -> None:
        self.run.fail_add = True

        with self.assertRaises(subprocess.CalledProcessError):
            self._event("bound")

        self.assertFalse(self.lease_path.exists())
        self.assertEqual(
            self.error_path.read_text(encoding="utf-8"),
            "iPhone USB DHCP address configuration failed",
        )

    def test_failed_address_delete_preserves_ownership_record(self) -> None:
        self._event("bound")
        self.run.commands.clear()
        self.run.fail_delete = True

        with self.assertRaises(subprocess.CalledProcessError):
            self._event("deconfig", {"interface": "eth0"})

        self.assertTrue(self.lease_path.exists())
        self.assertIn("172.20.10.2/28", self.run.addresses)
        self.assertEqual(
            [command[3] for command in self.run.commands],
            ["del", "address"],
        )
        self.assertEqual(
            self.error_path.read_text(encoding="utf-8"),
            "iPhone USB DHCP address configuration failed",
        )

    def test_invalid_renewal_cleans_the_previous_owned_address(self) -> None:
        self._event("bound")
        self.run.commands.clear()
        environment = dict(self.environment)
        environment["router"] = ""

        with self.assertRaisesRegex(ValueError, "has no gateway"):
            self._event("renew", environment)

        self.assertFalse(self.lease_path.exists())
        self.assertEqual(
            self.error_path.read_text(encoding="utf-8"),
            "iPhone USB DHCP lease has no gateway",
        )
        self.assertEqual(
            self.run.commands,
            [
                [
                    "ip",
                    "-4",
                    "address",
                    "del",
                    "172.20.10.2/28",
                    "dev",
                    "eth0",
                ]
            ],
        )


if __name__ == "__main__":
    unittest.main()

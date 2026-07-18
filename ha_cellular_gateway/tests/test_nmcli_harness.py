from __future__ import annotations

import subprocess
import unittest

from integration.networkmanager.nmcli_harness import (
    SYNTHETIC_DEVICE_IDENTITY,
    NmcliHarnessRunner,
)


class RecordingCommandRunner:
    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        self.calls: list[tuple[list[str], bool, int]] = []

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, check, timeout))
        return self.result


class NmcliHarnessRunnerTests(unittest.TestCase):
    def test_missing_veth_path_is_replaced_without_changing_other_fields(self) -> None:
        args = [
            "nmcli",
            "-g",
            "GENERAL.PATH,GENERAL.STATE,GENERAL.CON-UUID",
            "device",
            "show",
            "nmwan0",
        ]
        delegate = RecordingCommandRunner(
            subprocess.CompletedProcess(
                args,
                0,
                "--\n100 (connected)\nforeign-uuid\n",
                "",
            )
        )

        result = NmcliHarnessRunner(delegate).run(args)

        self.assertEqual(result.stdout, f"{SYNTHETIC_DEVICE_IDENTITY}\n100 (connected)\nforeign-uuid\n")
        self.assertEqual(delegate.calls, [(args, True, 20)])

    def test_existing_path_and_all_other_commands_delegate_unchanged(self) -> None:
        path_read = [
            "nmcli",
            "-g",
            "GENERAL.PATH",
            "device",
            "show",
            "nmwan0",
        ]
        delegate = RecordingCommandRunner(
            subprocess.CompletedProcess(path_read, 0, "/org/freedesktop/NetworkManager/Devices/7\n", "")
        )
        runner = NmcliHarnessRunner(delegate)

        result = runner.run(path_read, check=False, timeout=8)
        mutation = ["nmcli", "device", "set", "nmwan0", "autoconnect", "no"]
        delegate.result = subprocess.CompletedProcess(mutation, 0, "", "")
        mutation_result = runner.run(mutation)

        self.assertEqual(
            result.stdout,
            "/org/freedesktop/NetworkManager/Devices/7\n",
        )
        self.assertEqual(mutation_result.args, mutation)
        self.assertEqual(
            delegate.calls,
            [(path_read, False, 8), (mutation, True, 20)],
        )

    def test_only_exact_radio_read_is_synthetic(self) -> None:
        radio = ["nmcli", "-g", "WIFI-HW,WIFI", "radio"]
        delegate = RecordingCommandRunner(
            subprocess.CompletedProcess(radio, 1, "", "no wireless hardware")
        )
        runner = NmcliHarnessRunner(delegate)

        result = runner.run(radio)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "enabled\nenabled\n")
        self.assertEqual(delegate.calls, [])

        nearby_read = ["nmcli", "-g", "WIFI-HW,WIFI", "radio", "all"]
        delegate.result = subprocess.CompletedProcess(
            nearby_read,
            1,
            "",
            "unsupported query",
        )
        nearby_result = runner.run(nearby_read, check=False)

        self.assertEqual(nearby_result.returncode, 1)
        self.assertEqual(nearby_result.stderr, "unsupported query")
        self.assertEqual(delegate.calls, [(nearby_read, False, 20)])


if __name__ == "__main__":
    unittest.main()

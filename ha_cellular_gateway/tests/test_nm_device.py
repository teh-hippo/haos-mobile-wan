from __future__ import annotations

import subprocess
import unittest

from rootfs.app.nm_device import RadioInspectionError, radio_state


class StubRun:
    def __init__(self, results: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        returncode, stdout = self.results.get(args, (1, ""))
        return subprocess.CompletedProcess(args, returncode, stdout, "")


class RadioStateTests(unittest.TestCase):
    def test_legacy_split_lines_misclassifies_real_combined_output(self) -> None:
        values = "enabled:enabled\n".splitlines()
        enabled = {"enabled", "yes", "true", "1"}

        hardware = values[0].lower() in enabled
        software = values[1].lower() in enabled if len(values) > 1 else False

        self.assertFalse(hardware)
        self.assertFalse(software)

    def test_reads_hardware_and_software_as_separate_scalars(self) -> None:
        run = StubRun(
            {
                ("nmcli", "-g", "WIFI-HW", "radio"): (0, "enabled\n"),
                ("nmcli", "-g", "WIFI", "radio"): (0, "disabled\n"),
            }
        )

        self.assertEqual(radio_state(run), (False, True))
        self.assertEqual(
            run.commands,
            [
                ("nmcli", "-g", "WIFI-HW", "radio"),
                ("nmcli", "-g", "WIFI", "radio"),
            ],
        )

    def test_failed_missing_and_unknown_values_are_unavailable(self) -> None:
        cases = (
            (1, ""),
            (0, ""),
            (0, "missing\n"),
            (0, "enabled\ndisabled\n"),
        )
        for returncode, stdout in cases:
            with self.subTest(returncode=returncode, stdout=stdout):
                run = StubRun(
                    {
                        ("nmcli", "-g", "WIFI-HW", "radio"): (
                            returncode,
                            stdout,
                        )
                    }
                )
                with self.assertRaises(RadioInspectionError):
                    radio_state(run)


if __name__ == "__main__":
    unittest.main()

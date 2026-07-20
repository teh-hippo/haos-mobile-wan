"""USB/iPhone (``idevice_id``/``idevicepair``) command state."""

from __future__ import annotations

from .process import Result


class UsbCommandState:
    def __init__(self) -> None:
        self.idevice_udids: list[str] = []
        self.idevice_paired_udids: list[str] = []
        self.idevice_pair_result = Result(
            returncode=1, stdout="ERROR: Please accept the trust dialog\n"
        )
        self.idevice_validate_result = Result(
            returncode=1, stdout="ERROR: Device is not paired\n"
        )

    def dispatch(self, args: list[str]) -> Result | None:
        if args[:2] == ["idevice_id", "--list"]:
            return Result(
                stdout="\n".join(self.idevice_udids)
                + ("\n" if self.idevice_udids else "")
            )
        if args[:2] == ["idevicepair", "list"]:
            return Result(
                stdout="\n".join(self.idevice_paired_udids)
                + ("\n" if self.idevice_paired_udids else "")
            )
        if args and args[0] == "idevicepair" and "--udid" in args:
            if args[-1] == "validate":
                return self.idevice_validate_result
            if args[-1] == "pair":
                return self.idevice_pair_result
        return None

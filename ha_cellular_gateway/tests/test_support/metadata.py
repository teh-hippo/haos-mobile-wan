"""In-memory NetworkManager Wi-Fi profile metadata double."""

from __future__ import annotations


class FakeWifiProfileMetadata:
    """In-memory stand-in for the app Wi-Fi profile's NetworkManager metadata."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.data.get(key)

    def write(self, key: str, value: str) -> None:
        self.data[key] = value

    def clear(self, key: str) -> None:
        self.data.pop(key, None)

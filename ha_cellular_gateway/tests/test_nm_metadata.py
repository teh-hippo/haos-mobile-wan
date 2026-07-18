from __future__ import annotations

import types
import unittest
from unittest import mock

from rootfs.app import nm_metadata
from rootfs.app.errors import GatewayError
from rootfs.app.nm_metadata import (
    METADATA_UNAVAILABLE,
    PROFILE_MISSING,
    DbusWifiProfileMetadata,
)

INVALID_CONNECTION = "org.freedesktop.NetworkManager.Settings.InvalidConnection"
PERMISSION_DENIED = "org.freedesktop.NetworkManager.PermissionDenied"
TRANSPORT_ERROR = "org.freedesktop.DBus.Error.NoServer"
UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a03"


class FakeDBusException(Exception):
    """Stand-in for ``dbus.exceptions.DBusException`` with a wire error name."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._name = name

    def get_dbus_name(self) -> str:
        return self._name


class FakeSettingsObject:
    def __init__(self, bus: "FakeBus") -> None:
        self._bus = bus

    def GetConnectionByUuid(self, uuid: str, dbus_interface: str | None = None):
        if self._bus.lookup_error is not None:
            raise self._bus.lookup_error
        return "/org/freedesktop/NetworkManager/Settings/1"


class FakeConnectionObject:
    def __init__(self, bus: "FakeBus") -> None:
        self._bus = bus

    def GetSettings(self, dbus_interface: str | None = None):
        return self._bus.payload

    def Update(self, settings, dbus_interface: str | None = None) -> None:
        self._bus.updated = settings


class FakeBus:
    def __init__(self, *, lookup_error: Exception | None = None) -> None:
        self.lookup_error = lookup_error
        self.payload: dict = {"user": {"data": {"marker": "value"}}}
        self.updated = None
        self.closed = False

    def get_object(self, service: str, path: str):
        if path == nm_metadata.NM_SETTINGS_PATH:
            return FakeSettingsObject(self)
        return FakeConnectionObject(self)

    def close(self) -> None:
        self.closed = True


def make_dbus(bus_factory):
    """Build a fake ``dbus`` module exposing only what the store touches."""
    module = types.SimpleNamespace()
    module.bus = types.SimpleNamespace(BusConnection=bus_factory)
    module.exceptions = types.SimpleNamespace(DBusException=FakeDBusException)
    module.Dictionary = lambda data, signature=None: dict(data)
    return module


class NmMetadataTests(unittest.TestCase):
    def test_bus_connect_failure_becomes_metadata_unavailable(self) -> None:
        def factory(address: str):
            raise FakeDBusException(TRANSPORT_ERROR)

        store = DbusWifiProfileMetadata(UUID)
        with mock.patch.object(nm_metadata, "_dbus", lambda: make_dbus(factory)):
            for action in (
                lambda: store.read("marker"),
                lambda: store.write("marker", "value"),
                lambda: store.clear("marker"),
            ):
                with self.assertRaises(GatewayError) as ctx:
                    action()
                self.assertEqual(str(ctx.exception), METADATA_UNAVAILABLE)
                self.assertIsInstance(ctx.exception.__cause__, FakeDBusException)

    def test_invalid_connection_is_the_only_missing_profile(self) -> None:
        buses: list[FakeBus] = []

        def factory(address: str) -> FakeBus:
            bus = FakeBus(lookup_error=FakeDBusException(INVALID_CONNECTION))
            buses.append(bus)
            return bus

        store = DbusWifiProfileMetadata(UUID)
        with mock.patch.object(nm_metadata, "_dbus", lambda: make_dbus(factory)):
            self.assertIsNone(store.read("marker"))
            store.clear("marker")  # missing_ok path must swallow the absence
            with self.assertRaises(GatewayError) as ctx:
                store.write("marker", "value")

        self.assertEqual(str(ctx.exception), PROFILE_MISSING)
        self.assertTrue(all(bus.closed for bus in buses))

    def test_permission_and_transport_errors_convert_not_missing(self) -> None:
        for name in (PERMISSION_DENIED, TRANSPORT_ERROR):
            with self.subTest(error=name):
                buses: list[FakeBus] = []

                def factory(address: str, name: str = name) -> FakeBus:
                    bus = FakeBus(lookup_error=FakeDBusException(name))
                    buses.append(bus)
                    return bus

                store = DbusWifiProfileMetadata(UUID)
                with mock.patch.object(
                    nm_metadata, "_dbus", lambda: make_dbus(factory)
                ):
                    for action in (
                        lambda: store.read("marker"),
                        lambda: store.write("marker", "value"),
                        lambda: store.clear("marker"),
                    ):
                        with self.assertRaises(GatewayError) as ctx:
                            action()
                        self.assertEqual(str(ctx.exception), METADATA_UNAVAILABLE)

                self.assertTrue(buses)
                self.assertTrue(all(bus.closed for bus in buses))


if __name__ == "__main__":
    unittest.main()

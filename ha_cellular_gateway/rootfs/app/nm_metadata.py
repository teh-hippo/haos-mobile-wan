from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol

from .errors import GatewayError

NM_SERVICE = "org.freedesktop.NetworkManager"
NM_SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
NM_SETTINGS_INTERFACE = "org.freedesktop.NetworkManager.Settings"
NM_CONNECTION_INTERFACE = "org.freedesktop.NetworkManager.Settings.Connection"

USER_SETTING = "user"
USER_DATA_PROPERTY = "data"

INVALID_CONNECTION_ERROR = "org.freedesktop.NetworkManager.Settings.InvalidConnection"

HAOS_SYSTEM_BUS = "unix:path=/run/dbus/system_bus_socket"

PROFILE_MISSING = "NetworkManager cannot find the app Wi-Fi profile"
METADATA_UNAVAILABLE = "NetworkManager profile metadata is unavailable"


def system_bus_address() -> str:
    return os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or HAOS_SYSTEM_BUS


class WifiProfileMetadata(Protocol):
    def read(self, key: str) -> str | None: ...

    def write(self, key: str, value: str) -> None: ...

    def clear(self, key: str) -> None: ...


def _dbus() -> Any:
    import dbus

    return dbus


class DbusWifiProfileMetadata:
    def __init__(
        self,
        uuid: str,
        *,
        address: Callable[[], str] = system_bus_address,
    ) -> None:
        self.uuid = uuid
        self._address = address

    def read(self, key: str) -> str | None:
        dbus = _dbus()
        bus = None
        try:
            bus = dbus.bus.BusConnection(self._address())
            path = self._connection_path(bus, missing_ok=True)
            if path is None:
                return None
            settings = self._get_settings(bus, path)
            data = settings.get(USER_SETTING, {}).get(USER_DATA_PROPERTY, {})
            value = data.get(key)
            return None if value is None else str(value)
        except dbus.exceptions.DBusException as error:
            raise GatewayError(METADATA_UNAVAILABLE) from error
        finally:
            if bus is not None:
                bus.close()

    def write(self, key: str, value: str) -> None:
        self._apply(lambda data: data.__setitem__(key, value), missing_ok=False)

    def clear(self, key: str) -> None:
        self._apply(lambda data: data.pop(key, None), missing_ok=True)

    def _apply(
        self,
        mutate: Callable[[dict[str, str]], object],
        *,
        missing_ok: bool,
    ) -> None:
        dbus = _dbus()
        bus = None
        try:
            bus = dbus.bus.BusConnection(self._address())
            path = self._connection_path(bus, missing_ok=missing_ok)
            if path is None:
                return
            settings = self._get_settings(bus, path)
            user = dict(settings.get(USER_SETTING, {}))
            data = {str(k): str(v) for k, v in user.get(USER_DATA_PROPERTY, {}).items()}
            before = dict(data)
            mutate(data)
            if data == before:
                return
            self._store_user_data(settings, user, data)
            connection = bus.get_object(NM_SERVICE, path)
            connection.Update(settings, dbus_interface=NM_CONNECTION_INTERFACE)
        except dbus.exceptions.DBusException as error:
            raise GatewayError(METADATA_UNAVAILABLE) from error
        finally:
            if bus is not None:
                bus.close()

    @staticmethod
    def _store_user_data(
        settings: Any, user: dict[str, Any], data: dict[str, str]
    ) -> None:
        dbus = _dbus()
        user[USER_DATA_PROPERTY] = dbus.Dictionary(data, signature="ss")
        settings[USER_SETTING] = dbus.Dictionary(user, signature="sv")

    @staticmethod
    def _get_settings(bus: Any, path: Any) -> Any:
        connection = bus.get_object(NM_SERVICE, path)
        return connection.GetSettings(dbus_interface=NM_CONNECTION_INTERFACE)

    def _connection_path(self, bus: Any, *, missing_ok: bool) -> Any:
        dbus = _dbus()
        settings = bus.get_object(NM_SERVICE, NM_SETTINGS_PATH)
        try:
            return settings.GetConnectionByUuid(
                self.uuid, dbus_interface=NM_SETTINGS_INTERFACE
            )
        except dbus.exceptions.DBusException as error:
            if error.get_dbus_name() != INVALID_CONNECTION_ERROR:
                raise
            if missing_ok:
                return None
            raise GatewayError(PROFILE_MISSING) from None

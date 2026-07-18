WIFI_HOTSPOT = "wifi_hotspot"
IPHONE_USB = "iphone_usb"
IPHONE_USB_WIFI_FALLBACK = "iphone_usb_wifi_fallback"

MOBILE_CONNECTIONS = frozenset(
    {
        WIFI_HOTSPOT,
        IPHONE_USB,
        IPHONE_USB_WIFI_FALLBACK,
    }
)

DEFAULT_MOBILE_CONNECTION_OPTION = "Wi-Fi hotspot"
MOBILE_CONNECTION_OPTIONS = {
    DEFAULT_MOBILE_CONNECTION_OPTION: WIFI_HOTSPOT,
    "USB (iPhone)": IPHONE_USB,
    "USB (iPhone), Wi-Fi fallback": IPHONE_USB_WIFI_FALLBACK,
}

LEGACY_WIFI_MANUAL = "manual"
LEGACY_WIFI_MIGRATE_MATCHING = "migrate_matching"
LEGACY_WIFI_MIGRATION_OPTIONS = {
    "Manual cleanup": LEGACY_WIFI_MANUAL,
    "Migrate matching Supervisor profile": LEGACY_WIFI_MIGRATE_MATCHING,
}

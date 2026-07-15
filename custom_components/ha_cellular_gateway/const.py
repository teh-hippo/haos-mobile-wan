from homeassistant.const import Platform


DOMAIN = "ha_cellular_gateway"
CONF_TOKEN = "token"
DEFAULT_NAME = "HAOS Mobile WAN"
PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
)

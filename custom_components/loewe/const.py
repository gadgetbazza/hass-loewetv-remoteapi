"""Constants for Loewe TV integration."""

from homeassistant.const import Platform

DOMAIN = "loewe"

CONF_HOST = "host"
CONF_RESOURCE_PATH = "resource_path"
CONF_CLIENT_ID = "client_id"
CONF_DEVICE_UUID = "device_uuid"  # Actually contains the client MAC, not UUID.
CONF_FCID = "fcid"
CONF_TV_MAC = "tv_mac"

DEFAULT_RESOURCE_PATH = "/loewe_tablet_0001"
DEFAULT_POLL_INTERVAL = 10

# Remote control key codes (based on Loewe RC spec)
LOEWE_RC_CODES: dict[str, int] = {
    "pip": 10,
    "menu": 11,
    "power": 12,      # ON_OFF
    "mute": 13,
    "epg": 15,
    "right": 16,
    "left": 17,
    "vol_down": 20,
    "vol_up": 21,
    "power_on": 22,
    "prog_down": 23,
    "prog_up": 24,
    "power_off": 25,
    "green": 26,
    "red": 27,
    "up": 32,
    "down": 33,
    "pic": 35,
    "ok": 38,
    "blue": 40,
    "yellow": 43,
    "media": 49,      # Home
    "radio": 53,
    "ttx": 60,
    "end": 63,        # Back
    "sound": 64,
    "back": 65,
    "info": 79,
    "aspect": 90,
    "timer": 91,
    "av1": 114,
    "av2": 115,
    "av3": 116,
    "avs": 117,
    "vga": 118,
    "hdmi1": 119,
    "comp": 120,
    "hdmi2": 121,
    "hdmi3": 122,
    "hdmi4": 123,
    "video": 124,
    "spdif_in": 125,
}

# Platforms supported by this integration
PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.BUTTON,
    Platform.SENSOR,
]

# SOAP core constants
SOAP_BASE_URL = "http://{host}:905/loewe_tablet_0001"
SOAP_SERVICE = "urn:loewe.de:RemoteTV:Tablet"
SOAP_PREFIX = "ltv"

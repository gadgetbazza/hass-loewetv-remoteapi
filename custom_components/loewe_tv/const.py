"""Constants for Loewe TV integration."""

from homeassistant.const import Platform

DOMAIN = "loewe_tv"

CONF_HOST = "host"
CONF_RESOURCE_PATH = "resource_path"
CONF_CLIENT_ID = "client_id"
CONF_DEVICE_UUID = "device_uuid"
CONF_FCID = "fcid"
CONF_TV_MAC = "tv_mac"

DEFAULT_RESOURCE_PATH = "/loewe_tablet_0001"

# Remote control key codes (partial set)
RC_KEY_POWER_OFF = 25
RC_KEY_POWER_ON = 22

# Platforms supported by this integration
PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]

# ---------- SOAP endpoint definitions ----------
SOAP_ENDPOINTS = {
    # Pairing
    "RequestAccess": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "RequestAccess",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },

    # Device
    "GetDeviceData": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetDeviceData",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    
    # Status
    "GetCurrentStatus": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetCurrentStatus",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },

    # Playback
    "GetCurrentPlayback": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetCurrentPlayback",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    
    # Sources/Channels
    "GetListOfChannelLists": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetListOfChannelLists",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    "GetChannelList": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetChannelList",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    "ZapToMedia": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "ZapToMedia",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    # Volume
    "GetVolume": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetVolume",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    "SetVolume": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "SetVolume",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },

    # Mute
    "GetMute": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "GetMute",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },
    "SetMute": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "SetMute",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",
    },

    # Remote keys
    "InjectRCKey": {
        "url": "http://{host}:905/loewe_tablet_0001",
        "soap_action": "InjectRCKey",
        "service": "urn:loewe.de:RemoteTV:Tablet",
        "mode": "soap_xml_new",
        "prefix": "ltv",  # can adjust later if we discover u:/m:
    },
}

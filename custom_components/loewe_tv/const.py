"""Constants for the Loewe TV Remote API integration."""

from __future__ import annotations
from datetime import timedelta

# ── Domain / names
DOMAIN = "loewe_tv"
INTEGRATION_NAME = "Loewe TV"
MANUFACTURER = "Loewe"
MODEL_FALLBACK = "TV"

# ── Config entry keys used across the integration
CONF_BASE_URL = "base_url"
CONF_HOST = "host"
CONF_URL = "url"
CONF_CLIENT_NAME = "client_name"

# Keys required by config_flow.py (must exist to import)
CONF_RESOURCE_PATH = "resource_path"
CONF_CLIENT_ID = "client_id"
CONF_DEVICE_UUID = "device_uuid"
CONF_CONTROL_TRANSPORT = "control_transport"

# ── Defaults
DEFAULT_CLIENT_NAME = "HomeAssistant"
# Our coordinator uses a timedelta; 10s is a good default for polling
DEFAULT_SCAN_INTERVAL = timedelta(seconds=10)
# The config_flow expects this exact string default (from your original code)
DEFAULT_RESOURCE_PATH = "/loewe_tablet_0001"

# Optional scan interval option key (kept for compatibility)
OPT_SCAN_INTERVAL = "scan_interval"

# Transport options (kept for compatibility with existing flows/options)
TRANSPORT_AUTO = "auto"
TRANSPORT_SOAP = "soap_only"
TRANSPORT_UPNP = "upnp_only"

# ── Namespaces
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
LTV_NS = "urn:loewe.de:RemoteTV:Tablet"

# ── Remote key codes shared by platforms
RC_KEY_POWER = 12
RC_KEY_MUTE_TOGGLE = 13
RC_KEY_VOL_DOWN = 20
RC_KEY_VOL_UP = 21

# ── Coordinator payload keys
ATTR_DEVICE = "device"
ATTR_STATUS = "status"
ATTR_POWER = "Power"
ATTR_VOLUME_RAW = "VolumeRaw"  # 0..1_000_000
ATTR_MUTE_RAW = "MuteRaw"      # 0/1

# ── Services
SERVICE_DEBUG_STATUS = "debug_status"

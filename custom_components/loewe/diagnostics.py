from __future__ import annotations
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

REDACT = {
    "ClientId",
    "MAC-Address",
    "MAC-Address-LAN",
    "MAC-Address-WLAN",
}

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    device_info = getattr(coord, "_device_info", {})

    data = {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": {
            "host": getattr(coord, "host", None),
            "resource_path": getattr(coord, "resource_path", None),
            "client_id": getattr(coord, "client_id", None),
        },
        "device_info": {
            "chassis": device_info.get("Chassis"),
            "sw_version": device_info.get("SW-Version"),
            "location": device_info.get("Location"),
            "network_host_name": device_info.get("NetworkHostName"),
            "streaming_server_name": device_info.get("StreamingServerName"),
            "own_volume_id": device_info.get("OwnVolumeId"),
            "mac": device_info.get("MAC-Address"),
            "mac_lan": device_info.get("MAC-Address-LAN"),
            "mac_wlan": device_info.get("MAC-Address-WLAN"),
        },
    }
    return async_redact_data(data, REDACT)


from __future__ import annotations
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

REDACT = {"ClientId", "MAC-Address", "MAC-Address-LAN", "MAC-Address-WLAN"}

async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "coordinator": {
            "host": getattr(coord, "host", None),
            "resource_path": getattr(coord, "resource_path", None),
            "client_id": getattr(coord, "client_id", None),
            "device_info": getattr(coord, "_device_info", {})
        },
    }
    return async_redact_data(data, REDACT)

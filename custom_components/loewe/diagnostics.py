"""Diagnostics support for Loewe TV integration."""

from __future__ import annotations
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Fields that should never be exposed in plain text
TO_REDACT: set[str] = {
    "client_id",
    "device_uuid",
    "fcid",
    "tv_mac",
    "MAC-Address",
    "MAC-Address-LAN",
    "MAC-Address-WLAN",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    device_info = getattr(coordinator, "_device_info", {})

    data: dict[str, Any] = {
        "entry": entry.as_dict(),
        "coordinator": {
            "host": getattr(coordinator, "host", None),
            "resource_path": getattr(coordinator, "resource_path", None),
            "client_id": getattr(coordinator, "client_id", None),
            "fcid": getattr(coordinator, "fcid", None),
        },
        "device_info": device_info,
        "status": getattr(coordinator, "data", {}),
    }

    return async_redact_data(data, TO_REDACT)

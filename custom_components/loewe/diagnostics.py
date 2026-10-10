"""Diagnostics support for Loewe TV integration."""

from __future__ import annotations
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import TO_REDACT
from .coordinator import LoeweConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LoeweConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (session IDs and MACs redacted)."""
    coordinator = entry.runtime_data
    data: dict[str, Any] = {
        "entry": entry.as_dict(),
        "connection": {
            "host": coordinator.soap.host,
            "resource_path": coordinator.soap.resource_path,
            "url": coordinator.soap.url,
            "client_id": coordinator.client_id,
            "fcid": coordinator.fcid,
            "tv_mac": coordinator.tv_mac,
            "client_mac": coordinator.client_mac,
            "last_update_success": coordinator.last_update_success,
        },
        "device_info": coordinator._device_info,
        "sources": {
            "av_inputs": [src["name"] for src in coordinator.available_sources],
            "favourite_channels": len(coordinator.favourite_channels),
            "all_channels": len(coordinator.all_channels),
        },
        "data": coordinator.data,
    }
    return async_redact_data(data, TO_REDACT)

from __future__ import annotations
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not coordinator:
        return {"error": "Coordinator not found"}
    data = coordinator.data or {}
    return {
        "host": entry.data.get("host"),
        "name": entry.data.get("name"),
        "state": data.get("state"),
        "volume": data.get("volume"),
        "muted": data.get("muted"),
        "source": data.get("source"),
        "current_channel": data.get("channel"),
        "current_app": data.get("app"),
        "current_input": data.get("input"),
        "inputs": list(data.get("inputs", {}).keys()),
        "channels_count": len(data.get("channels", {})),
        "apps_count": len(data.get("apps", {})),
    }

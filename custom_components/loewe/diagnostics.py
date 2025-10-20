"""Diagnostics support for Loewe TV integration."""

from __future__ import annotations
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_TV_MAC, CONF_CLIENT_MAC, CONF_DEVICE_UUID, TO_REDACT

def _deep_redact(obj: Any) -> Any:
    """Recursively redact any field whose name matches entries in TO_REDACT."""
    if isinstance(obj, dict):
        return {
            k: (
                "**REDACTED**"
                if any(red.lower() in k.lower() for red in TO_REDACT)
                else _deep_redact(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_deep_redact(v) for v in obj]
    return obj

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
            "tv_mac": getattr(coordinator, "tv_mac", None),
            "client_mac": getattr(coordinator, "client_mac", None),
        },
        "device_info": device_info,
        "status": getattr(coordinator, "data", {}),
    }

    # Redact sensitive information deeply
    redacted = async_redact_data(data, TO_REDACT)
    return _deep_redact(redacted)


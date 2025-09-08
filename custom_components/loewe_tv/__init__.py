from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .coordinator import LoeweTVCoordinator

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.BUTTON,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data["host"]
    resource_path = entry.data.get("resource_path") or "/loewe_tablet_0001"
    client_id = entry.data.get("client_id")
    device_uuid = entry.data.get("device_uuid")
    control_transport = entry.options.get("control_transport", "soap_only") if entry.options else "soap_only"
    update_interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL) if entry.options else DEFAULT_SCAN_INTERVAL

    coordinator = LoeweTVCoordinator(hass, host, resource_path, client_id=client_id, device_uuid=device_uuid, control_transport=control_transport, update_interval=update_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator:
            await coordinator.async_close()
    return unloaded

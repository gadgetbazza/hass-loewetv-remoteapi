"""Loewe TV integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .coordinator import LoeweTVCoordinator
from .network import async_get_device_mac

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_RESOURCE_PATH,
    CONF_CLIENT_ID,
    CONF_DEVICE_UUID,
    CONF_FCID,
    CONF_TV_MAC,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Loewe TV integration (YAML not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Loewe TV from a config entry."""
    host = entry.data[CONF_HOST]
    resource_path = entry.data.get(CONF_RESOURCE_PATH, "/loewe_tablet_0001")
    client_id = entry.data.get(CONF_CLIENT_ID)
    device_uuid = entry.data.get(CONF_DEVICE_UUID) or await async_get_device_mac(hass)
    fcid = entry.data.get(CONF_FCID)

    _LOGGER.debug(
        "async_setup_entry: host=%s resource_path=%s client_id=%s device_uuid=%s fcid=%s",
        host, resource_path, client_id, device_uuid, fcid
    )

    # --- Verify stored DeviceUUID (MAC) matches current ---
    current_mac = await async_get_device_mac(hass)
    stored_uuid = entry.data.get(CONF_DEVICE_UUID)

    if stored_uuid and stored_uuid.lower() != current_mac.lower():
        _LOGGER.warning(
            "Stored DeviceUUID (%s) does not match current MAC (%s) — "
            "re-pairing may be required.",
            stored_uuid, current_mac,
        )
        # Optionally, trigger re-pair automatically
        entry_data = dict(entry.data)
        entry_data[CONF_DEVICE_UUID] = current_mac
        hass.config_entries.async_update_entry(entry, data=entry_data)

    coordinator = LoeweTVCoordinator(hass, host=host, resource_path=resource_path, entry=entry)
    coordinator.client_id = client_id
    coordinator.fcid = fcid
    coordinator.device_uuid = device_uuid

    # Load persisted TV MAC captured during config flow
    coordinator.tv_mac = entry.data.get(CONF_TV_MAC)

    # Ensure valid session before fetching device data
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setups to supported platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_channel_up(call):
        """Handle channel up service call."""
        await coordinator.async_channel_up()

    async def handle_channel_down(call):
        """Handle channel down service call."""
        await coordinator.async_channel_down()

    async def handle_refresh_sources(call):
        """Handle manual refresh of AV and channel sources."""
        target_entity_ids = call.data.get("entity_id")
        if not target_entity_ids or any(
            eid.endswith(entry.entry_id) for eid in target_entity_ids
        ):
            await coordinator.async_refresh_sources()
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "channel_up", handle_channel_up)
    hass.services.async_register(DOMAIN, "channel_down", handle_channel_down)
    hass.services.async_register(DOMAIN, "refresh_sources", handle_refresh_sources)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Loewe TV config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: LoeweTVCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unload_ok

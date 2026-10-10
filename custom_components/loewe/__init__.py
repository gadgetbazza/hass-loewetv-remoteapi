"""Loewe TV integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
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
    CONF_CLIENT_MAC,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _target_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[LoeweTVCoordinator]:
    """Return the coordinators for the entities a service call targets (all if none given)."""
    coordinators: dict[str, LoeweTVCoordinator] = hass.data[DOMAIN]
    entity_ids = cv.ensure_list(call.data.get(ATTR_ENTITY_ID))
    if not entity_ids or ENTITY_MATCH_ALL in entity_ids:
        return list(coordinators.values())

    registry = er.async_get(hass)
    targets: list[LoeweTVCoordinator] = []
    for entity_id in entity_ids:
        entity = registry.async_get(entity_id)
        coordinator = coordinators.get(entity.config_entry_id) if entity else None
        if coordinator and coordinator not in targets:
            targets.append(coordinator)
    return targets


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Loewe TV integration (YAML not supported) and its services."""
    hass.data.setdefault(DOMAIN, {})

    async def handle_channel_up(call: ServiceCall) -> None:
        """Handle channel up service call."""
        for coordinator in _target_coordinators(hass, call):
            await coordinator.async_channel_up()

    async def handle_channel_down(call: ServiceCall) -> None:
        """Handle channel down service call."""
        for coordinator in _target_coordinators(hass, call):
            await coordinator.async_channel_down()

    async def handle_refresh_sources(call: ServiceCall) -> None:
        """Handle manual refresh of AV and channel sources."""
        for coordinator in _target_coordinators(hass, call):
            await coordinator.async_refresh_sources()
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "channel_up", handle_channel_up)
    hass.services.async_register(DOMAIN, "channel_down", handle_channel_down)
    hass.services.async_register(DOMAIN, "refresh_sources", handle_refresh_sources)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Loewe TV from a config entry."""
    host = entry.data[CONF_HOST]
    resource_path = entry.data.get(CONF_RESOURCE_PATH, "/loewe_tablet_0001")
    client_id = entry.data.get(CONF_CLIENT_ID)
    client_mac = entry.data.get(CONF_CLIENT_MAC) or await async_get_device_mac(hass)
    fcid = entry.data.get(CONF_FCID)

    _LOGGER.debug(
        "async_setup_entry: host=%s resource_path=%s client_id=%s client_mac=%s fcid=%s",
        host, resource_path, client_id, client_mac, fcid
    )

    # --- Verify stored Client MAC matches current ---
    current_mac = await async_get_device_mac(hass)

    if client_mac and client_mac.lower() != current_mac.lower():
        _LOGGER.warning(
            "Stored Client MAC (%s) does not match current MAC (%s) — "
            "re-pairing may be required.",
            client_mac, current_mac,
        )
        # Optionally, trigger re-pair automatically
        entry_data = dict(entry.data)
        entry_data[CONF_CLIENT_MAC] = current_mac
        hass.config_entries.async_update_entry(entry, data=entry_data)

    coordinator = LoeweTVCoordinator(hass, host=host, resource_path=resource_path, entry=entry)
    coordinator.client_id = client_id
    coordinator.fcid = fcid
    coordinator.client_mac = current_mac

    # Load persisted TV MAC captured during config flow
    coordinator.tv_mac = entry.data.get(CONF_TV_MAC)

    # Ensure valid session before fetching device data
    await coordinator.async_config_entry_first_refresh()

    # Backfill missing tv_mac into config entry if later discovered
    try:
        if not entry.data.get(CONF_TV_MAC) and getattr(coordinator, "tv_mac", None):
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_TV_MAC: coordinator.tv_mac},
            )
            _LOGGER.debug("Backfilled missing tv_mac into config entry: %s", coordinator.tv_mac)
    except Exception as e:
        _LOGGER.debug("tv_mac backfill skipped: %s", e)

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setups to supported platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Loewe TV config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: LoeweTVCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unload_ok

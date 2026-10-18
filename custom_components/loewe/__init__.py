"""Loewe TV integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import format_mac
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_RESOURCE_PATH,
    CONF_TV_MAC,
    CONF_CLIENT_MAC,
    CONF_TMDB_API_KEY,
    DEFAULT_RESOURCE_PATH,
    PLATFORMS,
)
from .coordinator import REPEAT_DAYS, LoeweConfigEntry, LoeweTVCoordinator
from .network import async_get_device_mac

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RECORD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Optional("programme"): vol.In(["current", "next"]),
        vol.Optional("channel"): cv.string,
        vol.Optional("start"): cv.datetime,
        vol.Optional("end"): cv.datetime,
        vol.Optional("duration"): cv.positive_time_period,
        vol.Optional("repeat"): vol.In(list(REPEAT_DAYS)),
    }
)

GET_GUIDE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Optional("channel"): cv.string,
        vol.Optional("hours", default=24): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=192)),
    }
)


def _loaded_coordinators(hass: HomeAssistant) -> dict[str, LoeweTVCoordinator]:
    """Coordinators of all loaded Loewe TV entries, keyed by entry_id."""
    return {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    }


def _target_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[LoeweTVCoordinator]:
    """Return the coordinators for the entities a service call targets (all if none given)."""
    coordinators = _loaded_coordinators(hass)
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

    async def handle_record(call: ServiceCall) -> None:
        """Programme a recording on the targeted TV(s)."""
        options = {k: v for k, v in call.data.items() if k != ATTR_ENTITY_ID}
        for coordinator in _target_coordinators(hass, call):
            await coordinator.async_record(**options)

    async def handle_get_guide(call: ServiceCall) -> ServiceResponse:
        """Return a channel's programmes from the TV's guide (the first targeted TV)."""
        coordinators = _target_coordinators(hass, call)
        if not coordinators:
            raise ServiceValidationError("No Loewe TV to read the guide from")
        coordinator = coordinators[0]
        query = call.data.get("channel")
        if query:
            found = coordinator.find_channel(query)
            channel = coordinator.lookup_channel(found["locator"]) if found else None
            if not channel:
                raise ServiceValidationError(f"No TV channel called {query!r} on the Loewe TV")
        elif not (channel := coordinator.current_channel):
            raise ServiceValidationError("The Loewe TV isn't showing a TV channel; give a channel")
        until = dt_util.utcnow().timestamp() + call.data["hours"] * 3600

        def iso(timestamp: int) -> str:
            return dt_util.as_local(dt_util.utc_from_timestamp(timestamp)).isoformat()

        return {
            "channel": channel["name"],
            "programmes": [
                {
                    "title": p["title"],
                    "description": p["description"],
                    "start": iso(p["start"]),
                    "end": iso(p["end"]),
                }
                for p in await coordinator.async_get_guide(channel)
                if p["start"] < until
            ],
        }

    hass.services.async_register(DOMAIN, "channel_up", handle_channel_up)
    hass.services.async_register(DOMAIN, "channel_down", handle_channel_down)
    hass.services.async_register(DOMAIN, "refresh_sources", handle_refresh_sources)
    hass.services.async_register(DOMAIN, "record", handle_record, schema=RECORD_SCHEMA)
    hass.services.async_register(
        DOMAIN, "get_guide", handle_get_guide, schema=GET_GUIDE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LoeweConfigEntry) -> bool:
    """Set up Loewe TV from a config entry."""
    # The TV pairs with HA's MAC (sent as DeviceUUID); note if HA's network interface changed
    current_mac = await async_get_device_mac(hass)
    stored_mac = entry.data.get(CONF_CLIENT_MAC)
    if stored_mac != current_mac:
        if stored_mac:
            _LOGGER.warning(
                "Home Assistant's MAC changed from %s to %s; the TV may ask to pair again",
                stored_mac, current_mac,
            )
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_CLIENT_MAC: current_mac}
        )

    coordinator = LoeweTVCoordinator(
        hass,
        host=entry.data[CONF_HOST],
        resource_path=entry.data.get(CONF_RESOURCE_PATH, DEFAULT_RESOURCE_PATH),
        entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()
    _async_update_tv_identity(hass, entry, coordinator)

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: LoeweConfigEntry) -> None:
    """Apply changed options without a reload.

    Also called when the coordinator stores a renewed session in the entry's
    data, so only the options are looked at.
    """
    coordinator = entry.runtime_data
    if coordinator.set_tmdb_key(entry.options.get(CONF_TMDB_API_KEY)):
        await coordinator.async_request_refresh()


def _async_update_tv_identity(
    hass: HomeAssistant, entry: LoeweConfigEntry, coordinator: LoeweTVCoordinator
) -> None:
    """Store the TV MAC once known and use it as the entry's unique ID.

    Entries created before 1.1 used "loewe-<host>" as their unique ID, which
    breaks duplicate detection when the TV's IP address changes.
    """
    if not coordinator.tv_mac:
        return
    data = entry.data
    if not data.get(CONF_TV_MAC):
        data = {**data, CONF_TV_MAC: coordinator.tv_mac}
        _LOGGER.debug("Stored TV MAC %s in config entry", coordinator.tv_mac)

    unique_id = format_mac(coordinator.tv_mac)
    if entry.unique_id != unique_id and not any(
        other.unique_id == unique_id
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ):
        _LOGGER.debug("Updating config entry unique ID from %s to %s", entry.unique_id, unique_id)
        hass.config_entries.async_update_entry(entry, data=data, unique_id=unique_id)
    elif data is not entry.data:
        hass.config_entries.async_update_entry(entry, data=data)


async def async_unload_entry(hass: HomeAssistant, entry: LoeweConfigEntry) -> bool:
    """Unload a Loewe TV config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

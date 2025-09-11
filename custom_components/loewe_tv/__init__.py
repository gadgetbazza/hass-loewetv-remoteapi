"""Loewe TV Remote API integration bootstrap."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .coordinator import LoeweCoordinator

_LOGGER = logging.getLogger(__name__)

try:
    from .const import DOMAIN
except Exception:  # pragma: no cover
    DOMAIN = "loewe_tv"

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Loewe integration (register services, etc.). Must return bool."""
    try:
        hass.data.setdefault(DOMAIN, {})

        async def _async_handle_debug_status(call: ServiceCall) -> None:
            """Service: loewe_tv.debug_status — log raw status/volume/mute.

            Optional fields:
              - entry_id: target a specific config entry
              - force_renew: bool; if true, drop current ClientId and request a new one first
            """
            entry_id: Optional[str] = call.data.get("entry_id")
            force_renew: bool = bool(call.data.get("force_renew", False))

            store: Dict[str, Dict[str, Any]] = hass.data.get(DOMAIN, {})

            # Choose coordinators
            targets: list[LoeweCoordinator] = []
            if entry_id:
                bundle = store.get(entry_id)
                if not bundle:
                    _LOGGER.warning("Loewe debug_status: entry_id %s not found", entry_id)
                else:
                    coord = bundle.get("coordinator")
                    if coord:
                        targets.append(coord)
            else:
                for bundle in store.values():
                    coord = bundle.get("coordinator")
                    if coord:
                        targets.append(coord)

            if not targets:
                _LOGGER.warning("Loewe debug_status: no active coordinators found")
                return

            for coord in targets:
                renewed = False

                if force_renew:
                    coord.client_id = None  # force RequestAccess
                    renewed = await coord.async_request_access()

                status = await coord.async_get_current_status()
                volume = await coord.async_get_volume()
                mute = await coord.async_get_mute()

                if not status:
                    if not force_renew:
                        renewed = await coord.async_request_access()
                    if renewed:
                        status = await coord.async_get_current_status()
                        volume = await coord.async_get_volume()
                        mute = await coord.async_get_mute()

                _LOGGER.info(
                    "Loewe debug [%s]: renewed=%s status=%s volume=%s mute=%s",
                    getattr(getattr(coord, "_device", None), "name", "TV"),
                    renewed,
                    status,
                    volume,
                    mute,
                )

        # Register domain-level service
        try:
            hass.services.async_register(DOMAIN, "debug_status", _async_handle_debug_status)
        except Exception as svc_err:  # very defensive; still return True
            _LOGGER.exception("Failed to register loewe_tv.debug_status: %s", svc_err)

        return True
    except Exception as err:
        # Always return False on failure so HA doesn't see "None"
        _LOGGER.exception("Error in loewe_tv.async_setup: %s", err)
        return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Loewe TV from a config entry."""
    try:
        hass.data.setdefault(DOMAIN, {})

        data = entry.data
        base_url = data.get("base_url") or data.get("url") or data.get("host")
        if not base_url:
            _LOGGER.error("Loewe TV: missing base_url/host in config entry data")
            return False

        coordinator = LoeweCoordinator(
            hass,
            base_url=str(base_url),
            client_name="HomeAssistant",
            device_name=entry.title or "Loewe TV",
            unique_id=entry.unique_id,
        )

        await coordinator.async_config_entry_first_refresh()

        hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        return True
    except Exception as err:
        _LOGGER.exception("Error in loewe_tv.async_setup_entry: %s", err)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry (platforms + network session)."""
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        bundle = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if bundle:
            coord: LoeweCoordinator | None = bundle.get("coordinator")
            if coord:
                await coord.async_close()
        return unload_ok
    except Exception as err:
        _LOGGER.exception("Error in loewe_tv.async_unload_entry: %s", err)
        return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle reloads from UI."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


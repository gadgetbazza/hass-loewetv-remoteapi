"""Remote platform for Loewe TV (to send RC keys)."""

from __future__ import annotations
import logging
from typing import Any, List

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Loewe TV remote entity from a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: LoeweTVCoordinator = (
        data if isinstance(data, LoeweTVCoordinator) else data.get("coordinator")
    )

    if coordinator is None:
        raise RuntimeError("No coordinator found for Loewe TV entry")

    entity = LoeweTVRemote(coordinator, entry)
    async_add_entities([entity])


class LoeweTVRemote(RemoteEntity):
    """Representation of Loewe TV Remote for sending RC keys."""

    _attr_should_poll = False

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._entry = entry
        device = (coordinator.data or {}).get("device", {})
        self._attr_name = (device.get("name") or entry.title or "Loewe TV") + " Remote"
        self._attr_unique_id = (device.get("unique_id") or entry.entry_id) + "_remote"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "manufacturer": device.get("manufacturer") or "Loewe",
            "model": device.get("model") or "TV",
            "sw_version": device.get("sw_version"),
            "name": self._attr_name,
        }

    async def async_send_command(self, command: List[str], **kwargs: Any) -> None:
        """Send one or more RC key codes."""
        for cmd in command:
            try:
                key = int(cmd)
            except ValueError:
                _LOGGER.warning("Invalid RC key: %s", cmd)
                continue
            _LOGGER.warning("LoeweTV: Sending RC key %s", key)
            await self.coordinator.async_inject_rc_key(key)


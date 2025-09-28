"""Remote platform for Loewe TV (to send RC keys)."""

from __future__ import annotations
import logging
from typing import Any, List

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOEWE_RC_CODES
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
        self._attr_unique_id = f"{entry.entry_id}_remote"

        device_info = coordinator._device_info or {}

        # Prefer NetworkHostName, fallback to entry title or default
        base_name = (
            device_info.get("NetworkHostName")
            or entry.title
            or "Loewe TV"
        )
        self._attr_name = base_name + " Remote"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},   # unify here
            "manufacturer": "Loewe",
            "model": device_info.get("Chassis", "TV"),
            "sw_version": device_info.get("SW-Version", ""),
            "name": base_name,   # Device name (without " Remote")
        }

    async def async_send_command(self, command: List[str], **kwargs: Any) -> None:
        """Send one or more RC key codes."""
        for cmd in command:
            # Look up symbolic key if needed
            if cmd.lower() in LOEWE_RC_CODES:
                key = LOEWE_RC_CODES[cmd.lower()]
            else:
                try:
                    key = int(cmd)
                except ValueError:
                    _LOGGER.warning("Invalid RC key: %s", cmd)
                    continue

            _LOGGER.debug("LoeweTV: Sending RC key %s (%s)", key, cmd)
            await self.coordinator.async_inject_rc_key(key)

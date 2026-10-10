"""Remote platform for Loewe TV (to send RC keys)."""

from __future__ import annotations
import asyncio
import logging

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOEWE_RC_CODES
from .coordinator import LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Loewe TV remote entity from a config entry."""
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LoeweTVRemote(coordinator, entry)])


class LoeweTVRemote(CoordinatorEntity, RemoteEntity):
    """Representation of Loewe TV Remote for sending RC keys."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None  # like other HA TV remotes, the entity takes the device's name

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_remote"
        self._attr_device_info = coordinator.device_info

    async def async_send_command(
        self,
        command: str | list[str],
        *,
        device: str | None = None,
        num_repeats: int = 1,
        delay_secs: float = 0.5,
        hold_secs: float | None = None,
    ) -> None:
        """Send one or more RC key codes to the TV."""

        # Normalize into a list
        commands = [command] if isinstance(command, str) else command

        for cmd in commands:
            key: int | None = None

            if cmd.lower() in LOEWE_RC_CODES:
                key = LOEWE_RC_CODES[cmd.lower()]
            else:
                try:
                    key = int(cmd)
                except ValueError:
                    _LOGGER.warning("Invalid RC key: %s", cmd)
                    continue

            for _ in range(num_repeats):
                _LOGGER.debug("LoeweTV: Sending RC key %s (%s)", key, cmd)
                await self.coordinator.async_inject_rc_key(key)
                if delay_secs:
                    await asyncio.sleep(delay_secs)

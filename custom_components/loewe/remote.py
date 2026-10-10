"""Remote platform for Loewe TV (to send RC keys)."""

from __future__ import annotations
import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from homeassistant.components.media_player import MediaPlayerState
from homeassistant.components.remote import RemoteEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import LOEWE_RC_CODES
from .coordinator import LoeweConfigEntry, LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: LoeweConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Loewe TV remote entity from a config entry."""
    async_add_entities([LoeweTVRemote(entry.runtime_data, entry)])


class LoeweTVRemote(CoordinatorEntity[LoeweTVCoordinator], RemoteEntity):
    """Representation of Loewe TV Remote for sending RC keys."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None  # like other HA TV remotes, the entity takes the device's name

    def __init__(self, coordinator: LoeweTVCoordinator, entry: LoeweConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_remote"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """The remote is on when the TV is on (standby counts as off)."""
        if not self.coordinator.data:
            return None
        state = (self.coordinator.data.get("device") or {}).get("ha_state")
        return state == MediaPlayerState.ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the TV (Wake-on-LAN + power-on key)."""
        await self.coordinator.async_power_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Put the TV into standby."""
        await self.coordinator.async_power_off()
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send RC keys by name (see LOEWE_RC_CODES) or numeric code.

        Honours num_repeats and delay_secs (between key presses). hold_secs is
        ignored: the TV treats a held key as a single press.
        """
        num_repeats: int = kwargs.get("num_repeats", 1)
        delay_secs: float = kwargs.get("delay_secs", 0.5)

        keys: list[tuple[str, int]] = []
        for cmd in [command] if isinstance(command, str) else command:
            if (key := LOEWE_RC_CODES.get(cmd.lower())) is None:
                try:
                    key = int(cmd)
                except ValueError:
                    _LOGGER.warning("Invalid RC key: %s", cmd)
                    continue
            keys.append((cmd, key))

        # Each key is repeated num_repeats times before the next key (unchanged behaviour)
        presses = [key for key in keys for _ in range(num_repeats)]
        for index, (cmd, key) in enumerate(presses):
            if index and delay_secs:
                await asyncio.sleep(delay_secs)
            _LOGGER.debug("LoeweTV: Sending RC key %s (%s)", key, cmd)
            await self.coordinator.async_inject_rc_key(key)

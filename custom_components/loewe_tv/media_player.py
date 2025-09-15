"""Media Player platform for Loewe TV."""

from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, RC_KEY_POWER_OFF
from .coordinator import LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Loewe TV media player from a config entry."""
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LoeweTVMediaPlayer(coordinator, entry)])


class LoeweTVMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of Loewe TV as a Media Player."""

    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._attr_name = entry.title or "Loewe TV"
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "manufacturer": "Loewe",
            "model": "TV",
            "name": self._attr_name,
        }

    # ---------- State ----------
    @property
    def state(self) -> str | None:
        device = (self.coordinator.data or {}).get("device", {})
        ha_state = device.get("ha_state")
        if ha_state:
            return ha_state
        return STATE_UNKNOWN

    @property
    def volume_level(self) -> float | None:
        device = (self.coordinator.data or {}).get("device", {})
        volume = device.get("volume")
        if volume is not None:
            level = volume / 1_000_000
            return min(max(level, 0.0), 1.0)  # clamp to [0,1]
        return None

    @property
    def is_volume_muted(self) -> bool | None:
        device = (self.coordinator.data or {}).get("device", {})
        return device.get("mute")

    # ---------- Commands ----------
    async def async_turn_off(self) -> None:
        """Send discrete Power Off RC key."""
        _LOGGER.debug("LoeweTV: Sending RC POWER OFF")
        await self.coordinator.async_inject_rc_key(RC_KEY_POWER_OFF)

    async def async_turn_on(self) -> None:
        """Turn on the TV (not yet implemented)."""
        _LOGGER.warning("LoeweTV: Turn on not implemented yet")

    async def async_set_volume_level(self, volume: float) -> None:
        raw_value = int(volume * 1_000_000)
        if await self.coordinator.async_set_volume(raw_value):
            # Optimistically update coordinator state
            device = self.coordinator.data.get("device", {})
            device["volume"] = raw_value
            self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        if await self.coordinator.async_set_mute(mute):
            # Optimistically update coordinator state
            device = self.coordinator.data.get("device", {})
            device["mute"] = mute
            self.async_write_ha_state()



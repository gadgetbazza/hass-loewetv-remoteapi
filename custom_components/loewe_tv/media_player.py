"""Media Player platform for Loewe TV."""

from __future__ import annotations
import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOEWE_RC_CODES
from .coordinator import LoeweTVCoordinator
from .utils import async_send_wol

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
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media"

        # Prefer Loewe-reported hostname, fallback to entry title or default
        device_info = coordinator._device_info or {}
        self._attr_name = (
            device_info.get("NetworkHostName")
            or entry.title
            or "Loewe TV"
        )

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},   # unify here
            "manufacturer": "Loewe",
            "model": device_info.get("Chassis", "TV"),
            "sw_version": device_info.get("SW-Version", ""),
            "name": self._attr_name,
        }


    # ---------- State ----------
    @property
    def state(self) -> str | None:
        device = (self.coordinator.data or {}).get("device", {})
        return device.get("ha_state", STATE_UNKNOWN)

    @property
    def volume_level(self) -> float | None:
        device = (self.coordinator.data or {}).get("device", {})
        volume = device.get("volume")
        if volume is not None:
            level = volume / 1_000_000
            return min(max(level, 0.0), 1.0)  # clamp to [0,1]
        return None

    @property
    def volume_step(self) -> float:
        """Override HA default step (0.1 → too big) to 0.01 (1%)."""
        return 0.01

    @property
    def is_volume_muted(self) -> bool | None:
        device = (self.coordinator.data or {}).get("device", {})
        return device.get("mute")

    @property
    def source_list(self) -> list[str] | None:
        """Return the list of available inputs (plus TV tuner)."""
        sources = [src["name"] for src in self.coordinator.available_sources]
        if "TV" not in sources:
            sources.insert(0, "TV")
        return sources

    @property
    def source(self) -> str | None:
        """Return the currently active input."""
        loc = self.coordinator.current_locator
        if not loc:
            return None

        # First check AV sources
        for src in self.coordinator.available_sources:
            if src["locator"] == loc:
                return src["name"]

        # If not found but matches last known TV tuner locator → treat as "TV"
        if loc == getattr(self.coordinator, "_last_tv_locator", None):
            return "TV"

        return None

    # ---------- Commands ----------
    async def async_turn_off(self) -> None:
        """Send discrete Power Off RC key."""
        _LOGGER.debug("LoeweTV: Sending RC POWER OFF")
        keycode = LOEWE_RC_CODES.get("power_off")
        if keycode is not None:
            await self.coordinator.async_inject_rc_key(keycode)

    async def async_turn_on(self) -> None:
        """Wake TV via WOL, then send RC TV_ON (22) to leave network standby."""
        mac = self.coordinator.tv_mac
        if mac:
            _LOGGER.debug("LoeweTV: Sending WOL to %s", mac)
            try:
                await async_send_wol(self.hass, mac)
            except Exception as e:
                _LOGGER.warning("LoeweTV: Failed to send WOL to %s: %s", mac, e)
        else:
            _LOGGER.warning("LoeweTV: No TV MAC available for WOL")

        _LOGGER.debug("LoeweTV: Sending RC TV_ON")
        keycode = LOEWE_RC_CODES.get("power_on")
        if keycode is not None:
            await self.coordinator.async_inject_rc_key(keycode)

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

    async def async_select_source(self, source: str) -> None:
        """Switch TV input or AV source."""
        if source == "TV":
            locator = getattr(self.coordinator, "_last_tv_locator", None)

            if not locator:
                # Fall back to first channel from Freeview (or favlist)
                locator = await self.coordinator.async_get_first_tv_channel()
                if locator:
                    _LOGGER.debug("LoeweTV: Using fallback first TV channel %s", locator)
                else:
                    _LOGGER.warning("LoeweTV: No TV channels available to zap to")
                    return

            _LOGGER.debug("LoeweTV: Switching to TV channel %s", locator)
            if await self.coordinator.async_set_channel(locator):
                self.async_write_ha_state()
            else:
                _LOGGER.warning("LoeweTV: Zap to TV channel %s failed", locator)
                # Revert state back to previous source
                self.async_write_ha_state()
            return

        # Otherwise, look through AV sources
        for src in self.coordinator.available_sources:
            if src["name"] == source:
                locator = src["locator"]
                _LOGGER.debug("LoeweTV: Switching source to %s (%s)", source, locator)
                if await self.coordinator.async_set_channel(locator):
                    self.async_write_ha_state()
                else:
                    _LOGGER.warning("LoeweTV: Zap to %s (%s) failed", source, locator)
                    # Revert state back
                    self.async_write_ha_state()
                return

        _LOGGER.warning("LoeweTV: Requested source %s not found", source)

    async def async_channel_up(self) -> None:
        """Send channel up command."""
        _LOGGER.debug("LoeweTV: Channel Up pressed")
        await self.coordinator.async_channel_up()

    async def async_channel_down(self) -> None:
        """Send channel down command."""
        _LOGGER.debug("LoeweTV: Channel Down pressed")
        await self.coordinator.async_channel_down()


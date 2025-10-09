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
from .network import async_send_wol

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

        device_info = coordinator._device_info or {}
        self._attr_name = (
            device_info.get("NetworkHostName") or entry.title or "Loewe TV"
        )

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "Loewe",
            "model": device_info.get("Chassis", "TV"),
            "sw_version": device_info.get("SW-Version", ""),
            "name": self._attr_name,
        }

    # ---------- State ----------
    @property
    def state(self) -> str:
        device = (self.coordinator.data or {}).get("device", {})
        return device.get("ha_state", STATE_UNKNOWN)

    @property
    def volume_level(self) -> float | None:
        device = (self.coordinator.data or {}).get("device", {})
        if (volume := device.get("volume")) is not None:
            level = volume / 1_000_000
            return max(0.0, min(level, 1.0))  # clamp to [0,1]
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

        for src in self.coordinator.available_sources:
            if src["locator"] == loc:
                return src["name"]

        if loc == getattr(self.coordinator, "_last_tv_locator", None):
            return "TV"
        return None

    # ---------- Commands ----------
    async def async_turn_off(self) -> None:
        """Send discrete Power Off RC key."""
        if (keycode := LOEWE_RC_CODES.get("power_off")) is not None:
            if await self.coordinator.async_inject_rc_key(keycode):
                # Optimistically update state
                self.coordinator.data.get("device", {})["ha_state"] = "off"
                self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the Loewe TV using Wake-on-LAN and a discrete RC key (22)."""
        mac = self.coordinator.tv_mac
        wol_sent = False

        # --- Step 1: Send Wake-on-LAN (if MAC known) ---
        if mac:
            try:
                from .network import async_send_wol
                _LOGGER.debug("Sending Wake-on-LAN to %s", mac)
                await async_send_wol(mac)
                wol_sent = True
            except Exception as e:
                _LOGGER.warning("Failed to send WOL packet: %s", e)
        else:
            _LOGGER.debug("No MAC address available for WOL; skipping")

        # --- Step 2: Optional delay to let NIC wake up ---
        if wol_sent:
            _LOGGER.debug("WOL sent, waiting 1.0s before sending RC Power On")
            await asyncio.sleep(1.0)

        # --- Step 3: Send discrete Power On RC key (22) ---
        try:
            if (keycode := LOEWE_RC_CODES.get("power_on")) is not None:
                await self.coordinator.async_inject_rc_key(keycode)
                _LOGGER.debug("Sent RC key %s (Discrete Power On) after WOL", keycode)
        except Exception as e:
            _LOGGER.warning("Failed to send RC Power On key: %s", e)

    async def async_set_volume_level(self, volume: float) -> None:
        raw_value = int(volume * 1_000_000)
        if await self.coordinator.async_set_volume(raw_value):
            # Optimistically update
            self.coordinator.data.get("device", {})["volume"] = raw_value
            self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        if await self.coordinator.async_set_mute(mute):
            # Optimistically update
            self.coordinator.data.get("device", {})["mute"] = mute
            self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Switch TV input or AV source."""
        if source == "TV":
            locator = getattr(self.coordinator, "_last_tv_locator", None) or await self.coordinator.async_get_first_tv_channel()
            if not locator:
                _LOGGER.warning("No TV channels available to zap to")
                return

            if await self.coordinator.async_set_channel(locator):
                # Optimistically update
                self._attr_source = "TV"
                self.async_write_ha_state()
            else:
                _LOGGER.warning("Zap to TV channel %s failed", locator)
                self.async_write_ha_state()
            return

        for src in self.coordinator.available_sources:
            if src["name"] == source:
                locator = src["locator"]
                if await self.coordinator.async_set_channel(locator):
                    # Optimistically update
                    self._attr_source = source
                    self.async_write_ha_state()
                else:
                    _LOGGER.warning("Zap to %s (%s) failed", source, locator)
                    self.async_write_ha_state()
                return

        _LOGGER.warning("Requested source %s not found", source)

    async def async_channel_up(self) -> None:
        await self.coordinator.async_channel_up()

    async def async_channel_down(self) -> None:
        await self.coordinator.async_channel_down()

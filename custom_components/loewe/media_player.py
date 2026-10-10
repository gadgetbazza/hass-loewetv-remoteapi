"""Media Player platform for Loewe TV."""

from __future__ import annotations
import logging
import asyncio
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOEWE_RC_CODES
from .coordinator import LoeweTVCoordinator
from .network import async_send_wol

_LOGGER = logging.getLogger(__name__)

# Media browser folders, in display order (favourites first)
BROWSE_FAVOURITES = "favourites"
BROWSE_ALL_CHANNELS = "all_channels"
BROWSE_INPUTS = "inputs"
BROWSE_FOLDERS = {
    BROWSE_FAVOURITES: "Favourites",
    BROWSE_ALL_CHANNELS: "All channels",
    BROWSE_INPUTS: "Inputs",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Loewe TV media player from a config entry."""
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LoeweTVMediaPlayer(coordinator, entry)])


class LoeweTVMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of Loewe TV as a Media Player."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None  # the entity takes the device's name
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA
    )

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media"
        self._attr_device_info = coordinator.device_info

    # ---------- State ----------
    @property
    def state(self) -> str:
        """ON/OFF from the TV; PLAYING while it is on and tuned to a TV channel."""
        device = (self.coordinator.data or {}).get("device", {})
        state = device.get("ha_state", STATE_UNKNOWN)
        if state == MediaPlayerState.ON and self._channel:
            return MediaPlayerState.PLAYING
        return state

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
        return self.coordinator.current_source_name

    # ---------- Now playing ----------
    @property
    def _channel(self) -> dict[str, str] | None:
        return (self.coordinator.data or {}).get("channel")

    @property
    def _event(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("event") or {}

    @property
    def media_content_type(self) -> str | None:
        return MediaType.CHANNEL if self._channel else None

    @property
    def media_content_id(self) -> str | None:
        return self._channel["locator"] if self._channel else None

    @property
    def media_channel(self) -> str | None:
        return self._channel["name"] if self._channel else None

    @property
    def media_title(self) -> str | None:
        """Programme title on a TV channel (channel name if no EPG), else the input name."""
        if self.state not in (MediaPlayerState.ON, MediaPlayerState.PLAYING):
            return None
        if self._channel:
            return self._event.get("name") or self._channel["name"]
        return self.coordinator.current_source_name

    @property
    def media_duration(self) -> int | None:
        return self._event.get("duration") if self._channel else None

    # Position is reported as 0 at the programme's start time; HA extrapolates
    # from media_position_updated_at, so the attributes only change per programme.
    @property
    def media_position(self) -> int | None:
        return 0 if self._channel and self._event.get("start") is not None else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        if self._channel and (start := self._event.get("start")) is not None:
            return datetime.fromtimestamp(start, tz=timezone.utc)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self._channel:
            return None
        nxt = (self.coordinator.data or {}).get("next_event") or {}
        return {
            "channel_number": self._channel.get("number"),
            "programme_description": self._event.get("info") or None,
            "next_programme": nxt.get("name"),
            "next_programme_start": (
                datetime.fromtimestamp(nxt["start"], tz=timezone.utc).isoformat()
                if nxt.get("start") is not None
                else None
            ),
        }

    # ---------- Media browser ----------
    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse favourites, all channels and AV inputs."""
        if not media_content_id:
            return BrowseMedia(
                title=self.name or "Loewe TV",
                media_class=MediaClass.DIRECTORY,
                media_content_id="",
                media_content_type="",
                can_play=False,
                can_expand=True,
                children=[self._browse_folder(folder) for folder in BROWSE_FOLDERS],
                children_media_class=MediaClass.DIRECTORY,
            )
        if media_content_id in BROWSE_FOLDERS:
            return self._browse_folder(media_content_id, with_children=True)
        raise BrowseError(f"Unknown media folder: {media_content_id}")

    def _folder_items(self, folder: str) -> list[dict[str, str]]:
        if folder == BROWSE_FAVOURITES:
            return self.coordinator.favourite_channels
        if folder == BROWSE_ALL_CHANNELS:
            return self.coordinator.all_channels
        return self.coordinator.available_sources

    def _browse_folder(self, folder: str, with_children: bool = False) -> BrowseMedia:
        children = None
        if with_children:
            children = [
                BrowseMedia(
                    title=f"{item['number']}. {item['name']}" if item.get("number") else item["name"],
                    media_class=MediaClass.CHANNEL,
                    media_content_id=item["locator"],
                    media_content_type=MediaType.CHANNEL,
                    can_play=True,
                    can_expand=False,
                )
                for item in self._folder_items(folder)
            ]
        return BrowseMedia(
            title=BROWSE_FOLDERS[folder],
            media_class=MediaClass.DIRECTORY,
            media_content_id=folder,
            media_content_type="",
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.CHANNEL,
        )

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        """Switch to a channel/input given its locator, name or favourite number."""
        item = self.coordinator.find_channel(media_id)
        locator = item["locator"] if item else media_id
        if not item and not media_id.startswith("channel://"):
            raise HomeAssistantError(f"Unknown Loewe channel or input: {media_id}")
        if not await self.coordinator.async_set_channel(locator):
            raise HomeAssistantError(f"Loewe TV did not switch to {media_id}")

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
                await async_send_wol(self.coordinator.hass, mac)
                wol_sent = True
            except Exception as e:
                _LOGGER.warning("Failed to send WOL packet: %s", e)
        else:
            _LOGGER.debug("No TV MAC address available for WOL; skipping")

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

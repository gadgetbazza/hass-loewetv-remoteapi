"""Media Player platform for Loewe TV."""

from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
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
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import LoeweConfigEntry, LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)

# Media browser folders, in display order (favourites first)
BROWSE_FAVOURITES = "favourites"
BROWSE_ALL_CHANNELS = "all_channels"
BROWSE_INPUTS = "inputs"
BROWSE_GUIDE = "guide"
BROWSE_FOLDERS = {
    BROWSE_FAVOURITES: "Favourites",
    BROWSE_ALL_CHANNELS: "All channels",
    BROWSE_INPUTS: "Inputs",
    BROWSE_GUIDE: "Guide",
}

# Media IDs below the Guide folder: guide/<channel key>[/<YYYY-MM-DD>[/<start>]],
# and the "Record" item, played to programme a recording: record/<channel key>/<start>/<end>
GUIDE_PREFIX = f"{BROWSE_GUIDE}/"
RECORD_PREFIX = "record/"
MEDIA_TYPE_RECORD = "loewe_record"


async def async_setup_entry(
    hass: HomeAssistant, entry: LoeweConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Loewe TV media player from a config entry."""
    async_add_entities([LoeweTVMediaPlayer(entry.runtime_data, entry)])


class LoeweTVMediaPlayer(CoordinatorEntity[LoeweTVCoordinator], MediaPlayerEntity):
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

    def __init__(self, coordinator: LoeweTVCoordinator, entry: LoeweConfigEntry) -> None:
        super().__init__(coordinator)
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
    def media_image_url(self) -> str | None:
        """Programme artwork from TMDB (only when an API key is set in the options)."""
        return (self.coordinator.data or {}).get("artwork") if self._channel else None

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
        if media_content_id == BROWSE_GUIDE:
            return self._browse_guide_channels()
        if media_content_id.startswith(GUIDE_PREFIX):
            return await self._async_browse_guide(media_content_id[len(GUIDE_PREFIX):].split("/"))
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
        if folder == BROWSE_GUIDE and not with_children:
            return _directory(BROWSE_GUIDE, BROWSE_FOLDERS[BROWSE_GUIDE], MediaClass.CHANNEL)
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

    # ---------- Programme guide ----------
    @staticmethod
    def _channel_title(channel: dict[str, str]) -> str:
        return f"{channel['number']}. {channel['name']}" if channel.get("number") else channel["name"]

    def _guide_channels(self) -> list[dict[str, str]]:
        """Channels offered in the guide: the favourites, or every channel if there are none."""
        channels = self.coordinator.favourite_channels or self.coordinator.all_channels
        return [c for c in channels if self.coordinator.dvb_triplet(c)]

    def _browse_guide_channels(self) -> BrowseMedia:
        children = [
            _directory(
                f"{GUIDE_PREFIX}{self.coordinator.channel_key(channel)}",
                self._channel_title(channel),
                MediaClass.DIRECTORY,
                media_class=MediaClass.CHANNEL,
            )
            for channel in self._guide_channels()
        ]
        return _directory(BROWSE_GUIDE, BROWSE_FOLDERS[BROWSE_GUIDE], MediaClass.CHANNEL, children)

    async def _async_browse_guide(self, parts: list[str]) -> BrowseMedia:
        """Guide pages: a channel's days, a day's programmes, or one programme's actions."""
        channel = self.coordinator.channel_by_key(parts[0])
        if not channel:
            raise BrowseError(f"Unknown channel in the guide: {parts[0]}")
        programmes = await self.coordinator.async_get_guide(channel)
        base = f"{GUIDE_PREFIX}{parts[0]}"
        today = dt_util.now().date()

        if len(parts) == 1:
            days = sorted({_local_date(p["start"], today) for p in programmes})
            children = [
                _directory(f"{base}/{day.isoformat()}", _day_title(day, today), MediaClass.EPISODE)
                for day in days
            ]
            return _directory(base, self._channel_title(channel), MediaClass.DIRECTORY, children)

        try:
            day = date.fromisoformat(parts[1])
        except ValueError as err:
            raise BrowseError(f"Bad guide date: {parts[1]}") from err
        on_day = [p for p in programmes if _local_date(p["start"], today) == day]
        day_id = f"{base}/{parts[1]}"

        if len(parts) == 2:
            children = [
                _directory(
                    f"{day_id}/{p['start']}",
                    self._programme_title(p),
                    MediaClass.DIRECTORY,
                    media_class=MediaClass.EPISODE,
                )
                for p in on_day
            ]
            title = f"{self._channel_title(channel)}: {_day_title(day, today)}"
            return _directory(day_id, title, MediaClass.EPISODE, children)

        programme = next((p for p in on_day if str(p["start"]) == parts[2]), None)
        if not programme:
            raise BrowseError("That programme is no longer in the guide")
        return self._browse_programme(channel, parts[0], programme, f"{day_id}/{parts[2]}")

    def _programme_title(self, programme: dict[str, Any]) -> str:
        start = dt_util.as_local(dt_util.utc_from_timestamp(programme["start"]))
        title = f"{start:%H:%M} {programme['title']}"
        if programme["start"] <= dt_util.utcnow().timestamp():
            title += " (on now)"
        if self._is_scheduled(programme):
            title += " ●"
        return title

    def _is_scheduled(self, programme: dict[str, Any]) -> bool:
        """True if a recording timer overlaps this programme on its channel."""
        return any(
            timer["start"] is not None
            and timer["end"] is not None
            and timer["start"] < programme["end"]
            and timer["end"] > programme["start"]
            and timer.get("channel_id") == programme.get("channel_id")
            for timer in self.coordinator.timers or []
        )

    def _browse_programme(
        self, channel: dict[str, str], key: str, programme: dict[str, Any], media_id: str
    ) -> BrowseMedia:
        """A programme's page: Watch (while it's on) and Record."""
        children = []
        if programme["start"] <= dt_util.utcnow().timestamp():
            children.append(BrowseMedia(
                title=f"Watch {channel['name']}",
                media_class=MediaClass.CHANNEL,
                media_content_id=channel["locator"],
                media_content_type=MediaType.CHANNEL,
                can_play=True,
                can_expand=False,
            ))
        children.append(BrowseMedia(
            title="Scheduled to record ●" if self._is_scheduled(programme) else "Record",
            media_class=MediaClass.EPISODE,
            media_content_id=f"{RECORD_PREFIX}{key}/{programme['start']}/{programme['end']}",
            media_content_type=MEDIA_TYPE_RECORD,
            can_play=True,
            can_expand=False,
        ))
        if programme.get("description"):
            # The browser has no text field; a non-playable item shows the description
            children.append(BrowseMedia(
                title=programme["description"],
                media_class=MediaClass.DIRECTORY,
                media_content_id=f"{media_id}/info",
                media_content_type="",
                can_play=False,
                can_expand=False,
            ))
        return _directory(media_id, self._programme_title(programme), MediaClass.EPISODE, children)

    async def _async_record_from_guide(self, media_id: str) -> None:
        try:
            key, start, end = media_id[len(RECORD_PREFIX):].split("/")
            begin, finish = int(start), int(end)
        except ValueError as err:
            raise HomeAssistantError(f"Bad recording request: {media_id}") from err
        channel = self.coordinator.channel_by_key(key)
        if not channel:
            raise HomeAssistantError(f"Unknown channel: {key}")
        await self.coordinator.async_record(
            channel=channel["locator"],
            start=dt_util.utc_from_timestamp(begin),
            end=dt_util.utc_from_timestamp(finish),
        )

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        """Switch to a channel/input given its locator, name or favourite number,
        or programme a recording picked in the guide."""
        if media_id.startswith(RECORD_PREFIX):
            await self._async_record_from_guide(media_id)
            return
        item = self.coordinator.find_channel(media_id)
        locator = item["locator"] if item else media_id
        if not item and not media_id.startswith("channel://"):
            raise HomeAssistantError(f"Unknown Loewe channel or input: {media_id}")
        if not await self.coordinator.async_set_channel(locator):
            raise HomeAssistantError(f"Loewe TV did not switch to {media_id}")

    # ---------- Commands ----------
    def _set_optimistic(self, **device_changes: Any) -> None:
        """Publish an optimistic device state (power/volume/mute) to all entities.

        Uses a copy of the coordinator data; the next poll replaces it with the TV's state.
        """
        data = self.coordinator.data or {}
        device = {**(data.get("device") or {}), **device_changes}
        self.coordinator.async_set_updated_data({**data, "device": device})

    async def async_turn_off(self) -> None:
        """Put the TV into standby (discrete power-off key)."""
        if await self.coordinator.async_power_off():
            self._set_optimistic(ha_state=MediaPlayerState.OFF)

    async def async_turn_on(self) -> None:
        """Wake the TV (Wake-on-LAN + discrete power-on key); the next poll confirms it."""
        await self.coordinator.async_power_on()

    async def async_set_volume_level(self, volume: float) -> None:
        raw_value = int(volume * 1_000_000)
        if await self.coordinator.async_set_volume(raw_value):
            self._set_optimistic(volume=raw_value)

    async def async_mute_volume(self, mute: bool) -> None:
        if await self.coordinator.async_set_mute(mute):
            self._set_optimistic(mute=mute)

    async def async_select_source(self, source: str) -> None:
        """Switch to an AV input, or to the TV tuner (last watched or first favourite channel)."""
        if source == "TV":
            locator = (
                self.coordinator.last_tv_locator
                or await self.coordinator.async_get_first_tv_channel()
            )
            if not locator:
                _LOGGER.warning("No TV channels available to zap to")
                return
        else:
            locator = next(
                (src["locator"] for src in self.coordinator.available_sources if src["name"] == source),
                None,
            )
            if not locator:
                _LOGGER.warning("Requested source %s not found", source)
                return

        if await self.coordinator.async_set_channel(locator):
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Switching to %s (%s) failed", source, locator)


def _directory(
    media_id: str,
    title: str,
    children_class: MediaClass,
    children: list[BrowseMedia] | None = None,
    media_class: MediaClass = MediaClass.DIRECTORY,
) -> BrowseMedia:
    return BrowseMedia(
        title=title,
        media_class=media_class,
        media_content_id=media_id,
        media_content_type="",
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=children_class,
    )


def _local_date(timestamp: int, today: date) -> date:
    """The local date a programme starts on (one on now that began yesterday counts as today)."""
    return max(dt_util.as_local(dt_util.utc_from_timestamp(timestamp)).date(), today)


def _day_title(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return f"{day:%A} {day.day} {day:%B}"

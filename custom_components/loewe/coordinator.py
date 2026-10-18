"""Coordinator for Loewe TV integration (stateless single-source session)."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Optional
from xml.sax.saxutils import escape
from .soap import LoeweSoapClient
from . import parsers
from .const import (
    DOMAIN,
    SOAP_PREFIX,
    DEFAULT_POLL_INTERVAL,
    CHANNEL_PAGE_SIZE,
    MAX_CHANNELS,
    CONF_TV_MAC,
    CONF_CLIENT_MAC,
    CONF_CLIENT_ID,
    CONF_FCID,
    CONF_TMDB_API_KEY,
    LOEWE_RC_CODES,
)
from .network import async_send_wol
from .tmdb import TmdbArtwork
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.components.media_player import MediaPlayerState

import logging
import asyncio
import time

_LOGGER = logging.getLogger(__name__)

# Waking from standby, the TV drops off the network for ~30 s while it boots
# (picture already on). Within POWER_ON_GRACE of a power-on, a lost connection
# means it is booting and it is reported on; a TV that was just on keeps its
# state through a drop of up to RECONNECT_GRACE. Switched off normally, it
# stays reachable and reports standby, so "off" is still immediate.
RECONNECT_GRACE = 45
POWER_ON_GRACE = 60

# Loaded while the TV is still starting up, AV inputs come back with
# placeholder names (e.g. "#3055 1" for an input named "Apple TV"). Such a
# list is fetched again, every AV_NAMES_RETRY seconds while the TV is on, up
# to AV_NAMES_ATTEMPTS times (an input might genuinely keep such a name).
AV_NAMES_RETRY = 30
AV_NAMES_ATTEMPTS = 10

# Recording timers change rarely (and only from the TV's menu or our own
# record action, which refreshes them at once), so they are polled slowly,
# plus just after a timer is due to start or end so "recording now" is prompt.
TIMERS_POLL_INTERVAL = 300
TIMERS_EDGE_DELAY = 30

# A channel's guide (a week of programmes) is read in one request and kept this long
GUIDE_CACHE_SECONDS = 600
GUIDE_MAX_PROGRAMMES = 1000

# ProgramTimer's repeatDays bitmask (API spec 9.13)
REPEAT_DAY_BITS = {"sun": 0x01, "mon": 0x02, "tue": 0x04, "wed": 0x08, "thu": 0x10, "fri": 0x20, "sat": 0x40}

type LoeweConfigEntry = ConfigEntry[LoeweTVCoordinator]


class LoeweTVCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages Loewe TV session, state, and polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        resource_path: str,
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Loewe TV Coordinator",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self._entry = entry
        self.soap = LoeweSoapClient(hass, host, resource_path)

        # Cached and runtime state
        self.available_sources: list[dict[str, str]] = []
        self.current_locator: Optional[str] = None
        self.last_tv_locator: Optional[str] = None
        self._device_info: dict[str, Any] = {}
        self.device_name: Optional[str] = None
        self._reachable = True

        # Channel lists (loaded with the AV sources) and the now-playing cache
        self.favourite_channels: list[dict[str, str]] = []
        self.all_channels: list[dict[str, str]] = []
        self._channels_by_uuid: dict[str, dict[str, str]] = {}
        self._channels_by_key: dict[str, dict[str, str]] = {}
        self._sources_loaded = False
        self._avlist_view: Optional[str] = None
        self._av_names_attempts = 0
        self._av_names_checked_at = 0.0
        self.current_channel: Optional[dict[str, str]] = None
        self.current_event: dict[str, Any] = {}
        self.next_event: dict[str, Any] = {}
        self._event_locator: Optional[str] = None
        self._event_expires = 0.0
        self._channel_changed_at = 0.0
        self._last_on_at = 0.0
        self._power_on_at = 0.0
        self.artwork: Optional[str] = None
        # Recording timers (None until read; kept while the TV is unreachable)
        self.timers: Optional[list[dict[str, Any]]] = None
        self._timers_checked_at = 0.0
        self._timers_due_at = 0.0  # wall-clock time of the next timer start/end
        # Programme guide per channel key: (fetched at, programmes)
        self._guides: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self.tmdb: Optional[TmdbArtwork] = None
        self._tmdb_key: Optional[str] = None
        self.set_tmdb_key(entry.options.get(CONF_TMDB_API_KEY) if entry else None)

        # Session IDs and MACs persisted in the config entry (none during the config flow)
        data = entry.data if entry else {}
        self.client_id: Optional[str] = data.get(CONF_CLIENT_ID)
        self.fcid: Optional[str] = data.get(CONF_FCID)
        self.tv_mac: Optional[str] = data.get(CONF_TV_MAC)
        self.client_mac: Optional[str] = data.get(CONF_CLIENT_MAC)

    # ---------------------- Polling ----------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll TV for current state and cache derived values."""
        _LOGGER.debug(
            "Polling Loewe TV (ClientId=%s, FCID=%s, UUID=%s)",
            self.client_id,
            self.fcid,
            self.client_mac,
        )

        # --- Step 1: status first (determines power/session validity).
        # _safe_request repairs the session itself if the reply comes back empty.
        status_resp = await self._safe_request("GetCurrentStatus")
        if status_resp is None and self.data is not None:
            if time.monotonic() - self._power_on_at < POWER_ON_GRACE:
                # Asked to power on and now off the network: it is booting
                # (picture on, control not ready yet). Report it on.
                _LOGGER.debug("Loewe TV not answering after power-on; reporting it on while it boots")
                device = {**(self.data.get("device") or {}), "ha_state": MediaPlayerState.ON}
                return {**self.data, "device": device}
            if time.monotonic() - self._last_on_at < RECONNECT_GRACE:
                _LOGGER.debug("Loewe TV briefly not answering; keeping the last state")
                return self.data
        if status_resp is None:
            # TV in deep sleep or network unreachable -> report OFF
            if self._reachable:
                _LOGGER.info("Loewe TV at %s is not responding; treating it as off", self.soap.host)
                self._reachable = False
            self._clear_now_playing()
            return {
                "status": {"ha_state": MediaPlayerState.OFF},
                "playback": {},
                "device": {"ha_state": MediaPlayerState.OFF, "volume": None, "mute": None},
                "timers": self.timers,
            }

        if not self._reachable:
            _LOGGER.info("Loewe TV at %s is responding again", self.soap.host)
            self._reachable = True

        status = parsers.parse_status(status_resp)
        if not status:
            raise UpdateFailed("Loewe TV returned an empty status, even after re-pairing")
        if status.get("ha_state") == MediaPlayerState.ON:
            self._last_on_at = time.monotonic()

        # After status is valid, ensure we have sources and channels
        if not self._sources_loaded:
            try:
                await self.async_refresh_sources()
            except Exception as e:
                _LOGGER.debug("Unable to refresh sources: %s", e)
        elif status.get("ha_state") == MediaPlayerState.ON:
            await self._async_retry_av_names()

        # Timers are readable in standby too
        if (
            time.monotonic() - self._timers_checked_at >= TIMERS_POLL_INTERVAL
            or (self._timers_due_at and time.time() >= self._timers_due_at)
        ):
            await self.async_refresh_timers()

        # --- Step 2: remaining calls only if status was valid
        playback_resp = await self._safe_request("GetCurrentPlayback")
        device = await self.async_get_device_data()
        volume_resp = await self._safe_request("GetVolume")
        mute_resp = await self._safe_request("GetMute")

        playback = parsers.parse_playback(playback_resp)
        volume = parsers.parse_volume(volume_resp)
        mute = parsers.parse_mute(mute_resp)

        # Remember last TV channel locator if current playback is not an AV source
        if playback and (locator := playback.get("Locator")):
            av_locators = {s["locator"] for s in self.available_sources if "locator" in s}
            if locator not in av_locators:
                if locator != self.last_tv_locator:
                    _LOGGER.debug("Updating last TV locator to %s", locator)
                    self.last_tv_locator = locator

        # --- Step 3: update cached state
        # GetCurrentStatus carries no locator; the active one comes from GetCurrentPlayback
        self.current_locator = playback.get("Locator") or self.current_locator

        # Now playing: only while the TV is actually on (standby still answers playback)
        if status.get("ha_state") == MediaPlayerState.ON:
            self.current_channel = self.lookup_channel(
                playback.get("Locator"), playback.get("MediaItemUuid")
            )
            await self._async_update_events()
        else:
            self._clear_now_playing()
        self._device_info = device or self._device_info
        self.device_name = device.get("NetworkHostName") or self.device_name

        if tvmac := parsers.device_mac(device):
            self.tv_mac = tvmac

        data = {
            "status": status,
            "playback": playback,
            "channel": self.current_channel,
            "event": self.current_event,
            "next_event": self.next_event,
            "artwork": self.artwork,
            "device": {
                "ha_state": status.get("ha_state", "unknown"),
                "volume": volume,
                "mute": mute,
            },
            "timers": self.timers,
        }

        return data

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info shared by all of this TV's entities."""
        device = self._device_info or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self.device_name or self._entry.title or "Loewe TV",
            manufacturer="Loewe",
            model=device.get("Chassis") or "TV",
            sw_version=device.get("SW-Version") or None,
        )

    # ---------------------- Session Management ----------------------

    async def async_request_access(self, app_name: str) -> dict[str, Any] | None:
        """Pair with the TV and store session IDs."""
        result = await self.soap.request_access(app_name)
        if result and result.get("State", "").lower() == "accepted":
            self.client_id = result.get("ClientId")
            self.fcid = result.get("fcid")
            _LOGGER.debug("Session established: ClientId=%s, FCID=%s", self.client_id, self.fcid)
            self._persist_session()
        else:
            _LOGGER.warning("RequestAccess failed or rejected: %s", result)
        return result

    async def _repair_session(self) -> bool:
        """Re-request pairing if the TV invalidates current session."""
        _LOGGER.debug("Attempting session repair (RequestAccess)")
        result = await self.async_request_access("HomeAssistant")

        # If initial result is pending, wait briefly and retry once
        if result and result.get("State", "").lower() == "pending":
            _LOGGER.debug("Session repair returned 'Pending' – waiting to retry")
            await asyncio.sleep(0.5)
            result = await self.async_request_access("HomeAssistant")

        ok = bool(result and result.get("State", "").lower() == "accepted")
        _LOGGER.debug("Session repair %s", "successful" if ok else f"failed: {result}")
        return ok

    def _persist_session(self) -> None:
        """Store a renewed ClientId/fcid so it survives a restart."""
        if not self._entry:
            return
        if (
            self._entry.data.get(CONF_CLIENT_ID) == self.client_id
            and self._entry.data.get(CONF_FCID) == self.fcid
        ):
            return
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_CLIENT_ID: self.client_id, CONF_FCID: self.fcid},
        )

    async def _send(self, action: str, extra_xml: str) -> Optional[str]:
        """Send one SOAP action using the current session IDs."""
        _LOGGER.debug(
            "SOAP request(%s): using ClientId=%s, FCID=%s",
            action, self.client_id, self.fcid
        )
        body = self.soap.build_body(
            action,
            fcid=self.fcid,
            client_id=self.client_id,
            extra_xml=extra_xml,
        )
        return await self.soap.request(action, body)

    async def _safe_request(self, action: str, *, extra_xml: str = "") -> Optional[str]:
        """Perform a SOAP call, re-pairing once if a Get* call returns an empty reply.

        The TV answers Get* calls made with an expired ClientId with an empty
        <XXXResponse>. Commands are not retried because some of them (e.g.
        ZapToMedia) legitimately reply with an empty body. Network failures
        (None) are not retried either: the TV is simply off or unreachable.
        """
        resp = await self._send(action, extra_xml)
        if action.startswith("Get") and parsers.is_empty_response(resp):
            _LOGGER.debug("SOAP %s returned an empty response; attempting session repair", action)
            if await self._repair_session():
                resp = await self._send(action, extra_xml)
        return resp

    async def async_get_device_data(self) -> dict[str, Any]:
        """Return parsed GetDeviceData (chassis, software version, MACs, host name)."""
        return parsers.parse_device_data(await self._safe_request("GetDeviceData"))

    @property
    def current_source_name(self) -> Optional[str]:
        """Name of the active input: an AV source name, "TV", or None if unknown."""
        loc = self.current_locator
        if not loc:
            return None
        for src in self.available_sources:
            if src["locator"] == loc:
                return src["name"]
        if loc == self.last_tv_locator:
            return "TV"
        return None

    # ---------------------- Volume / Mute / Remote ----------------------

    async def async_set_volume(self, raw_value: int) -> bool:
        """Send volume set command to Loewe TV."""
        _LOGGER.debug("Setting volume to %s", raw_value)
        extra_xml = f"<{SOAP_PREFIX}:Value>{raw_value}</{SOAP_PREFIX}:Value>"
        resp = await self._safe_request("SetVolume", extra_xml=extra_xml)
        ok = resp and "<SetVolumeResponse" in resp
        _LOGGER.debug("SetVolume success=%s", ok)
        return bool(ok)

    async def async_set_mute(self, mute: bool) -> bool:
        """Send mute toggle to Loewe TV."""
        _LOGGER.debug("Setting mute to %s", mute)
        value = "1" if mute else "0"
        extra_xml = f"<{SOAP_PREFIX}:Value>{value}</{SOAP_PREFIX}:Value>"
        resp = await self._safe_request("SetMute", extra_xml=extra_xml)
        ok = resp and "<SetMuteResponse" in resp
        _LOGGER.debug("SetMute success=%s", ok)
        return bool(ok)

    async def async_inject_rc_key(self, value: int) -> bool:
        """Inject a remote control key press/release sequence.

        Holding a key is not possible: on the TV tested, a press and a later
        release still count as a single key press.
        """
        _LOGGER.debug("Sending RC key %s", value)
        extra = (
            "<ltv:InputEventSequence>"
            f'<ltv:RCKeyEvent alphabet="l2700" value="{value}" mode="press"/>'
            f'<ltv:RCKeyEvent alphabet="l2700" value="{value}" mode="release"/>'
            "</ltv:InputEventSequence>"
        )
        resp = await self._safe_request("InjectRCKey", extra_xml=extra)
        success = bool(resp)
        _LOGGER.debug("InjectRCKey %s", "succeeded" if success else "failed")
        return success

    async def async_power_off(self) -> bool:
        """Put the TV into standby with the discrete power-off key."""
        return await self.async_inject_rc_key(LOEWE_RC_CODES["power_off"])

    async def _async_follow_up_power_on(self) -> None:
        """Poll every 3 s for up to ~30 s after a power-on until the TV reports on,
        instead of waiting for the next regular poll."""
        for _ in range(10):
            await asyncio.sleep(3)
            await self.async_refresh()
            device = (self.data or {}).get("device", {})
            if device.get("ha_state") == MediaPlayerState.ON:
                return

    async def async_power_on(self) -> bool:
        """Wake the TV: Wake-on-LAN (if the MAC is known), then the discrete power-on key."""
        self._power_on_at = time.monotonic()
        if self._entry:
            self._entry.async_create_background_task(
                self.hass, self._async_follow_up_power_on(), "loewe_power_on_follow_up"
            )
        if self.tv_mac:
            try:
                _LOGGER.debug("Sending Wake-on-LAN to %s", self.tv_mac)
                await async_send_wol(self.hass, self.tv_mac)
                # Give the network interface a moment to wake up
                await asyncio.sleep(1.0)
            except OSError as err:
                _LOGGER.warning("Failed to send Wake-on-LAN packet: %s", err)
        else:
            _LOGGER.debug("No TV MAC address known; skipping Wake-on-LAN")
        return await self.async_inject_rc_key(LOEWE_RC_CODES["power_on"])

    # ---------------------- Sources / Channels ----------------------

    async def async_get_channel_lists(self) -> list[dict[str, Any]]:
        """Retrieve available channel/input lists from the TV."""
        extra = """
            <ltv:QueryParameters>
                <ltv:Range startIndex="0" maxItems="50"/>
            </ltv:QueryParameters>
        """
        resp = await self._safe_request("GetListOfChannelLists", extra_xml=extra)
        return parsers.parse_channel_lists(resp)

    async def async_get_channel_list(self, view_id: str) -> list[dict[str, str]]:
        """Retrieve all items of a channel list (AV inputs or TV channels), page by page.

        Some TVs ignore the requested range and return the whole list in one
        reply, so duplicate items are dropped and a page adding nothing ends the loop.
        """
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        while len(items) < MAX_CHANNELS:
            extra = f"""
                <ltv:ChannelListView>{escape(view_id)}</ltv:ChannelListView>
                <ltv:QueryParameters>
                    <ltv:Range startIndex="{len(items)}" maxItems="{CHANNEL_PAGE_SIZE}" />
                    <ltv:MediaItemInformation>true</ltv:MediaItemInformation>
                    <ltv:MediaItemClass></ltv:MediaItemClass>
                </ltv:QueryParameters>
            """
            resp = await self._safe_request("GetChannelList", extra_xml=extra)
            page, total = parsers.parse_channel_list_page(resp)
            new = [item for item in page if item["locator"] not in seen]
            seen.update(item["locator"] for item in new)
            items.extend(new)
            if not new or total is None or len(items) >= total:
                break
        return items

    async def async_get_first_tv_channel(self) -> Optional[str]:
        """Return the locator of the first TV channel (favourites first, then the full list)."""
        if not self._sources_loaded:
            await self.async_refresh_sources()
        for channel in (self.favourite_channels or self.all_channels)[:1]:
            _LOGGER.debug("Using first TV channel: %s", channel["name"])
            return channel["locator"]
        _LOGGER.debug("No TV channels available to zap to")
        return None

    async def async_refresh_sources(self) -> None:
        """
        (Re)load the AV inputs and the TV channel lists.

        View names are prefixed by type (per the API spec): "avlist" for AV
        inputs, "favlist" for favourites and "fastscan" for the full network
        list. The first list of each type is used.
        """
        lists_ = await self.async_get_channel_lists()
        if not lists_:
            _LOGGER.debug("No channel lists available; will retry on the next poll")
            return

        def first(prefix: str) -> Optional[dict[str, Any]]:
            return next((c for c in lists_ if c["view"].lower().startswith(prefix)), None)

        # The AV list is historically named '#3051'; fall back to the view prefix
        avlist = next((c for c in lists_ if c.get("name") == "#3051"), None) or first("avlist")
        favlist = first("favlist")
        fulllist = first("fastscan")

        self._avlist_view = avlist["view"] if avlist else None
        self.available_sources = await self.async_get_channel_list(avlist["view"]) if avlist else []
        self._av_names_attempts = 0
        self._av_names_checked_at = time.monotonic()
        self.favourite_channels = await self.async_get_channel_list(favlist["view"]) if favlist else []
        self.all_channels = await self.async_get_channel_list(fulllist["view"]) if fulllist else []
        self._index_channels()
        self._sources_loaded = True
        _LOGGER.info(
            "Loaded %d AV sources, %d favourite channels, %d channels in total",
            len(self.available_sources), len(self.favourite_channels), len(self.all_channels),
        )

    @staticmethod
    def _has_placeholder_names(sources: list[dict[str, str]]) -> bool:
        return any(src["name"].startswith("#") for src in sources)

    async def _async_retry_av_names(self) -> None:
        """Fetch the AV inputs again if they were loaded with placeholder names."""
        if (
            not self._avlist_view
            or self._av_names_attempts >= AV_NAMES_ATTEMPTS
            or time.monotonic() - self._av_names_checked_at < AV_NAMES_RETRY
            or not self._has_placeholder_names(self.available_sources)
        ):
            return
        self._av_names_attempts += 1
        self._av_names_checked_at = time.monotonic()
        sources = await self.async_get_channel_list(self._avlist_view)
        if sources:
            self.available_sources = sources
            _LOGGER.debug("Reloaded AV source names: %s", [src["name"] for src in sources])

    # ---------------------- Channel lookup / Now playing ----------------------

    def channel_key(self, channel: dict[str, str]) -> str:
        """Key identifying a cached TV channel, e.g. in media browser IDs."""
        return self._channel_key(channel["locator"])

    def channel_by_key(self, key: str) -> Optional[dict[str, str]]:
        return self._channels_by_key.get(key)

    @staticmethod
    def _channel_key(locator: str) -> str:
        """Key identifying a channel independent of the list it was tuned from.

        Locators look like "channel://<pos>:<channel id>:<list id>"; the middle
        part identifies the channel itself.
        """
        parts = locator.split(":")
        return parts[2] if len(parts) > 2 else locator

    def _index_channels(self) -> None:
        """Rebuild the channel lookup tables from the cached lists."""
        self._channels_by_uuid = {}
        self._channels_by_key = {}
        # Favourites last so their entries (and numbering) win
        for channel in [*self.all_channels, *self.favourite_channels]:
            if channel.get("uuid"):
                self._channels_by_uuid[channel["uuid"]] = channel
            self._channels_by_key[self._channel_key(channel["locator"])] = channel

    def _is_av_locator(self, locator: str) -> bool:
        return any(src["locator"] == locator for src in self.available_sources)

    def lookup_channel(
        self, locator: Optional[str], uuid: Optional[str] = None
    ) -> Optional[dict[str, str]]:
        """Return the cached TV channel for a locator/mediaItemUuid, or None (e.g. an AV input)."""
        if not locator or self._is_av_locator(locator):
            return None
        if uuid and (channel := self._channels_by_uuid.get(uuid)):
            return channel
        return self._channels_by_key.get(self._channel_key(locator))

    def find_channel(self, query: str) -> Optional[dict[str, str]]:
        """Find a TV channel or AV input by locator, name (case-insensitive) or favourite number."""
        query = query.strip()
        everything = [*self.favourite_channels, *self.all_channels, *self.available_sources]
        for item in everything:
            if item["locator"] == query:
                return item
        folded = query.casefold()
        for item in everything:
            if item["name"].casefold() == folded:
                return item
        return next((c for c in self.favourite_channels if c.get("number") == query), None)

    def set_tmdb_key(self, api_key: Optional[str]) -> bool:
        """Turn programme artwork on (a TMDB API key) or off (None/empty); True if changed."""
        api_key = (api_key or "").strip() or None
        if api_key == self._tmdb_key:
            return False
        self._tmdb_key = api_key
        self.tmdb = TmdbArtwork(self.hass, api_key) if api_key else None
        self.artwork = None
        self._event_expires = 0.0  # look the current programme up on the next poll
        return True

    def _clear_now_playing(self) -> None:
        self.current_channel = None
        self.current_event = {}
        self.next_event = {}
        self.artwork = None
        self._event_locator = None
        self._event_expires = 0.0

    async def _async_update_events(self) -> None:
        """Fetch current/next programme when the channel changes or the programme ends."""
        if not self.current_channel:
            self.current_event = {}
            self.next_event = {}
            self.artwork = None
            self._event_locator = None
            return

        now = time.time()
        if self.current_locator != self._event_locator:
            self._channel_changed_at = now
        elif now < self._event_expires:
            return

        player = f"<{SOAP_PREFIX}:Player>0</{SOAP_PREFIX}:Player>"
        self.current_event = parsers.parse_event(
            await self._safe_request("GetCurrentEvent", extra_xml=player)
        )
        self.next_event = parsers.parse_event(
            await self._safe_request("GetNextEvent", extra_xml=player)
        )
        # Straight after a channel change the TV can still answer with the
        # previous channel's programme; treat that as "no EPG yet" so it is retried.
        tuned = self._channel_key(self.current_locator or "")
        for event in (self.current_event, self.next_event):
            if event.get("locator") and self._channel_key(event["locator"]) != tuned:
                _LOGGER.debug(
                    "EPG answered for %s, not the tuned channel; retrying", event["locator"]
                )
                self.current_event, self.next_event = {}, {}
                break
        self._event_locator = self.current_locator
        self.artwork = (
            await self.tmdb.async_lookup(self.current_event.get("name")) if self.tmdb else None
        )

        start = self.current_event.get("start")
        duration = self.current_event.get("duration")
        end = start + duration if start is not None and duration else None
        if end and end > now:
            # Re-check just after the programme ends
            self._event_expires = end + 5
        elif now - self._channel_changed_at < 60:
            # Right after a channel change the TV may not have the EPG yet: retry next poll
            self._event_expires = now
        else:
            self._event_expires = now + 60
        _LOGGER.debug(
            "Now playing on %s: %s (next: %s)",
            self.current_channel["name"],
            self.current_event.get("name"),
            self.next_event.get("name"),
        )

    @property
    def current_service_name(self) -> Optional[str]:
        """Channel name when watching TV, otherwise the AV input name."""
        if self.current_channel:
            return self.current_channel["name"]
        return self.current_source_name

    async def async_set_channel(self, locator: str) -> bool:
        """Switch the TV to a given locator via ZapToMedia."""
        extra = f"""
            <ltv:Player>0</ltv:Player>
            <ltv:Locator>{escape(locator)}</ltv:Locator>
        """
        resp = await self._safe_request("ZapToMedia", extra_xml=extra)

        ok = bool(resp)  # ZapToMedia gives an empty but syntactically valid response on success
        if ok:
            # Optimistic update; the next poll fetches the programme for the new channel
            self.current_locator = locator
            self.current_channel = self.lookup_channel(locator)
            if self.current_channel:
                self.last_tv_locator = locator  # remember last TV channel
            self._event_locator = None
            await self.async_request_refresh()
            if self._entry:
                self._entry.async_create_background_task(
                    self.hass, self._async_follow_up_events(locator), "loewe_epg_follow_up"
                )
        else:
            _LOGGER.debug("ZapToMedia failed for locator %s", locator)

        return ok

    async def _async_follow_up_events(self, locator: str) -> None:
        """After a zap from HA, re-check the programme a few times until the EPG has it.

        The immediate refresh after ZapToMedia usually finds no EPG data yet, and
        coordinator refresh requests are debounced to one per poll interval, so
        only the event calls are repeated here.
        """
        elapsed = 0
        for delay in (2, 2, 3, 3):  # ~2, 4, 7 and 10 s after the zap
            await asyncio.sleep(delay)
            elapsed += delay
            if self.current_locator != locator or not self.current_channel or self.current_event:
                return
            self._event_expires = 0.0  # force a fetch for the same channel
            await self._async_update_events()
            if self.current_event and self.data is not None:
                _LOGGER.debug("Programme found ~%ss after channel change", elapsed)
                self.async_set_updated_data(
                    {
                        **self.data,
                        "event": self.current_event,
                        "next_event": self.next_event,
                        "artwork": self.artwork,
                    }
                )
                return

    async def async_channel_up(self) -> None:
        await self.async_inject_rc_key(LOEWE_RC_CODES["prog_up"])

    async def async_channel_down(self) -> None:
        await self.async_inject_rc_key(LOEWE_RC_CODES["prog_down"])

    # ---------------------- Recording timers ----------------------

    async def async_refresh_timers(self) -> None:
        """Re-read the TV's recording timers (left as they were if the TV doesn't answer)."""
        self._timers_checked_at = time.monotonic()
        timers = parsers.parse_timer_list(await self._safe_request("GetTimerList"))
        if timers is not None:
            await self._async_name_timers(timers)
            self.timers = timers
        now = time.time()
        edges = [
            edge + TIMERS_EDGE_DELAY
            for timer in self.timers or []
            for edge in (timer["start"], timer["end"])
            if edge is not None and edge + TIMERS_EDGE_DELAY > now
        ]
        self._timers_due_at = min(edges, default=0.0)

    async def _async_name_timers(self, timers: list[dict[str, Any]]) -> None:
        """Give timers the TV left as "Recording" the title of the programme they cover.

        The TV is meant to take the title from the guide, but timers set through
        the API keep the default name (and no EPG event ID).
        """
        for timer in timers:
            if timer["title"] not in (None, "Recording") or timer["start"] is None or timer["end"] is None:
                continue
            channel = self._channels_by_key.get(timer.get("channel_id") or "")
            if not channel:
                continue
            try:
                programmes = await self.async_get_guide(channel)
            except HomeAssistantError:
                continue

            def overlap(programme: dict[str, Any]) -> int:
                return min(programme["end"], timer["end"]) - max(programme["start"], timer["start"])

            best = max(programmes, key=overlap, default=None)
            if best and overlap(best) > 0:
                timer["title"] = best["title"]

    async def async_record(
        self,
        *,
        programme: Optional[str] = None,
        channel: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        duration: Optional[timedelta] = None,
        repeat_days: Optional[list[str]] = None,
    ) -> None:
        """Programme a recording on the TV's DR+ recorder.

        Either `programme` ("current" or "next" on the tuned channel, timed from
        the EPG) or `start` plus `end` or `duration` (on `channel`, default the
        tuned one). The TV names the recording after the EPG event it matches,
        otherwise "Recording". Raises ServiceValidationError for bad input and
        HomeAssistantError if the TV refuses or doesn't answer.
        """
        if not programme and start is None:
            raise ServiceValidationError("Give a programme (current or next) or a start time")
        if channel:
            if not self._sources_loaded:
                await self.async_refresh_sources()
            found = self.find_channel(channel)
            tv_channel = self.lookup_channel(found["locator"]) if found else None
            if not tv_channel:
                raise ServiceValidationError(f"No TV channel called {channel!r} on the Loewe TV")
        else:
            tv_channel = self.current_channel
            if not tv_channel:
                raise ServiceValidationError(
                    "The Loewe TV isn't showing a TV channel; give a channel to record"
                )

        now = time.time()
        if programme:
            if tv_channel is not self.current_channel:
                raise ServiceValidationError(
                    "Only the tuned channel's programmes are known; "
                    "give a start time to record another channel"
                )
            event = self.current_event if programme == "current" else self.next_event
            if event.get("start") is None or not event.get("duration"):
                raise ServiceValidationError(f"The TV has no programme information for the {programme} programme")
            begin = event["start"]
            finish = begin + event["duration"]
            if programme == "current":
                # Already started: record from now to the end of the programme
                begin = int(now)
        else:
            if (end is None) == (duration is None):
                raise ServiceValidationError("Give either an end time or a duration")
            begin = int(dt_util.as_timestamp(_local_datetime(start)))
            finish = (
                int(dt_util.as_timestamp(_local_datetime(end)))
                if end is not None
                else begin + int(duration.total_seconds())
            )
            begin = max(begin, int(now))  # already under way: record the rest
        if finish <= max(begin, now):
            raise ServiceValidationError("That recording would already have ended")

        repeat = 0
        for day in repeat_days or []:
            repeat |= REPEAT_DAY_BITS[day]

        extra = (
            f"<{SOAP_PREFIX}:Device>PVR</{SOAP_PREFIX}:Device>"
            f"<{SOAP_PREFIX}:RecordingType>default</{SOAP_PREFIX}:RecordingType>"
            f"<{SOAP_PREFIX}:Locator>{escape(tv_channel['locator'])}</{SOAP_PREFIX}:Locator>"
            f'<{SOAP_PREFIX}:Timer starttime="{begin}" duration="{finish - begin}" repeatDays="{repeat}"/>'
        )
        _LOGGER.debug(
            "Programming a recording on %s from %s for %s s (repeat %#x)",
            tv_channel["name"], begin, finish - begin, repeat,
        )
        result = parsers.parse_result(await self._safe_request("ProgramTimer", extra_xml=extra))
        if result is None:
            raise HomeAssistantError("The Loewe TV didn't answer the recording request")
        if result != 0:
            raise HomeAssistantError(f"The Loewe TV refused the recording (error {result})")

        # "Accepted" doesn't guarantee the timer exists (a conflict can need
        # confirming on the TV), so show what the TV now actually has.
        await self.async_refresh_timers()
        if self.data is not None:
            self.async_set_updated_data({**self.data, "timers": self.timers})

    # ---------------------- Programme guide ----------------------

    @staticmethod
    def dvb_triplet(channel: dict[str, str]) -> Optional[tuple[int, int, int]]:
        """(original network ID, transport stream ID, service ID) of a TV channel.

        A channel's mediaItemUuid ends in them as 4 hex digits each, with
        "ffff" between the network and transport stream IDs, e.g.
        "chl0:00-0002233affff104410bf" -> (0x233a, 0x1044, 0x10bf).
        """
        uuid = channel.get("uuid") or ""
        digits = uuid.rsplit("-", 1)[-1]
        if not uuid.startswith("chl") or len(digits) < 16:
            return None
        try:
            return int(digits[-16:-12], 16), int(digits[-8:-4], 16), int(digits[-4:], 16)
        except ValueError:
            return None

    async def async_get_guide(self, channel: dict[str, str]) -> list[dict[str, Any]]:
        """Programmes on a channel from the one on now to the end of the TV's guide (about a week).

        Read from the TV's own EPG table with an iterator; cached for GUIDE_CACHE_SECONDS.
        Raises HomeAssistantError if the channel has no DVB IDs or the TV doesn't answer.
        """
        key = self._channel_key(channel["locator"])
        now = time.time()
        cached = self._guides.get(key)
        if cached and now - cached[0] < GUIDE_CACHE_SECONDS:
            return [p for p in cached[1] if p["end"] > now]

        triplet = self.dvb_triplet(channel)
        if not triplet:
            raise HomeAssistantError(f"No guide available for {channel['name']}")
        onid, tsid, sid = triplet

        def selection(field: int, condition: int, value: int) -> str:
            return (
                f"<{SOAP_PREFIX}:Selection><{SOAP_PREFIX}:Field>{field}</{SOAP_PREFIX}:Field>"
                f"<{SOAP_PREFIX}:Condition>{condition}</{SOAP_PREFIX}:Condition>"
                f"<{SOAP_PREFIX}:Value>{value}</{SOAP_PREFIX}:Value></{SOAP_PREFIX}:Selection>"
            )

        fields = "".join(f"<{SOAP_PREFIX}:Field>{f}</{SOAP_PREFIX}:Field>" for f in parsers.EPG_FIELDS)
        # Condition 1 is "equals"; seeking to the first programme whose end
        # (2008) is after now (condition 5) starts the list at the one on now.
        extra = (
            f"<{SOAP_PREFIX}:TableName>de.loewe.sl2.epg</{SOAP_PREFIX}:TableName>"
            f"<{SOAP_PREFIX}:Type>0</{SOAP_PREFIX}:Type>"
            f"<{SOAP_PREFIX}:Selections>{selection(2002, 1, onid)}{selection(2000, 1, sid)}"
            f"{selection(2001, 1, tsid)}</{SOAP_PREFIX}:Selections>"
            f"<{SOAP_PREFIX}:Fields>{fields}</{SOAP_PREFIX}:Fields>"
            f"<{SOAP_PREFIX}:Orders><{SOAP_PREFIX}:Order><{SOAP_PREFIX}:Field>2007</{SOAP_PREFIX}:Field>"
            f"<{SOAP_PREFIX}:Direction>1</{SOAP_PREFIX}:Direction></{SOAP_PREFIX}:Order></{SOAP_PREFIX}:Orders>"
            f"<{SOAP_PREFIX}:NotifyUpdate>NO</{SOAP_PREFIX}:NotifyUpdate>"
            f'<{SOAP_PREFIX}:QueryParameters><{SOAP_PREFIX}:Range startIndex="0" maxItems="{GUIDE_MAX_PROGRAMMES}"/>'
            f"</{SOAP_PREFIX}:QueryParameters>"
            f"<{SOAP_PREFIX}:SeekToContentParameters><{SOAP_PREFIX}:Selections>{selection(2008, 5, int(now))}"
            f"</{SOAP_PREFIX}:Selections><{SOAP_PREFIX}:Which>0</{SOAP_PREFIX}:Which>"
            f"<{SOAP_PREFIX}:Offset>0</{SOAP_PREFIX}:Offset><{SOAP_PREFIX}:WindowSize>0</{SOAP_PREFIX}:WindowSize>"
            f"</{SOAP_PREFIX}:SeekToContentParameters>"
        )
        programmes = parsers.parse_guide(await self._safe_request("CreateIterator", extra_xml=extra))
        if programmes is None:
            raise HomeAssistantError(f"The Loewe TV didn't send the guide for {channel['name']}")
        programmes = [{**p, "channel_id": key} for p in programmes if p["end"] > now]
        self._guides[key] = (now, programmes)
        _LOGGER.debug("Guide for %s: %d programmes", channel["name"], len(programmes))
        return programmes


    # ---------------------- Recordings archive ----------------------

    async def async_get_recordings(self) -> list[dict[str, Any]]:
        """The DR+ recorder's recordings, newest first. Raises HomeAssistantError if no answer."""
        extra = (
            f"<{SOAP_PREFIX}:QueryParameters>"
            f'<{SOAP_PREFIX}:Range startIndex="0" maxItems="1000"/>'
            f"</{SOAP_PREFIX}:QueryParameters>"
        )
        recordings = parsers.parse_recordings(await self._safe_request("GetDRPlusArchive", extra_xml=extra))
        if recordings is None:
            raise HomeAssistantError("The Loewe TV didn't send its recordings")
        return recordings


def _local_datetime(value: datetime) -> datetime:
    """Treat a naive date/time (as service calls usually give) as HA's local time."""
    return value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone())

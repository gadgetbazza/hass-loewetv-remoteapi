"""Coordinator for Loewe TV integration (stateless single-source session)."""

from __future__ import annotations
from datetime import timedelta
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
    LOEWE_RC_CODES,
)
from .network import async_send_wol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.media_player import MediaPlayerState

import logging
import asyncio
import time

_LOGGER = logging.getLogger(__name__)

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
        self.current_channel: Optional[dict[str, str]] = None
        self.current_event: dict[str, Any] = {}
        self.next_event: dict[str, Any] = {}
        self._event_locator: Optional[str] = None
        self._event_expires = 0.0
        self._channel_changed_at = 0.0

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
            }

        if not self._reachable:
            _LOGGER.info("Loewe TV at %s is responding again", self.soap.host)
            self._reachable = True

        status = parsers.parse_status(status_resp)
        if not status:
            raise UpdateFailed("Loewe TV returned an empty status, even after re-pairing")

        # After status is valid, ensure we have sources and channels
        if not self._sources_loaded:
            try:
                await self.async_refresh_sources()
            except Exception as e:
                _LOGGER.debug("Unable to refresh sources: %s", e)

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
            "device": {
                "ha_state": status.get("ha_state", "unknown"),
                "volume": volume,
                "mute": mute,
            },
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

    async def async_power_on(self) -> bool:
        """Wake the TV: Wake-on-LAN (if the MAC is known), then the discrete power-on key."""
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

        self.available_sources = await self.async_get_channel_list(avlist["view"]) if avlist else []
        self.favourite_channels = await self.async_get_channel_list(favlist["view"]) if favlist else []
        self.all_channels = await self.async_get_channel_list(fulllist["view"]) if fulllist else []
        self._index_channels()
        self._sources_loaded = True
        _LOGGER.info(
            "Loaded %d AV sources, %d favourite channels, %d channels in total",
            len(self.available_sources), len(self.favourite_channels), len(self.all_channels),
        )

    # ---------------------- Channel lookup / Now playing ----------------------

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

    def _clear_now_playing(self) -> None:
        self.current_channel = None
        self.current_event = {}
        self.next_event = {}
        self._event_locator = None
        self._event_expires = 0.0

    async def _async_update_events(self) -> None:
        """Fetch current/next programme when the channel changes or the programme ends."""
        if not self.current_channel:
            self.current_event = {}
            self.next_event = {}
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
        self._event_locator = self.current_locator

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
                    {**self.data, "event": self.current_event, "next_event": self.next_event}
                )
                return

    async def async_channel_up(self) -> None:
        await self.async_inject_rc_key(LOEWE_RC_CODES["prog_up"])

    async def async_channel_down(self) -> None:
        await self.async_inject_rc_key(LOEWE_RC_CODES["prog_down"])

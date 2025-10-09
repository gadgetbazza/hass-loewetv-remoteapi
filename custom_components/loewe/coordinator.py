"""Coordinator for Loewe TV integration (stateless single-source session)."""

from __future__ import annotations
from datetime import timedelta
from typing import Any, Optional
from .soap import LoeweSoapClient
from . import parsers
from .const import SOAP_PREFIX, DEFAULT_POLL_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

import logging
import asyncio

_LOGGER = logging.getLogger(__name__)


class LoeweTVCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages Loewe TV session, state, and polling."""

    def __init__(self, hass: HomeAssistant, host: str, resource_path: str, entry=None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Loewe TV Coordinator",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.hass = hass
        self._entry = entry
        self.soap = LoeweSoapClient(hass, host, resource_path)

        # Cached and runtime state
        self.available_sources: list[dict[str, str]] = []
        self.current_locator: Optional[str] = None
        self._last_tv_locator: Optional[str] = None
        self._device_info: dict[str, Any] = {}
        self.tv_mac: Optional[str] = None
        self.device_name: Optional[str] = None
        self._last_raw_response: Optional[str] = None

        # Session IDs
        self.device_uuid: Optional[str] = None  # (actually MAC)
        self.client_id: Optional[str] = None
        self.fcid: Optional[str] = None

    # ---------------------- Polling ----------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll TV for current state and cache derived values."""
        _LOGGER.debug(
            "Polling Loewe TV (ClientId=%s, FCID=%s, UUID=%s)",
            self.client_id,
            self.fcid,
            self.device_uuid,
        )

        # --- Step 1: status first (determines power/session validity)
        try:
            status_resp = await self._safe_request("GetCurrentStatus")
        except Exception as e:
            _LOGGER.debug("GetCurrentStatus request failed (network/timeout): %s", e)
            # TV likely in deep sleep or network unreachable -> assume OFF and bail out
            return {
                "status": {"ha_state": MediaPlayerState.OFF},
                "playback": {},
                "device": {"ha_state": MediaPlayerState.OFF, "volume": None, "mute": None},
            }

        if not status_resp:
            _LOGGER.debug("No response from TV — assuming powered off / deep sleep")
            return {
                "status": {"ha_state": MediaPlayerState.OFF},
                "playback": {},
                "device": {"ha_state": MediaPlayerState.OFF, "volume": None, "mute": None},
            }

        status = parsers.parse_status(status_resp)

        # If empty status → attempt repair once, then bail out this cycle
        if not status:
            _LOGGER.debug("Empty GetCurrentStatus response — attempting session repair")
            repaired = await self._repair_session()
            if not repaired:
                _LOGGER.debug("Session repair failed — skipping remaining polling cycle")
                return {}
            _LOGGER.debug("Session repaired — continue remaining polling cycle until next run")
            status_resp = await self._safe_request("GetCurrentStatus")
            status = parsers.parse_status(status_resp)
            if not status:
                _LOGGER.debug("Status still empty after successful repair — skipping cycle")
                return {}

        # After status is valid, ensure we have sources
        if not self.available_sources:
            try:
                await self.async_refresh_sources()
            except Exception as e:
                _LOGGER.debug("Unable to refresh sources: %s", e)

        # --- Step 2: remaining calls only if status was valid
        playback_resp = await self._safe_request("GetCurrentPlayback")
        device_resp = await self._safe_request("GetDeviceData")
        volume_resp = await self._safe_request("GetVolume")
        mute_resp = await self._safe_request("GetMute")

        playback = parsers.parse_playback(playback_resp)
        device = parsers.parse_device_data(device_resp)
        volume = parsers.parse_volume(volume_resp)
        mute = parsers.parse_mute(mute_resp)

        # Remember last TV channel locator if current playback is not an AV source
        if playback and (locator := playback.get("Locator")):
            av_locators = {s["locator"] for s in self.available_sources if "locator" in s}
            if locator not in av_locators:
                if locator != self._last_tv_locator:
                    _LOGGER.debug("Updating last TV locator to %s", locator)
                    self._last_tv_locator = locator

        # --- Step 3: update cached state
        self.current_locator = status.get("CurrentLocator") or self.current_locator
        self._device_info = device or self._device_info
        self.device_name = device.get("NetworkHostName") or self.device_name

        tvmac = device.get("MAC-Address-LAN") or device.get("MAC-Address")
        if tvmac:
            self.tv_mac = tvmac

        data = {
            "status": status,
            "playback": playback,
            "device": {
                "ha_state": status.get("ha_state", "unknown"),
                "volume": volume,
                "mute": mute,
            },
        }

        self._last_raw_response = self.soap._last_raw_response
        return data

    # ---------------------- Session Management ----------------------

    async def async_request_access(self, app_name: str) -> dict[str, Any] | None:
        """Pair with the TV and store session IDs."""
        result = await self.soap.request_access(app_name)
        if result and result.get("State", "").lower() == "accepted":
            self.client_id = result.get("ClientId")
            self.fcid = result.get("fcid")
            _LOGGER.debug("Session established: ClientId=%s, FCID=%s", self.client_id, self.fcid)
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

    async def _safe_request(self, action: str, *, extra_xml: str = "") -> Optional[str]:
        """Perform a SOAP call with session repair logic."""
        _LOGGER.debug(
            "SOAP safe_request(%s): using ClientId=%s, FCID=%s",
            action, self.client_id, self.fcid
        )

        body = self.soap.build_body(
            action,
            fcid=self.fcid,
            client_id=self.client_id,
            extra_xml=extra_xml,
        )

        resp = await self.soap.request(action, body)
        if not resp or f"<{action}Response" in resp and f">{action}Response>" in resp:
            _LOGGER.debug("SOAP %s returned empty response — attempting repair", action)
            if await self._repair_session():
                body = self.soap.build_body(
                    action,
                    fcid=self.fcid,
                    client_id=self.client_id,
                    extra_xml=extra_xml,
                )
                resp = await self.soap.request(action, body)
        return resp

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
        """Inject a remote control key press/release sequence."""
        _LOGGER.debug("Sending RC key %s", value)

        extra = (
            "<ltv:InputEventSequence>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{value}\" mode=\"press\"/>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{value}\" mode=\"release\"/>"
            "</ltv:InputEventSequence>"
        )

        resp = await self._safe_request("InjectRCKey", extra_xml=extra)
        success = bool(resp)
        _LOGGER.debug("InjectRCKey %s", "succeeded" if success else "failed")
        return success

    # ---------------------- Sources / Channels ----------------------

    async def async_get_channel_lists(self) -> list[dict[str, str]]:
        """Retrieve available channel/input lists from the TV."""
        extra = """
            <ltv:QueryParameters>
                <ltv:Range startIndex="0" maxItems="20"/>
            </ltv:QueryParameters>
        """
        resp = await self._safe_request("GetListOfChannelLists", extra_xml=extra)
        return parsers.parse_channel_lists(resp)

    async def async_get_channel_list(self, view_id: str) -> list[dict[str, str]]:
        """Retrieve items of a channel list (e.g., AV inputs)."""
        extra = f"""
            <ltv:ChannelListView>{view_id}</ltv:ChannelListView>
            <ltv:QueryParameters>
                <ltv:Range startIndex="0" maxItems="20" />
                <ltv:MediaItemInformation>true</ltv:MediaItemInformation>
                <ltv:MediaItemClass></ltv:MediaItemClass>
            </ltv:QueryParameters>
        """
        resp = await self._safe_request("GetChannelList", extra_xml=extra)
        return parsers.parse_channel_list(resp)

    async def async_get_first_tv_channel(self) -> Optional[str]:
        """
        Return the locator of the first TV channel.
        Prefer favourites ('favlist' in view) then fastscan ('fastscan' in view).
        """
        channel_lists = await self.async_get_channel_lists()
        if not channel_lists:
            _LOGGER.debug("No channel lists found when searching for a TV channel")
            return None

        # Prefer favourites
        favlist = next((c for c in channel_lists if "favlist" in (c["view"] or "").lower()), None)
        if favlist:
            items = await self.async_get_channel_list(favlist["view"])
            if items:
                locator = items[0]["locator"]
                _LOGGER.debug("Using first favourite channel: %s", locator)
                return locator

        # Fall back to fastscan (full DVB list)
        fastscan = next((c for c in channel_lists if "fastscan" in (c["view"] or "").lower()), None)
        if fastscan:
            items = await self.async_get_channel_list(fastscan["view"])
            if items:
                locator = items[0]["locator"]
                _LOGGER.debug("Using first fastscan channel: %s", locator)
                return locator

        _LOGGER.debug("No TV channels available to zap to")
        return None

    async def async_refresh_sources(self) -> None:
        """
        (Re)load AV sources into self.available_sources.
        Heuristic: find AV list by name '#3051' if present; otherwise pick any
        list whose name or view looks like AV inputs.
        """
        lists_ = await self.async_get_channel_lists()
        if not lists_:
            self.available_sources = []
            _LOGGER.debug("No channel lists available; cleared available sources")
            return

        # First try the historic '#3051' ID by name (from pre.zip behaviour)
        avlist = next((c for c in lists_ if (c.get("name") or "") == "#3051"), None)

        # Fallback heuristics: look for 'av' or 'input' in name/view
        if not avlist:
            avlist = next(
                (c for c in lists_ if any(
                    kw in (c.get("name","").lower()) or kw in (c.get("view","").lower())
                    for kw in ("av", "input", "hdmi")
                )),
                None
            )

        if not avlist:
            self.available_sources = []
            _LOGGER.debug("No AV list found in channel lists; cleared available sources")
            return

        items = await self.async_get_channel_list(avlist["view"])
        self.available_sources = items or []
        _LOGGER.info("Loaded %d available AV sources", len(self.available_sources))

    async def async_set_channel(self, locator: str) -> bool:
        """Switch the TV to a given locator via ZapToMedia."""
        extra = f"""
            <ltv:Player>0</ltv:Player>
            <ltv:Locator>{locator}</ltv:Locator>
        """
        resp = await self._safe_request("ZapToMedia", extra_xml=extra)

        ok = bool(resp)  # ZapToMedia gives an empty but syntactically valid response on success
        if ok:
            # Optimistic update
            self.current_locator = locator
            lower = locator.lower()
            if lower.startswith(("dvb://", "tv://")):
                self._last_tv_locator = locator  # remember last TV channel
        else:
            _LOGGER.debug("ZapToMedia failed for locator %s", locator)

        return ok

    async def async_channel_up(self) -> None:
        from .const import LOEWE_RC_CODES
        key = LOEWE_RC_CODES.get("prog_up")
        if key is not None:
            await self.async_inject_rc_key(key)

    async def async_channel_down(self) -> None:
        from .const import LOEWE_RC_CODES
        key = LOEWE_RC_CODES.get("prog_down")
        if key is not None:
            await self.async_inject_rc_key(key)

    # ---------------------- Close out / Clean Up ----------------------

    async def async_close(self) -> None:
        await self.soap.async_close()

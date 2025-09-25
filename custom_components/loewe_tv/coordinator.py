"""Coordinator for Loewe TV integration."""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
import aiohttp

from datetime import timedelta
from typing import Any, Optional
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .utils import async_get_device_uuid

from homeassistant.components.media_player.const import MediaPlayerState

from .const import (
    DOMAIN,
    DEFAULT_RESOURCE_PATH,
    CONF_CLIENT_ID,
    CONF_DEVICE_UUID,
    CONF_FCID,
    CONF_HOST,
    SOAP_ENDPOINTS,
)

_LOGGER = logging.getLogger(__name__)

class LoeweTVCoordinator(DataUpdateCoordinator):
    """Loewe TV data coordinator."""

    # --- properties to expose values to entities ---

    @property
    def current_mode(self) -> str | None:
        """Current playback mode (tv, radio, drplus, etc.)."""
        return getattr(self, "_current_mode", None)
        
    @property
    def available_sources(self) -> list[dict[str, str]]:
        """Return the list of available sources (friendly name + locator)."""
        return getattr(self, "_available_sources", [])

    @property
    def current_locator(self) -> str | None:
        return getattr(self, "_current_locator", None)

        
    def __init__(
        self,
        hass,
        host: str,
        resource_path: str = DEFAULT_RESOURCE_PATH,
    ) -> None:
        self.hass = hass
        self.host = host
        self.resource_path = resource_path
        self.client_id: Optional[str] = None
        self.fcid: Optional[str] = None
        self.device_uuid: str | None = None
        self._last_raw_response: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._available_sources: list[dict[str, str]] = []
        self._last_tv_locator: str | None = None
        self.tv_mac: str | None = None
        self._sources_lock = asyncio.Lock()
        self._avlist_view: str | None = None

        # Restore from config entry if available
        entry = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN)
             if e.data.get(CONF_HOST) == host),
            None,
        )
        if entry:
            self.client_id = entry.data.get(CONF_CLIENT_ID, self.client_id)
            self.fcid = entry.data.get(CONF_FCID, self.fcid)
            self.device_uuid = entry.data.get(CONF_DEVICE_UUID, self.device_uuid)

        _LOGGER.debug(
            "Coordinator initialized: host=%s resource_path=%s client_id=%s fcid=%s",
            self.host,
            self.resource_path,
            self.client_id,
            self.fcid,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=10),
        )

    async def _session_get(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---------- Session handling ----------
    async def _repair_session(self) -> bool:
        """(Re)establish a valid session with the TV via RequestAccess."""
        _LOGGER.info("API connection may have been lost, attempting to repair session")
        
        entry = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN)
             if self.hass.data[DOMAIN].get(e.entry_id) is self),
            None,
        )
        self.fcid = None
        self.client_id = None

        # Always try a RequestAccess to confirm/refresh session
        result = await self.async_request_access("HomeAssistant")
        if not result:
            _LOGGER.error("RequestAccess returned no result")
            return False

        state = result.get("State", "").lower()
        
        if state == "pending":
            _LOGGER.debug("RequestAccess returned pending state, making a second pass")
            #Make a second pass to confirm it is accepted
            
            result = await self.async_request_access("HomeAssistant")
            if not result:
                _LOGGER.error("RequestAccess returned no result")
                return False
            
            state = result.get("State", "").lower()
        
        if state != "accepted":
            _LOGGER.warning("RequestAccess state is not yet accepted: %s", state)
            return False

        # Save new values
        self.client_id = result.get("ClientId")
        self.fcid = result.get("fcid")

        if not self.client_id or not self.fcid:
            _LOGGER.error("RequestAccess missing required client_id and fcid identifiers")
            return False

        # Persist back into config entry if we have one
        if entry:
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_CLIENT_ID: self.client_id,
                    CONF_FCID: self.fcid,
                    CONF_DEVICE_UUID: self.device_uuid,
                },
            )

        _LOGGER.debug(
            "Session repaired: fcid=%s client_id=%s (device_uuid=%s)",
            self.fcid, self.client_id, self.device_uuid,
        )
        return True

    # ---------- Pairing ----------
    async def async_request_access(self, device_name: str) -> Optional[dict]:
        """Perform RequestAccess handshake (assigns fcid + client_id)."""
        _LOGGER.debug("Executing async_request_access")
        
        fcid_seed = self.fcid or "1"
        client_seed = self.client_id or "?"

        # Ensure we have a device_uuid, with your preferred precedence:
        # 1) in-memory (self.device_uuid)
        # 2) stored in HA entry
        # 3) compute via async helper (then persist + cache)
        if not self.device_uuid:
            entry = next(
                (e for e in self.hass.config_entries.async_entries(DOMAIN)
                 if self.hass.data[DOMAIN].get(e.entry_id) is self),
                None,
            )
            stored = entry.data.get(CONF_DEVICE_UUID) if entry else None
            if stored:
                self.device_uuid = stored
            else:
                self.device_uuid = await async_get_device_uuid(self.hass)
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_DEVICE_UUID: self.device_uuid},
                    )

        device_uuid = self.device_uuid  # use this in your RequestAccess envelope


        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
     xmlns:ltv="urn:loewe.de:RemoteTV:Tablet">
      <soapenv:Header/>
      <soapenv:Body>
        <ltv:RequestAccess>
            <ltv:fcid>{fcid_seed}</ltv:fcid>
            <ltv:ClientId>{client_seed}</ltv:ClientId>
            <ltv:DeviceType>{device_name[:40]}</ltv:DeviceType>
            <ltv:DeviceName>{device_name[:40]}</ltv:DeviceName>
            <ltv:DeviceUUID>{device_uuid}</ltv:DeviceUUID>
            <ltv:RequesterName>Home Assistant Loewe TV Integration</ltv:RequesterName>
        </ltv:RequestAccess>
      </soapenv:Body>
    </soapenv:Envelope>"""

        resp = await self._soap_request("RequestAccess", envelope, raw_envelope=True)
        if not resp:
            #_LOGGER.debug("RequestAccess: no response")
            return None

        #_LOGGER.debug("Raw RequestAccess response:\n%s", resp)
        result: dict[str, str] = {}

        if "<fcid>" in resp:
            self.fcid = result["fcid"] = resp.split("<fcid>")[1].split("</fcid>")[0].strip()
        if "<ClientId>" in resp:
            self.client_id = result["ClientId"] = resp.split("<ClientId>")[1].split("</ClientId>")[0].strip()
        if "<AccessStatus>" in resp:
            result["State"] = resp.split("<AccessStatus>")[1].split("</AccessStatus>")[0].strip()
        elif "<State>" in resp:
            result["State"] = resp.split("<State>")[1].split("</State>")[0].strip()

        _LOGGER.debug("RequestAccess parsed result: %s", result)
        return result

    # ---------- API helpers ----------
    def _body_with_ids(self, action: str, ns: str = "ltv", extra_xml: str = "") -> str:
        """Build a SOAP body element with fcid + client_id and optional extra content."""
        return (
            f"<{ns}:{action}>"
            f"<{ns}:fcid>{{fcid}}</{ns}:fcid>"
            f"<{ns}:ClientId>{{client_id}}</{ns}:ClientId>"
            f"{extra_xml}"
            f"</{ns}:{action}>"
        )

    # ---------- API methods ----------
    async def async_get_device_data(self) -> None:
        """Fetch TV device data (MAC, etc.) and store it."""
        resp = await self._safe_soap_request("GetDeviceData", self._body_with_ids("GetDeviceData"))
        if not resp:
            #_LOGGER.warning("LoeweTV: GetDeviceData failed")
            return

        try:
            root = ET.fromstring(resp)
            ns = {"ltv": "urn:loewe.de:RemoteTV:Tablet"}
            mac_elem = (
                root.find(".//ltv:MAC-Address-LAN", ns)
                or root.find(".//ltv:MAC-Address", ns)
            )
            if mac_elem is not None and mac_elem.text:
                self.tv_mac = mac_elem.text.strip()
                _LOGGER.debug("LoeweTV: Retrieved TV MAC %s", self.tv_mac)
        except Exception as e:
            _LOGGER.error("LoeweTV: Error parsing GetDeviceData response: %s", e)

   
    async def async_get_current_status(self) -> dict[str, str]:
        resp = await self._safe_soap_request("GetCurrentStatus", self._body_with_ids("GetCurrentStatus"))
        if not resp:
            #_LOGGER.debug("GetCurrentStatus: no response")
            return {}

        result: dict[str, str] = {}
        if "<Power>" in resp:
            result["power"] = resp.split("<Power>")[1].split("</Power>")[0].strip()
        if "<HdrPlayerState>" in resp:
            result["player_state"] = resp.split("<HdrPlayerState>")[1].split("</HdrPlayerState>")[0].strip()
        elif "<PlayerState>" in resp:
            result["player_state"] = resp.split("<PlayerState>")[1].split("</PlayerState>")[0].strip()
        if "<HdrSpeed>" in resp:
            result["speed"] = resp.split("<HdrSpeed>")[1].split("</HdrSpeed>")[0].strip()
        elif "<Speed>" in resp:
            result["speed"] = resp.split("<Speed>")[1].split("</Speed>")[0].strip()
        if "<SystemLocked>" in resp:
            result["locked"] = resp.split("<SystemLocked>")[1].split("</SystemLocked>")[0].strip()
        elif "<LockState>" in resp:
            result["locked"] = resp.split("<LockState>")[1].split("</LockState>")[0].strip()

        _LOGGER.debug("Parsed GetCurrentStatus: %s", result)
        return result

    async def async_get_channel_lists(self) -> list[dict[str, str]]:
        """Retrieve the available channel/input lists from the TV."""
        body = self._body_with_ids(
            "GetListOfChannelLists",
            extra_xml="""
                <ltv:QueryParameters>
                    <ltv:Range startIndex="0" maxItems="20"/>
                </ltv:QueryParameters>
            """,
        )

        resp = await self._safe_soap_request("GetListOfChannelLists", body)
        if not resp:
            #_LOGGER.debug("GetListOfChannelLists: no response")
            return []

        sources: list[dict[str, str]] = []
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp)
            response_el = root.find(".//GetListOfChannelListsResponse")
            if response_el is not None:
                for clist in response_el.findall(".//ResultItemChannelList"):
                    name_el = clist.find("Name")
                    view_el = clist.find("View")
                    if name_el is not None and view_el is not None:
                        sources.append({
                            "name": name_el.text or "Unknown",
                            "view": view_el.text or "",
                        })
        except Exception as e:
            _LOGGER.warning("Failed to parse GetListOfChannelLists response: %s", e)

        return sources

    async def async_get_channel_list(self, view_id: str) -> list[dict[str, str]]:
        """Retrieve the items of a channel list (e.g. AV list for HDMI inputs)."""
        body = self._body_with_ids(
            "GetChannelList",
            extra_xml=f"""
                <ltv:ChannelListView>{view_id}</ltv:ChannelListView>
                <ltv:QueryParameters>
                    <ltv:Range startIndex="0" maxItems="20" />
                    <ltv:MediaItemInformation>true</ltv:MediaItemInformation>
                    <ltv:MediaItemClass></ltv:MediaItemClass>
                </ltv:QueryParameters>
            """,
        )

        resp = await self._safe_soap_request("GetChannelList", body)
        if not resp:
            #_LOGGER.debug("GetChannelList: no response for %s", view_id)
            return []

        items: list[dict[str, str]] = []
        try:
            root = ET.fromstring(resp)
            response_el = root.find(".//GetChannelListResponse")
            if response_el is not None:
                for ref in response_el.findall(".//ResultItemReference"):

                    locator = ref.attrib.get("locator")
                    short_info = ref.attrib.get("shortInfo")
                    caption = ref.attrib.get("caption")
                    if locator:
                        items.append({
                            "name": short_info or caption or locator,
                            "locator": locator,
                        })

                _LOGGER.debug(
                    "Parsed %d sources from %s: %s",
                    len(items), view_id, items
                )

        except Exception as e:
            _LOGGER.warning("Failed to parse GetChannelList response: %s", e)

        return items

    async def async_set_channel(self, locator: str) -> bool:
        """Switch TV to a given locator using ZapToMedia."""
        body = f"""
            <ltv:ZapToMedia>
                <ltv:fcid>{self.fcid}</ltv:fcid>
                <ltv:ClientId>{self.client_id}</ltv:ClientId>
                <ltv:Player>0</ltv:Player>
                <ltv:Locator>{locator}</ltv:Locator>
            </ltv:ZapToMedia>
        """

        resp = await self._safe_soap_request("ZapToMedia", body)
        ok = self._parse_zap_result(resp, locator, "ZapToMedia")
        if ok:
            # ---- Optimistic update ----
            self._current_locator = locator
            # Heuristic: set mode so HA UI stays stable until next poll
            #lower = locator.lower()
            #if lower.startswith(("dvb://", "tv://")):
            #    self._current_mode = "tv"
            #elif lower.startswith(("av://", "hdmi://", "scart://")):
            #    self._current_mode = "av"
            # Notify entities right away to avoid source flicker
            self.async_update_listeners()
            # Then reconcile with real state after a short delay
            #self.hass.loop.create_task(self._delayed_refresh_after_zap())
        return ok


    async def async_get_volume(self) -> Optional[int]:
        resp = await self._safe_soap_request("GetVolume", self._body_with_ids("GetVolume"))
        if not resp:
            #_LOGGER.debug("GetVolume: no response")
            return None
        for tag in ("<Value>", "<CurrentVolume>", "<Volume>"):
            if tag in resp:
                try:
                    volume = int(resp.split(tag)[1].split(tag.replace("<", "</"))[0].strip())
                    _LOGGER.debug("Parsed GetVolume: %s", volume)
                    return volume
                except ValueError:
                    _LOGGER.warning("GetVolume returned non-integer: %s", resp)
        _LOGGER.debug("GetVolume: no usable tag found")
        return None

    async def async_get_mute(self) -> Optional[bool]:
        resp = await self._safe_soap_request("GetMute", self._body_with_ids("GetMute"))
        if not resp:
            #_LOGGER.debug("GetMute: no response")
            return None

        for tag in ("<Value>", "<MuteState>", "<Mute>"):
            if tag in resp:
                state = resp.split(tag)[1].split(tag.replace("<", "</"))[0].strip().lower()

                if state in ("1", "true", "yes", "on"):
                    mute = True
                elif state in ("0", "false", "no", "off"):
                    mute = False
                else:
                    _LOGGER.warning("GetMute returned unrecognized value: %s", state)
                    return None

                _LOGGER.debug("Parsed GetMute: %s (raw=%s)", mute, state)
                return mute

        _LOGGER.debug("GetMute: no usable tag found")
        return None

    async def async_set_volume(self, value: int) -> bool:
        # Loewe usually expects <Value> not <DesiredVolume>
        extra = f"<ltv:Value>{value}</ltv:Value>"
        resp = await self._safe_soap_request("SetVolume", self._body_with_ids("SetVolume", extra_xml=extra))
        return resp is not None and "<SetVolumeResponse" in resp

    async def async_set_mute(self, mute: bool) -> bool:
        # Loewe usually expects <Value>0/1</Value>
        raw = "1" if mute else "0"
        extra = f"<ltv:Value>{raw}</ltv:Value>"
        resp = await self._safe_soap_request("SetMute", self._body_with_ids("SetMute", extra_xml=extra))
        return resp is not None and "<SetMuteResponse" in resp
        

    async def async_inject_rc_key(self, value: int) -> bool:
        extra = (
            "<ltv:InputEventSequence>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{value}\" mode=\"press\"/>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{value}\" mode=\"release\"/>"
            "</ltv:InputEventSequence>"
        )
        resp = await self._safe_soap_request("InjectRCKey", self._body_with_ids("InjectRCKey", extra_xml=extra))
        return bool(resp)

    async def async_get_current_playback(self) -> dict[str, str]:
        """Poll the TV for current playback mode and source info."""
        body = self._body_with_ids(
            "GetCurrentPlayback",
            extra_xml="<ltv:Player>0</ltv:Player>",
        )
        resp = await self._safe_soap_request("GetCurrentPlayback", body)
        if not resp:
            #_LOGGER.debug("GetCurrentPlayback: no response")
            return {}

        result: dict[str, str] = {}
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp)

            # Look for the response element
            response_el = root.find(".//GetCurrentPlaybackResponse")
            if response_el is not None:
                for child in response_el:
                    # Store each field in dict (Mode, Locator, MediaItemUuid, etc.)
                    tag = child.tag.split("}")[-1]  # strip namespace if present
                    result[tag] = child.text or ""
        except Exception as e:
            _LOGGER.warning("Failed to parse GetCurrentPlayback response: %s", e)

        return result
    
    async def async_channel_up(self) -> bool:
        return await self.async_inject_rc_key(24)  # CH+ keycode

    async def async_channel_down(self) -> bool:
        return await self.async_inject_rc_key(23)  # CH- keycode

    async def async_refresh_sources(self) -> None:
        """Force refresh of available sources (AV + tuner)."""
        try:
            await self.async_ensure_available_sources(force=True)
        except Exception as e:
            _LOGGER.error("Error refreshing sources: %s", e)

    async def async_get_first_tv_channel(self) -> str | None:
        """Return the locator of the first TV channel (favlist > fastscan)."""
        channel_lists = await self.async_get_channel_lists()
        if not channel_lists:
            _LOGGER.warning("No channel lists found when searching for TV channel")
            return None

        # Prefer favourites
        favlist = next((c for c in channel_lists if "favlist" in c["view"]), None)
        if favlist:
            items = await self.async_get_channel_list(favlist["view"])
            if items:
                locator = items[0]["locator"]
                _LOGGER.debug("Using first favourite channel: %s", locator)
                return locator

        # Fallback to fastscan (full DVB channel list)
        fastscan = next((c for c in channel_lists if "fastscan" in c["view"]), None)
        if fastscan:
            items = await self.async_get_channel_list(fastscan["view"])
            if items:
                locator = items[0]["locator"]
                _LOGGER.debug("Using first fastscan channel: %s", locator)
                return locator

        _LOGGER.warning("No TV channels available to zap to")
        return None


    # ---------- Coordinator ----------
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from the Loewe TV."""

        status = {}
        playback = {}
        volume = None
        mute = None

        # ---------- Step 1: get current tv status ----------
        try:
            status = await self.async_get_current_status()
        except Exception as e:
            _LOGGER.debug("GetCurrentStatus request failed: %s", e)

        ha_state = MediaPlayerState.OFF  # default if no response
        if isinstance(status, dict) and status:
            power = status.get("power", "").lower()
            if power in ("tv", "on"):
                ha_state = MediaPlayerState.ON
            elif power in ("standby", "off"):
                ha_state = MediaPlayerState.OFF
        else:
            _LOGGER.debug(
                "No valid status response from Loewe TV at %s, assuming OFF", self.host
            )

        # ---------- Bail out early if TV is off ----------
        if ha_state == MediaPlayerState.OFF:
            return {
                "status": status,
                "device": {"volume": None, "mute": None, "ha_state": ha_state},
                "playback": {},
                "available_sources": getattr(self, "_available_sources", []),
            }

        # ---------- Step 2: ensure sources ----------
        await self.async_ensure_available_sources(force=False)

        # ---------- Step 3: get tv playback info ----------
        playback = await self.async_get_current_playback()
        if playback:
            self._current_mode = playback.get("Mode")
            self._current_locator = playback.get("Locator")

            if self._current_locator:
                if not self._available_sources:
                    _LOGGER.warning(
                        "Available sources unexpectedly empty while processing playback locator"
                    )
                known_locators = {src["locator"] for src in self._available_sources}
                if (
                    self._current_locator not in known_locators
                    and self._current_locator != getattr(self, "_last_tv_locator", None)
                ):
                    self._last_tv_locator = self._current_locator
                    _LOGGER.debug("Storing new TV tuner locator: %s", self._last_tv_locator)

        # ---------- Step 4: get volume ----------
        volume = await self.async_get_volume()

        # ---------- Step 5: get mute status ----------
        mute = await self.async_get_mute()

        # ---------- Sanity logging ----------
        if (
            not status
            or not playback
            or volume is None
            or mute is None
        ):
            _LOGGER.debug(
                "Connected to Loewe TV at %s but one or more returned status was invalid ...",
                self.host,
            )
            if not status:
                _LOGGER.debug("GetCurrentStatus=%s", status)
            if not playback:
                _LOGGER.debug("GetCurrentPlayback=%s", playback)
            if volume is None:
                _LOGGER.debug("GetVolume=%s", volume)
            if mute is None:
                _LOGGER.debug("GetMute=%s", mute)
        else:
            _LOGGER.info("Successfully updated data from Loewe TV at %s", self.host)

        # ---------- Build result ----------
        result = {
            "status": status,
            "device": {"volume": volume, "mute": mute, "ha_state": ha_state},
            "playback": playback,
        }

        _LOGGER.debug("Update Data result: %s", result)
        return result


    # ---------- SOAP core ----------
    async def _soap_request(
        self,
        action: str,
        inner_xml: str,
        timeout: float = 8.0,
        raw_envelope: bool = False,
    ) -> str | None:
        cfg = SOAP_ENDPOINTS[action]
        url = cfg["url"].format(host=self.host)
        soap_action = cfg["soap_action"]
        service = cfg["service"]
        mode = cfg["mode"]
        prefix = cfg.get("prefix", "ltv")

        headers = {
            "Accept": "*/*",
            "Content-Type": "application/soap+xml; charset=utf-8"
            if mode != "soap_xml_legacy" else "text/xml; charset=utf-8",
            "SOAPAction": soap_action,
        }

        if raw_envelope:
            envelope = inner_xml
        elif mode == "soap_xml_legacy":
            envelope = f"""<?xml version="1.0" encoding="utf-8"?>
    <SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
      <SOAP-ENV:Header/>
      <SOAP-ENV:Body>
        {inner_xml}
      </SOAP-ENV:Body>
    </SOAP-ENV:Envelope>"""
        else:
            if not self.fcid or not self.client_id:
                _LOGGER.error("SOAP %s aborted: missing fcid or client_id", action)
                return None
            inner_with_ids = (
                inner_xml.replace("{{fcid}}", str(self.fcid)).replace("{fcid}", str(self.fcid))
                         .replace("{{client_id}}", self.client_id).replace("{client_id}", self.client_id)
            )
            #_LOGGER.debug("Resolved %s body:\n%s", action, inner_with_ids)
            envelope = f"""<?xml version="1.0" encoding="utf-8"?>
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
     xmlns:{prefix}="{service}">
      <soapenv:Header/>
      <soapenv:Body>
        {inner_with_ids}
      </soapenv:Body>
    </soapenv:Envelope>"""

        session = await self._session_get()
        try:
            _LOGGER.debug("SOAP action=%s url=%s", action, url)
            _LOGGER.debug("SOAP headers:\n%s", headers)
            _LOGGER.debug("SOAP request body:\n%s", envelope)
            async with session.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                self._last_raw_response = text
                await asyncio.sleep(0.1) #TV doesn't like rapid fire requests, so adding in a delay here on all requests.
                if resp.status == 200:
                    normalized = (
                        text.replace("<m:", "<").replace("</m:", "</")
                            .replace("<ltv:", "<").replace("</ltv:", "</")
                    )
                    _LOGGER.debug("SOAP %s response:\n%s", action, text)
                    #_LOGGER.debug("Normalized %s response:\n%s", action, normalized)
                    return normalized
                _LOGGER.error("SOAP %s failed (%s):\n%s", action, resp.status, text)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("SOAP %s network error: %s", action, err)

        _LOGGER.warning("SOAP %s failed on %s", action, url)
        return None

    async def _safe_soap_request(
        self, action: str, inner_xml: str, retry: bool = True
    ) -> str:
        """Wrapper around _soap_request that auto-heals the Loewe TV session."""

        # 1. Ensure identifiers exist
        if not self.client_id or not self.fcid:
            #_LOGGER.debug("Missing fcid/client_id before %s → repairing session", action)
            repaired = await self._repair_session()
            if not repaired:
                _LOGGER.error("Unable to repair session before %s", action)
                return ""

        # 2. Perform SOAP request
        resp = await self._soap_request(action, inner_xml)

        if resp:
            try:
                root = ET.fromstring(resp)

                # Look for the response element
                response_el = root.find(f".//{action}Response")
                if response_el is not None:
                    # If it has children or text → valid
                    if list(response_el) or (response_el.text and response_el.text.strip()):
                        return resp
                    else:
                        _LOGGER.debug(
                            "SOAP response for %s had empty <%sResponse/> → treating as invalid",
                            action,
                            action,
                        )
            except ET.ParseError:
                _LOGGER.warning("Failed to parse SOAP response: %s", resp)

        # 3. Empty or invalid response → repair session
        _LOGGER.debug("Empty/invalid SOAP response for %s, retry=%s", action, retry)
        if retry:
            #_LOGGER.info("Attempting to repair Loewe TV session after empty response")
            repaired = await self._repair_session()
            if repaired:
                return await self._safe_soap_request(action, inner_xml, retry=False)

        # 4. Still no usable result
        _LOGGER.error("SOAP %s ultimately failed, no usable response", action)
        return ""
        
    def _parse_zap_result(self, resp: str | None, target: str | int, action: str) -> bool:
        """Check SOAP zap result: success if <Result>0</Result>."""
        if not resp:
            _LOGGER.warning("%s failed: no response for %s", action, target)
            return False

        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(resp)
            result_elem = root.find(".//Result")
            if result_elem is not None and result_elem.text.strip() == "0":
                _LOGGER.debug("%s succeeded for %s", action, target)
                return True
            else:
                _LOGGER.warning(
                    "%s did not indicate success for %s (Result=%s)",
                    action,
                    target,
                    result_elem.text if result_elem is not None else "MISSING",
                )
        except Exception as e:
            _LOGGER.error("Error parsing %s response for %s: %s", action, target, e)

        return False

    async def _find_avlist_view(self) -> str | None:
        """Locate the AV list view id (e.g. '#3051') and cache it."""
        channel_lists = await self.async_get_channel_lists()
        if not channel_lists:
            self._avlist_view = None
            _LOGGER.debug("No channel lists available while searching for AV list")
            return None

        # Your existing heuristic: match name '#3051'
        avlist = next((c for c in channel_lists if c.get("name") == "#3051"), None)
        self._avlist_view = avlist.get("view") if avlist else None

        if self._avlist_view:
            _LOGGER.debug("Cached AV list view id: %s", self._avlist_view)
        else:
            _LOGGER.debug("AV list '#3051' not found in channel lists")

        return self._avlist_view


    async def async_ensure_available_sources(self, force: bool = False) -> list[dict[str, str]]:
        """
        Ensure _available_sources is populated.
        - If force is False and we already have sources, do nothing.
        - Otherwise (or if empty), (re)fetch and cache them.
        """
        async with self._sources_lock:
            if not force and self._available_sources:
                return self._available_sources

            view = self._avlist_view or await self._find_avlist_view()
            if not view:
                self._available_sources = []
                _LOGGER.debug("No AV list view available; sources cleared")
                return self._available_sources

            items = await self.async_get_channel_list(view)
            self._available_sources = items or []
            _LOGGER.info("Loaded %d available sources from AV list", len(self._available_sources))
            return self._available_sources

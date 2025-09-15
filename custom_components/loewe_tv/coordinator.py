"""Coordinator for Loewe TV integration."""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
import aiohttp

from datetime import timedelta
from typing import Optional
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .utils import async_get_device_uuid

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
        self.device_uuid: Optional[str] = None
        self._last_raw_response: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None

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
        entry = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN)
             if self.hass.data[DOMAIN].get(e.entry_id) is self),
            None,
        )
        self.fcid = None
        self.client_id = None
        self.device_uuid = "001122334455" #await async_get_device_uuid(hass)

        # Always try a RequestAccess to confirm/refresh session
        await asyncio.sleep(0.1)
        result = await self.async_request_access("HomeAssistant")
        if not result:
            _LOGGER.error("RequestAccess returned no result")
            return False

        state = result.get("State", "").lower()
        
        if state == "pending":
            _LOGGER.warning("RequestAccess is in progress %s", state)
            #Make a second pass to confirm it is accepted
            await asyncio.sleep(0.1)
            result = await self.async_request_access("HomeAssistant")
            if not result:
                _LOGGER.error("RequestAccess returned no result")
                return False
        
        if state != "accepted":
            _LOGGER.warning("RequestAccess not accepted yet: %s", state)
            return False

        # Save new values
        self.client_id = result.get("ClientId")
        self.fcid = result.get("fcid")

        if not self.client_id or not self.fcid:
            _LOGGER.error("RequestAccess missing required identifiers")
            return False

        # Persist back into config entry if we have one
        if entry:
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_CLIENT_ID: self.client_id,
                    CONF_FCID: self.fcid,
                    CONF_DEVICE_UUID: device_uuid,
                },
            )

        _LOGGER.info(
            "Session repaired: fcid=%s client_id=%s (device_uuid=%s)",
            self.fcid, self.client_id, self.device_uuid,
        )
        return True

    # ---------- Pairing ----------
    async def async_request_access(self, device_name: str) -> Optional[dict]:
        """Perform RequestAccess handshake (assigns fcid + client_id)."""
        fcid_seed = self.fcid or "1"
        client_seed = self.client_id or "?"

        entry = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN)
             if self.hass.data[DOMAIN].get(e.entry_id) is self),
            None,
        )
        device_uuid = entry.data.get(CONF_DEVICE_UUID) if entry else "001122334455"

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
            _LOGGER.debug("RequestAccess: no response")
            return None

        _LOGGER.debug("Raw RequestAccess response:\n%s", resp)
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
    async def async_get_current_status(self) -> dict[str, str]:
        resp = await self._safe_soap_request("GetCurrentStatus", self._body_with_ids("GetCurrentStatus"))
        if not resp:
            _LOGGER.debug("GetCurrentStatus: no response")
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

    async def async_get_volume(self) -> Optional[int]:
        resp = await self._safe_soap_request("GetVolume", self._body_with_ids("GetVolume"))
        if not resp:
            _LOGGER.debug("GetVolume: no response")
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
            _LOGGER.debug("GetMute: no response")
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
        resp = await self._soap_request("SetVolume", self._body_with_ids("SetVolume", extra_xml=extra))
        return resp is not None and "<SetVolumeResponse" in resp

    async def async_set_mute(self, mute: bool) -> bool:
        # Loewe usually expects <Value>0/1</Value>
        raw = "1" if mute else "0"
        extra = f"<ltv:Value>{raw}</ltv:Value>"
        resp = await self._soap_request("SetMute", self._body_with_ids("SetMute", extra_xml=extra))
        return resp is not None and "<SetMuteResponse" in resp

    async def async_inject_rc_key(self, value: int) -> bool:
        extra = (
            "<ltv:InputEventSequence>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{value}\" mode=\"press\"/>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{value}\" mode=\"release\"/>"
            "</ltv:InputEventSequence>"
        )
        return bool(await self._soap_request("InjectRCKey", self._body_with_ids("InjectRCKey", extra_xml=extra)))

    # ---------- Coordinator ----------
    async def _async_update_data(self) -> dict:
        status = await self.async_get_current_status()
        await asyncio.sleep(0.1)
        volume = await self.async_get_volume()
        await asyncio.sleep(0.1)
        mute = await self.async_get_mute()

        ha_state = None
        if isinstance(status, dict) and status:
            power = status.get("power", "").lower()
            if power in ("tv", "on"):
                ha_state = "on"
            elif power in ("standby", "off"):
                ha_state = "off"

        result = {
            "status": status or {},
            "device": {"volume": volume, "mute": mute, "ha_state": ha_state},
        }

        if status or volume is not None or mute is not None:
            _LOGGER.info(
                "Successfully connected to Loewe TV at %s (fcid=%s, client_id=%s)",
                self.host, self.fcid, self.client_id,
            )
        else:
            _LOGGER.warning(
                "Connected to Loewe TV at %s but no usable data returned (status=%s, volume=%s, mute=%s)",
                self.host, status, volume, mute,
            )

        _LOGGER.debug("Update result: %s", result)
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
            _LOGGER.debug("Resolved %s body:\n%s", action, inner_with_ids)
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
            _LOGGER.debug("SOAP request body:\n%s", envelope)
            async with session.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                self._last_raw_response = text
                if resp.status == 200:
                    normalized = (
                        text.replace("<m:", "<").replace("</m:", "</")
                            .replace("<ltv:", "<").replace("</ltv:", "</")
                    )
                    _LOGGER.debug("Raw %s response:\n%s", action, text)
                    _LOGGER.debug("Normalized %s response:\n%s", action, normalized)
                    return normalized
                _LOGGER.error("SOAP %s failed (%s):\n%s", action, resp.status, text)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("SOAP %s network error: %s", action, err)

        _LOGGER.warning("SOAP %s failed on %s", action, url)
        return None

    async def _safe_soap_request(
        self, action: str, inner_xml: str, retry: bool = True
    ) -> str:
        """Wrapper around _soap_request that auto-heals the Loewe TV session."""

        # 1. Ensure identifiers exist
        if not self.client_id or not self.fcid:
            _LOGGER.debug("Missing fcid/client_id before %s → repairing session", action)
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
            _LOGGER.info("Attempting to repair Loewe TV session after empty response")
            repaired = await self._repair_session()
            if repaired:
                return await self._safe_soap_request(action, inner_xml, retry=False)

        # 4. Still no usable result
        _LOGGER.error("SOAP %s ultimately failed, no usable response", action)
        return ""
        

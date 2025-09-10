from __future__ import annotations
import logging
from datetime import timedelta
import asyncio
from typing import Optional, Dict, Any

import aiohttp
import xml.etree.ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DEFAULT_RESOURCE_PATH,
    DEFAULT_SCAN_INTERVAL,
    TRANSPORT_SOAP,
)

_LOGGER = logging.getLogger(__name__)

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
LTV_NS = "urn:loewe.de:RemoteTV:Tablet"


def _ns(tag: str, ns: str) -> str:
    return f"{{{ns}}}{tag}"


class LoeweTVCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator for Loewe TV SOAP control."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        resource_path: str = DEFAULT_RESOURCE_PATH,
        client_id: Optional[str] = None,
        device_uuid: Optional[str] = None,
        control_transport: str = TRANSPORT_SOAP,
        update_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Loewe TV",
            update_interval=timedelta(seconds=update_interval),
        )
        self.host = host
        self.resource_path = (resource_path or DEFAULT_RESOURCE_PATH).rstrip("/")
        self.base_url = f"http://{self.host}:905{self.resource_path}"
        self.client_id: Optional[str] = client_id
        self.device_uuid = device_uuid
        self.control_transport = control_transport
        self._session: Optional[aiohttp.ClientSession] = None
        self.device_name: Optional[str] = None
        self._fcid = 1
        self._device_info: Dict[str, Any] = {}

    # ---- HTTP/SOAP helpers --------------------------------------------------

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=12)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _next_fcid(self) -> int:
        self._fcid += 1
        return self._fcid

    def _envelope(self, inner: str) -> str:
        return f'<s:Envelope xmlns:s="{SOAP_NS}"><s:Body>{inner}</s:Body></s:Envelope>'

    async def _soap(self, action: str, inner_xml: str, timeout: float = 10.0) -> Optional[str]:
        session = await self._session_get()
        data = self._envelope(inner_xml).encode("utf-8")

        # Loewe TVs (your firmware) want bare SOAPAction for *all* calls
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "deflate, gzip",
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": action,
        }

        try:
            async with session.post(
                self.base_url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    _LOGGER.debug("SOAP non-200 (%s) for %s: %s", resp.status, action, text[:400])
                    return None
                return text
        except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
            _LOGGER.debug("SOAP client error for %s: %s", action, ex)
            return None

    def _parse_map(self, xml_text: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        try:
            root = ET.fromstring(xml_text)
            body = root.find(_ns("Body", SOAP_NS))
            if body is None:
                return out
            for resp in body:
                for child in resp:
                    tag = child.tag.split("}")[-1]
                    out[tag] = (child.text or "").strip()
        except ET.ParseError:
            _LOGGER.debug("Failed to parse SOAP XML")
        return out

    # ---- API calls ----------------------------------------------------------

    async def async_request_access(self) -> Optional[Dict[str, str]]:
        """Perform RequestAccess handshake."""
        fcid = 8138941
        inner = (
            f'<ltv:RequestAccess xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>?</ltv:ClientId>"
            f"<ltv:DeviceType>Home Assistant</ltv:DeviceType>"
            f"<ltv:DeviceName>Loewe TV</ltv:DeviceName>"
            f"<ltv:DeviceUUID>ha-{self.host}</ltv:DeviceUUID>"
            f"<ltv:RequesterName>HA Loewe Integration</ltv:RequesterName>"
            f"</ltv:RequestAccess>"
        )
        xml = await self._soap("RequestAccess", inner)
        if not xml:
            return None
        parsed = self._parse_map(xml)
        client = parsed.get("ClientId")
        if client:
            self.client_id = client
            _LOGGER.debug("Obtained ClientId: %s", client)
        return parsed

    async def async_get_device_data(self) -> Optional[Dict[str, str]]:
        if not self.client_id:
            return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetDeviceData xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetDeviceData>"
        )
        xml = await self._soap("GetDeviceData", inner)
        if not xml:
            return None
        parsed = self._parse_map(xml)
        if parsed:
            self._device_info = parsed
            self.device_name = (
                parsed.get("NetworkHostName")
                or parsed.get("StreamingServerName")
                or "Loewe TV"
            )
        return parsed

    async def async_get_current_status(self) -> Optional[Dict[str, str]]:
        if not self.client_id:
            return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetCurrentStatus xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetCurrentStatus>"
        )
        xml = await self._soap("GetCurrentStatus", inner)
        if not xml:
            return None
        return self._parse_map(xml)

    async def async_get_volume(self) -> Optional[int]:
        if not self.client_id:
            return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetVolume xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetVolume>"
        )
        xml = await self._soap("GetVolume", inner)
        if not xml:
            return None
        parsed = self._parse_map(xml)
        try:
            return int(parsed.get("Value", ""))
        except Exception:
            return None

    async def async_set_volume(self, value: int) -> bool:
        if not self.client_id:
            return False
        fcid = self._next_fcid()
        inner = (
            f'<ltv:SetVolume xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"<ltv:Value>{value}</ltv:Value>"
            f"</ltv:SetVolume>"
        )
        xml = await self._soap("SetVolume", inner)
        if not xml:
            return False
        parsed = self._parse_map(xml)
        return "Value" in parsed

    async def async_get_mute(self) -> Optional[bool]:
        if not self.client_id:
            return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetMute xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetMute>"
        )
        xml = await self._soap("GetMute", inner)
        if not xml:
            return None
        parsed = self._parse_map(xml)
        val = (parsed.get("Value") or "").strip().lower()
        return val in ("1", "true", "on")

    async def async_inject_rc_key(self, code: int) -> bool:
        if not self.client_id:
            return False
        fcid = self._next_fcid()
        inner = (
            f'<ltv:InjectRCKey xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"<ltv:InputEventSequence>"
            f'<ltv:RCKeyEvent alphabet="l2700" mode="press" value="{code}"/>'
            f'<ltv:RCKeyEvent alphabet="l2700" mode="release" value="{code}"/>'
            f"</ltv:InputEventSequence>"
            f"</ltv:InjectRCKey>"
        )
        xml = await self._soap("InjectRCKey", inner)
        return bool(xml)

    # ---- Config flow hook ---------------------------------------------------

    async def async_test_connection(self) -> tuple[bool, dict]:
        """Validate connectivity & obtain ClientId if possible."""
        # Try RequestAccess if we don't have one
        if not self.client_id:
            await self.async_request_access()
        if self.client_id:
            dev = await self.async_get_device_data()
            if dev:
                return True, dev
            status = await self.async_get_current_status()
            if status:
                return True, status
        return False, {}

    # ---- Coordinator lifecycle ---------------------------------------------

    async def _async_update_data(self) -> dict:
        if not self.client_id:
            await self.async_request_access()

        status = await self.async_get_current_status()
        volume = await self.async_get_volume() if status else None
        mute = await self.async_get_mute() if status else None

        if status is None:
            status = {}
        if volume is not None:
            status["VolumeRaw"] = volume
        if mute is not None:
            status["MuteRaw"] = int(mute)

        return {"device": self._device_info, "status": status}

    async def async_close(self):
        if self._session and not self._session.closed:
            await self._session.close()

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
    TRANSPORT_AUTO,
    TRANSPORT_SOAP,
    TRANSPORT_UPNP,
)

_LOGGER = logging.getLogger(__name__)

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
LTV_NS = "urn:loewe.de:RemoteTV:Tablet"

def _ns(tag: str, ns: str) -> str:
    return f"{{{ns}}}{tag}"

class LoeweTVCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator for Loewe TV SOAP/UPnP control."""

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
        self.resource_path = resource_path or DEFAULT_RESOURCE_PATH
        self.base_url = f"http://{self.host}:905{self.resource_path}"
        self.sunny_base = f"http://{self.host}:1543/sunny"
        self.client_id: Optional[str] = client_id
        self.device_uuid = device_uuid
        self.control_transport = control_transport
        self._session: Optional[aiohttp.ClientSession] = None
        self.device_name: Optional[str] = None
        self._fcid = 1
        self._device_info: Dict[str, Any] = {}

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _next_fcid(self) -> int:
        self._fcid += 1
        return self._fcid

    def _envelope(self, inner: str) -> str:
        return f'<s:Envelope xmlns:s="{SOAP_NS}"><s:Body>{inner}</s:Body></s:Envelope>'

    async def _soap(self, action: str, inner_xml: str, timeout: float = 8.0) -> Optional[str]:
        session = await self._session_get()
        data = self._envelope(inner_xml).encode("utf-8")
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "deflate, gzip",
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": action,
        }
        _LOGGER.debug(
            "SOAP request to %s (Action=%s):\nHeaders: %s\nBody:\n%s",
            self.base_url, action, headers, data.decode("utf-8"),
        )
        try:
            async with session.post(self.base_url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                text = await resp.text()
                _LOGGER.debug("SOAP response %s: %s", resp.status, text[:800])
                if resp.status != 200:
                    return None
                return text
        except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
            _LOGGER.debug("SOAP client error: %s", ex)
            return None

    async def _upnp_control(self, service: str, action: str, inner_xml: str, timeout: float = 8.0) -> Optional[str]:
        url = f"{self.sunny_base}/{service}/control"
        session = await self._session_get()
        soap_body = f'<s:Envelope xmlns:s="{SOAP_NS}"><s:Body><u:{action} xmlns:u="urn:loewe.de:service:{service}:1">{inner_xml}</u:{action}></s:Body></s:Envelope>'
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPACTION': f'urn:loewe.de:service:{service}:1#{action}'
        }
        _LOGGER.debug("UPnP request to %s (Action=%s):\nHeaders: %s\nBody:\n%s", url, action, headers, soap_body)
        try:
            async with session.post(url, data=soap_body.encode('utf-8'), headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                text = await resp.text()
                _LOGGER.debug("UPnP response %s: %s", resp.status, text[:800])
                if resp.status != 200:
                    return None
                return text
        except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
            _LOGGER.debug("UPnP client error: %s", ex)
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

    async def async_request_access(self) -> Optional[Dict[str, str]]:
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
        _LOGGER.debug("RequestAccess: %s", parsed)
        return parsed

    async def async_get_device_data(self) -> Optional[Dict[str, str]]:
        fcid = 8138942
        inner = f'<ltv:GetDeviceData xmlns:ltv="{LTV_NS}"><ltv:fcid>{fcid}</ltv:fcid><ltv:ClientId>{self.client_id or ""}</ltv:ClientId></ltv:GetDeviceData>'
        xml = await self._soap("GetDeviceData", inner)
        if not xml:
            return None
        parsed = self._parse_map(xml)
        if parsed:
            self._device_info = parsed
            self.device_name = parsed.get("NetworkHostName") or parsed.get("StreamingServerName") or "Loewe TV"
        return parsed

    async def async_get_current_status(self) -> Optional[Dict[str, str]]:
        fcid = self._next_fcid()
        inner = f'<ltv:GetCurrentStatus xmlns:ltv="{LTV_NS}"><ltv:fcid>{fcid}</ltv:fcid><ltv:ClientId>{self.client_id or ""}</ltv:ClientId></ltv:GetCurrentStatus>'
        xml = await self._soap("GetCurrentStatus", inner)
        if not xml:
            return None
        return self._parse_map(xml)

    async def async_inject_rc_key(self, code: int) -> bool:
        fcid = self._next_fcid()
        inner = (
            f'<ltv:InjectRCKey xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id or ''}</ltv:ClientId>"
            f"<ltv:InputEventSequence><ltv:RCKeyEvent alphabet=\"l2700\" value=\"{code}\" mode=\"press\"/>"
            f"<ltv:RCKeyEvent alphabet=\"l2700\" value=\"{code}\" mode=\"release\"/></ltv:InputEventSequence>"
            f"</ltv:InjectRCKey>"
        )
        xml = await self._soap("InjectRCKey", inner)
        if xml:
            return True

        if self.control_transport in (TRANSPORT_AUTO, TRANSPORT_UPNP):
            body = f'<InputEventSequence><RCKeyEvent alphabet="l2700" value="{code}" mode="press"/><RCKeyEvent alphabet="l2700" value="{code}" mode="release"/></InputEventSequence>'
            upnp = await self._upnp_control("X_RemoteControl", "InjectRCKey", body)
            return upnp is not None

        return False

    async def async_test_connection(self) -> tuple[bool, dict]:
        dev = await self.async_get_device_data()
        if not dev:
            return (False, {})
        return (True, dev)

    async def _async_update_data(self) -> dict:
        if not self.client_id:
            await self.async_request_access()
        status = await self.async_get_current_status()
        return {
            "device": self._device_info,
            "status": status or {},
        }

    async def async_close(self):
        if self._session and not self._session.closed:
            await self._session.close()

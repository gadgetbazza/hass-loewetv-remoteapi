"""SOAP client for Loewe TV (stateless transport layer)."""

from __future__ import annotations
from typing import Any, Optional
from . import parsers
from .const import SOAP_BASE_URL, SOAP_SERVICE, SOAP_PREFIX
from .network import async_get_device_mac

import asyncio
import logging
import aiohttp

_LOGGER = logging.getLogger(__name__)


class LoeweSoapClient:
    """Pure transport client for Loewe SOAP API — stateless (no stored IDs)."""

    def __init__(self, hass: HomeAssistant, host: str, resource_path: str) -> None:
        self.hass = hass
        self.host = host
        self.resource_path = resource_path or "/loewe_tablet_0001"
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_raw_response: Optional[str] = None

    # ------------------------- session -------------------------

    async def _session_get(self) -> aiohttp.ClientSession:
        """Return an aiohttp session, creating it if needed."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_close(self) -> None:
        """Close the HTTP session cleanly."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------- request builders ----------------

    def build_body(
        self,
        action: str,
        *,
        extra_xml: str = "",
        fcid: Optional[str] = None,
        client_id: Optional[str] = None,
        include_ids: bool = True,
    ) -> str:
        """Construct the SOAP body for a given action."""
        id_block = ""
        if include_ids and fcid and client_id:
            id_block = (
                f"<{SOAP_PREFIX}:fcid>{fcid}</{SOAP_PREFIX}:fcid>"
                f"<{SOAP_PREFIX}:ClientId>{client_id}</{SOAP_PREFIX}:ClientId>"
            )

        body = f"<{SOAP_PREFIX}:{action}>{id_block}{extra_xml}</{SOAP_PREFIX}:{action}>"
        _LOGGER.debug("SOAP build_body(%s):\n%s", action, body)
        return body

    def _build_envelope(self, inner_xml: str) -> str:
        """Wrap the body into a standard SOAP envelope."""
        return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope
 xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:wse="http://www.w3.org/2009/02/ws-evt"
 xmlns:{SOAP_PREFIX}="{SOAP_SERVICE}">
  <soapenv:Header/>
  <soapenv:Body>
    {inner_xml}
  </soapenv:Body>
</soapenv:Envelope>"""

    # ------------------------- low-level requests --------------

    async def request(
        self,
        soap_action: str,
        inner_xml: str,
        *,
        timeout: float = 8.0,
        raw_envelope: bool = False,
    ) -> Optional[str]:
        """Perform a raw SOAP HTTP request and return the raw response XML."""
        url = SOAP_BASE_URL.format(host=self.host)
        envelope = inner_xml if raw_envelope else self._build_envelope(inner_xml)

        headers = {
            "Accept": "*/*",
            # Loewe TVs expect this format for all actions (read and write)
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": soap_action,
        }

        session = await self._session_get()
        try:
            _LOGGER.debug("SOAP %s → %s → envelope:\n%s", soap_action, url, envelope)
            async with session.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                self._last_raw_response = text
                await asyncio.sleep(0.1)  # small pacing delay for stability

                if resp.status == 200:
                    _LOGGER.debug("SOAP %s response:\n%s", soap_action, text)
                    return (
                        text.replace("<m:", "<").replace("</m:", "</")
                            .replace(f"<{SOAP_PREFIX}:", "<").replace(f"</{SOAP_PREFIX}:", "</")
                    )
                _LOGGER.error("SOAP %s failed (%s): %s", soap_action, resp.status, text)

        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("SOAP %s network error: %s", soap_action, err)
        except Exception as err:
            _LOGGER.exception("SOAP %s unexpected error: %s", soap_action, err)

        return None

    # ------------------------- pairing -------------------------

    async def request_access(self, device_name: str) -> Optional[dict[str, str]]:
        """Perform RequestAccess handshake to obtain fcid + client_id."""
        _LOGGER.debug("Executing RequestAccess for %s", device_name)

        fcid_seed = "1"
        client_seed = "?"

        # Try to use the TV’s actual MAC for DeviceUUID
        try:
            device_uuid = await async_get_device_mac(self.hass)
        except Exception as e:
            _LOGGER.warning("Unable to get MAC for DeviceUUID: %s", e)
            device_uuid = "001122334455"

        # Legacy Loewe envelope (uses text/xml instead of application/soap+xml)
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <SOAP-ENV:Header/>
  <SOAP-ENV:Body>
    <RequestAccess xmlns="{SOAP_SERVICE}">
      <fcid>{fcid_seed}</fcid>
      <ClientId>{client_seed}</ClientId>
      <DeviceType>{device_name[:40]}</DeviceType>
      <DeviceName>{device_name[:40]}</DeviceName>
      <DeviceUUID>{device_uuid}</DeviceUUID>
      <RequesterName>Home Assistant Loewe TV Integration</RequesterName>
    </RequestAccess>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

        url = SOAP_BASE_URL.format(host=self.host)
        headers = {
            "Accept": "*/*",
            "Content-Type": "text/xml; charset=utf-8",  # Loewe-specific requirement
            "SOAPAction": "RequestAccess",
        }

        session = await self._session_get()
        try:
            _LOGGER.debug("SOAP RequestAccess envelope:\n%s", envelope)
            async with session.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=8.0) as resp:
                text = await resp.text()
                self._last_raw_response = text
                await asyncio.sleep(0.1)
                _LOGGER.debug("SOAP RequestAccess response:\n%s", text)

                if resp.status != 200:
                    _LOGGER.error("RequestAccess failed (%s): %s", resp.status, text)
                    return None

                result = parsers.parse_request_access(text)
                _LOGGER.debug("RequestAccess parsed result: %s", result)
                return result

        except Exception as e:
            _LOGGER.error("RequestAccess network error: %s", e)

        return None

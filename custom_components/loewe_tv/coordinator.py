"""Coordinator for Loewe TV Remote API integration."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp
import async_timeout
import xml.etree.ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

# ────────────────────────────────────────────────────────────────────────────────
# Constants (prefer values from const.py if available)
# ────────────────────────────────────────────────────────────────────────────────
try:
    from .const import (
        DOMAIN,
        DEFAULT_SCAN_INTERVAL,
        MANUFACTURER,
        MODEL_FALLBACK,
        SOAP_NS,
        LTV_NS,
    )
except Exception:  # pragma: no cover
    DOMAIN = "loewe_tv"
    from datetime import timedelta
    DEFAULT_SCAN_INTERVAL = timedelta(seconds=10)
    MANUFACTURER = "Loewe"
    MODEL_FALLBACK = "TV"
    SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
    LTV_NS = "urn:loewe.de:RemoteTV:Tablet"

_LOGGER = logging.getLogger(__name__)


def _ns(tag: str, ns: str) -> str:
    return f"{{{ns}}}{tag}"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


@dataclass(slots=True)
class DeviceInfoLite:
    manufacturer: str = MANUFACTURER
    model: str = MODEL_FALLBACK
    sw_version: Optional[str] = None
    name: Optional[str] = None
    unique_id: Optional[str] = None


class LoeweCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinates all network I/O with the Loewe TV and exposes parsed state."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        # Preferred (new) style:
        base_url: str | None = None,
        client_name: str = "HomeAssistant",
        session: Optional[aiohttp.ClientSession] = None,
        update_interval=DEFAULT_SCAN_INTERVAL,
        device_name: Optional[str] = None,
        unique_id: Optional[str] = None,
        # Back-compat with older config_flow:
        host: str | None = None,
        resource_path: str = "/loewe_tablet_0001",
        url: str | None = None,
        port: int | None = None,  # allow explicit port; default 905
        **_ignored: Any,
    ) -> None:
        """
        Accept both the new 'base_url' and old ('host', 'resource_path' | 'url') styles.
        Examples accepted:
          - base_url="http://192.168.4.121:905/loewe_tablet_0001"
          - host="192.168.4.121", resource_path="/loewe_tablet_0001" (→ uses port 905)
          - url="http://192.168.4.121:905/loewe_tablet_0001"
          - base_url/url supplied as just "192.168.4.121" → normalized to http://IP:905/loewe_tablet_0001
        """

        def _ensure_endpoint(ep: str | None) -> str | None:
            """Normalize any base_url/url to include scheme, port 905, and path."""
            if not ep:
                return None
            ep = ep.strip()
            if not ep:
                return None
            if not (ep.startswith("http://") or ep.startswith("https://")):
                ep = f"http://{ep}"
            scheme, rest = ep.split("://", 1)
            # If no '/' present, add default path (and port if missing)
            if "/" not in rest:
                rest = f"{rest}:905/loewe_tablet_0001" if ":" not in rest else f"{rest}/loewe_tablet_0001"
            host_part, *path_parts = rest.split("/", 1)
            path = "/" + path_parts[0] if path_parts else "/loewe_tablet_0001"
            if ":" not in host_part:
                host_part = f"{host_part}:905"
            return f"{scheme}://{host_part}{path}"

        # Normalize endpoint source
        endpoint = base_url or url
        if not endpoint and host:
            host_str = host.strip()
            if not (host_str.startswith("http://") or host_str.startswith("https://")):
                host_str = f"http://{host_str}"
            path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
            use_port = 905 if port is None else int(port)
            has_port = ":" in host_str.split("://", 1)[-1]
            if not has_port:
                host_str = f"{host_str}:{use_port}"
            endpoint = f"{host_str.rstrip('/')}{path}"
        else:
            endpoint = _ensure_endpoint(endpoint)

        if not endpoint:
            raise ValueError("LoeweCoordinator requires base_url or host/resource_path/url")

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} coordinator",
            update_interval=update_interval,
        )

        self.base_url = endpoint.rstrip("/")
        self.client_name = client_name
        self._session_external = session is not None
        self._session: Optional[aiohttp.ClientSession] = session
        self._fcid = random.randint(1000, 9999)
        self.client_id: Optional[str] = None

        self._device = DeviceInfoLite(
            name=device_name or "Loewe TV",
            unique_id=unique_id,
        )

        _LOGGER.debug("LoeweCoordinator endpoint set to: %s", self.base_url)

    # ────────────────────────── session lifecycle ──────────────────────────────
    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_close(self) -> None:
        """Close our client session if we created it."""
        if not self._session_external and self._session and not self._session.closed:
            await self._session.close()

    # ───────────────────────────── SOAP helpers ────────────────────────────────
    def _next_fcid(self) -> int:
        self._fcid = (self._fcid + 1) % 100000
        return self._fcid

    def _envelope(self, inner_xml: str) -> str:
        return (
            f'<s:Envelope xmlns:s="{SOAP_NS}">'
            f"<s:Body>{inner_xml}</s:Body>"
            f"</s:Envelope>"
        )

    async def _soap(self, action: str, inner_xml: str, timeout: float = 20.0) -> Optional[str]:
        """POST a SOAP request. This Loewe firmware prefers a *bare* SOAPAction header."""
        session = await self._session_get()
        payload = self._envelope(inner_xml).encode("utf-8")

        # IMPORTANT: bare action name, and avoid keep-alive right after access
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": action,   # bare action name
            "Connection": "close",  # the TV sometimes drops persistent connections
        }

        async def _do_post() -> tuple[int, str]:
            async with async_timeout.timeout(timeout):
                async with session.post(self.base_url, data=payload, headers=headers) as resp:
                    text = await resp.text()
                    return resp.status, text

        try:
            status, text = await _do_post()
            if status == 200:
                return text
            _LOGGER.debug("SOAP non-200 (%s) for %s: %s", status, action, text[:600])
            return None
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientOSError):
            _LOGGER.debug("SOAP %s: server disconnected; retrying once...", action)
            await asyncio.sleep(0.3)
            try:
                status, text = await _do_post()
                if status == 200:
                    return text
                _LOGGER.debug("SOAP non-200 (%s) for %s (retry): %s", status, action, text[:600])
                return None
            except Exception as err:
                _LOGGER.debug("SOAP %s retry failed: %s", action, err)
                return None
        except asyncio.TimeoutError:
            _LOGGER.debug("SOAP %s timed out", action)
            return None
        except aiohttp.ClientError as err:
            _LOGGER.debug("SOAP %s client error: %s", action, err)
            return None

    def _parse_map(self, xml_text: str) -> Dict[str, str]:
        """Flatten the first level of the SOAP body response into a tag->text map."""
        out: Dict[str, str] = {}
        if not xml_text:
            return out
        try:
            root = ET.fromstring(xml_text)
            body = root.find(_ns("Body", SOAP_NS))
            if body is None:
                return out
            # Flatten first response element
            for resp in body:
                for child in resp:
                    tag = child.tag.split("}")[-1]
                    out[tag] = (child.text or "").strip()
        except ET.ParseError as err:
            _LOGGER.debug("XML parse error: %s", err)
        return out

    # ───────────────────────────── API methods ────────────────────────────────
    async def async_request_access(self) -> bool:
        """Request a ClientId using the full payload this TV expects."""
        # Drop any stale id before requesting anew
        self.client_id = None

        device_type = "Home Assistant"
        device_name = self._device.name or "Loewe TV"
        device_uuid = (self._device.unique_id or "ha-" + self.base_url.split("://", 1)[-1]).replace("/", "_")
        requester = "HA Loewe Integration"

        for attempt in (1, 2, 3):
            fcid = self._next_fcid()
            inner = (
                f'<ltv:RequestAccess xmlns:ltv="{LTV_NS}">'
                f"<ltv:fcid>{fcid}</ltv:fcid>"
                f"<ltv:ClientId>?</ltv:ClientId>"
                f"<ltv:DeviceType>{_xml_escape(device_type)}</ltv:DeviceType>"
                f"<ltv:DeviceName>{_xml_escape(device_name)}</ltv:DeviceName>"
                f"<ltv:DeviceUUID>{_xml_escape(device_uuid)}</ltv:DeviceUUID>"
                f"<ltv:RequesterName>{_xml_escape(requester)}</ltv:RequesterName>"
                f"</ltv:RequestAccess>"
            )
            xml = await self._soap("RequestAccess", inner, timeout=20.0)
            if xml:
                parsed = self._parse_map(xml)
                cid = parsed.get("ClientId")
                if cid:
                    self.client_id = cid
                    _LOGGER.debug("Obtained ClientId: %s", cid)
                    # Give the TV a beat to settle before the next SOAP call
                    await asyncio.sleep(0.4)
                    return True
            await asyncio.sleep(1.5 * attempt)

        _LOGGER.debug("RequestAccess: all retries failed")
        return False

    async def async_get_current_status(self) -> Optional[Dict[str, str]]:
        if not self.client_id:
            ok = await self.async_request_access()
            if not ok:
                return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetCurrentStatus xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetCurrentStatus>"
        )
        xml = await self._soap("GetCurrentStatus", inner, timeout=10.0)
        if xml:
            return self._parse_map(xml)

        # First call right after RequestAccess can race; pause and try once more
        await asyncio.sleep(0.4)
        xml = await self._soap("GetCurrentStatus", inner, timeout=10.0)
        return self._parse_map(xml) if xml else None

    async def async_get_volume(self) -> Optional[int]:
        if not self.client_id:
            ok = await self.async_request_access()
            if not ok:
                return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetVolume xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetVolume>"
        )
        xml = await self._soap("GetVolume", inner, timeout=10.0)
        if not xml:
            return None
        parsed = self._parse_map(xml)  # e.g., {"Value": "180000"} for 18%
        try:
            return int(parsed.get("Value", ""))
        except Exception:
            return None

    async def async_get_mute(self) -> Optional[bool]:
        if not self.client_id:
            ok = await self.async_request_access()
            if not ok:
                return None
        fcid = self._next_fcid()
        inner = (
            f'<ltv:GetMute xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"</ltv:GetMute>"
        )
        xml = await self._soap("GetMute", inner, timeout=10.0)
        if not xml:
            return None
        parsed = self._parse_map(xml)
        val = (parsed.get("Value") or "").strip().lower()
        if val in ("1", "true", "on"):
            return True
        if val in ("0", "false", "off"):
            return False
        return None

    async def async_set_volume(self, value_0_to_1_000_000: int) -> bool:
        """Attempt SOAP volume set; returns True/False for success."""
        value = max(0, min(1_000_000, int(value_0_to_1_000_000)))
        if not self.client_id:
            ok = await self.async_request_access()
            if not ok:
                return False
        fcid = self._next_fcid()
        inner = (
            f'<ltv:SetVolume xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"<ltv:Value>{value}</ltv:Value>"
            f"</ltv:SetVolume>"
        )
        xml = await self._soap("SetVolume", inner, timeout=10.0)
        return xml is not None

    async def async_set_mute(self, mute: bool) -> bool:
        """Set mute state using SOAP (preferred over RC toggle)."""
        if not self.client_id:
            ok = await self.async_request_access()
            if not ok:
                return False
        fcid = self._next_fcid()
        val = "1" if bool(mute) else "0"
        inner = (
            f'<ltv:SetMute xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"<ltv:Value>{val}</ltv:Value>"
            f"</ltv:SetMute>"
        )
        xml = await self._soap("SetMute", inner, timeout=10.0)
        return xml is not None

    async def async_inject_rc_key(self, keycode: int) -> bool:
        """Send a remote control key code (fallbacks like mute/volume/power)."""
        if not self.client_id:
            ok = await self.async_request_access()
            if not ok:
                return False
        fcid = self._next_fcid()
        inner = (
            f'<ltv:InjectRemoteKey xmlns:ltv="{LTV_NS}">'
            f"<ltv:fcid>{fcid}</ltv:fcid>"
            f"<ltv:ClientId>{self.client_id}</ltv:ClientId>"
            f"<ltv:Key>{int(keycode)}</ltv:Key>"
            f"</ltv:InjectRemoteKey>"
        )
        xml = await self._soap("InjectRemoteKey", inner, timeout=10.0)
        return xml is not None

    async def async_test_connection(self) -> bool:
        """Lightweight check used by config flow."""
        st = await self.async_get_current_status()
        return bool(st)

    # ───────────────────────────── polling hook ────────────────────────────────
    async def _async_update_data(self) -> Dict[str, Any]:
        """Pull fresh state from TV. Robust to temporary auth/transport errors."""
        try:
            if not self.client_id:
                # Give the TV a moment if it’s just powered up
                await asyncio.sleep(0.5)

            status = await self.async_get_current_status()

            # Retry once if status failed (often due to expired ClientId)
            if status is None:
                await self.async_request_access()
                status = await self.async_get_current_status()

            vol = await self.async_get_volume() if status is not None else None
            mute = await self.async_get_mute() if status is not None else None

            # Normalize container
            if status is None:
                status = {}

            if vol is not None:
                status["VolumeRaw"] = int(vol)  # 0..1_000_000
            if mute is not None:
                status["MuteRaw"] = 1 if mute else 0

            payload: Dict[str, Any] = {
                "device": {
                    "manufacturer": self._device.manufacturer,
                    "model": self._device.model,
                    "sw_version": self._device.sw_version,
                    "name": self._device.name,
                    "unique_id": self._device.unique_id,
                },
                "status": status,
            }
            return payload
        except Exception as err:
            raise UpdateFailed(str(err)) from err


# Back-compat for existing config_flow import
LoeweTVCoordinator = LoeweCoordinator


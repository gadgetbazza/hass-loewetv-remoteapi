import logging
import xml.etree.ElementTree as ET
import aiohttp
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_OFF
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

SOAP_URL = "http://{host}:905/LOEWE/RemoteService"
SOAP_NS = "urn:loewe-remote:service:Remote:1"


class LoeweTVCoordinator(DataUpdateCoordinator):
    """Coordinator to manage Loewe TV polling and SOAP requests."""

    def __init__(self, hass: HomeAssistant, host: str):
        super().__init__(
            hass,
            _LOGGER,
            name="LoeweTVCoordinator",
            update_interval=timedelta(seconds=10),
        )
        self._host = host
        self._volume = 0.0
        self._muted = False
        self._state = STATE_OFF
        self._source = None
        self._attr_channel = None
        self._attr_app = None
        self._attr_input = None
        self._input_map = {}
        self._channel_map = {}
        self._app_map = {}

    @property
    def host(self) -> str:
        return self._host

    async def _soap_request(self, action: str, body_xml: str) -> str | None:
        url = SOAP_URL.format(host=self._host)
        headers = {"Content-Type": "text/xml; charset=utf-8"}
        envelope = f"""
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
          <s:Body>
            <m:{action} xmlns:m="{SOAP_NS}">
              {body_xml}
            </m:{action}>
          </s:Body>
        </s:Envelope>
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=envelope, headers=headers, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    _LOGGER.debug("SOAP %s HTTP %s", action, resp.status)
        except Exception as err:
            _LOGGER.warning("SOAP %s exception: %s", action, err)
        return None

    async def send_rc_key(self, key_code: int):
        await self._soap_request("InjectRCKey", f"<Key>{key_code}</Key>")

    async def async_update_data(self):
        """Fetch state from the Loewe TV."""
        try:
            # Volume
            resp = await self._soap_request("GetVolume", "")
            if resp:
                root = ET.fromstring(resp)
                vol_elem = root.find(".//CurrentVolume")
                if vol_elem is not None and vol_elem.text is not None:
                    raw = int(vol_elem.text)
                    self._volume = max(0.0, min(1.0, raw / 999999))

            # Mute
            resp = await self._soap_request("GetMute", "")
            if resp:
                root = ET.fromstring(resp)
                mute_elem = root.find(".//Mute")
                if mute_elem is not None and mute_elem.text is not None:
                    self._muted = mute_elem.text == "1"

            # Discover once
            if not self._input_map:
                await self._refresh_inputs()
            if not self._channel_map:
                await self._refresh_channels()
            if not self._app_map:
                await self._refresh_apps()

            # Current media
            resp = await self._soap_request("GetCurrentMedia", "")
            if resp:
                root = ET.fromstring(resp)
                name_elem = root.find(".//Name")
                uuid_elem = root.find(".//Uuid")
                if name_elem is not None and uuid_elem is not None:
                    name = (name_elem.text or "").strip()
                    uuid = (uuid_elem.text or "").strip()
                    self._source = name
                    if uuid in self._input_map.values():
                        self._attr_input = name
                    elif uuid in self._channel_map.values():
                        self._attr_channel = name
                    elif uuid in self._app_map.values():
                        self._attr_app = name

            return {
                "volume": self._volume,
                "muted": self._muted,
                "state":  "on" if self._source else "off",
                "source": self._source,
                "channel": self._attr_channel,
                "app": self._attr_app,
                "input": self._attr_input,
                "inputs": self._input_map,
                "channels": self._channel_map,
                "apps": self._app_map,
            }

        except Exception as err:
            raise UpdateFailed(f"Error updating Loewe TV: {err}") from err

    async def _refresh_inputs(self):
        resp = await self._soap_request("GetListOfMedia", "")
        if not resp:
            return
        root = ET.fromstring(resp)
        for media in root.findall(".//Media"):
            name_elem = media.find("Name")
            uuid_elem = media.find("Uuid")
            if name_elem is not None and uuid_elem is not None:
                name = (name_elem.text or "").strip()
                uuid = (uuid_elem.text or "").strip()
                if name:
                    self._input_map[name] = uuid

    async def _refresh_channels(self):
        resp = await self._soap_request("GetListOfChannelLists", "")
        if not resp:
            return
        root = ET.fromstring(resp)
        list_uuids = [e.text for e in root.findall(".//Uuid") if e.text]
        for list_uuid in list_uuids:
            resp = await self._soap_request("GetChannelList", f"<Uuid>{list_uuid}</Uuid>")
            if not resp:
                continue
            r2 = ET.fromstring(resp)
            for chan in r2.findall(".//Channel"):
                name_elem = chan.find("Name")
                uuid_elem = chan.find("Uuid")
                if name_elem is not None and uuid_elem is not None:
                    name = (name_elem.text or "").strip()
                    uuid = (uuid_elem.text or "").strip()
                    if name:
                        self._channel_map[name] = uuid

    async def _refresh_apps(self):
        resp = await self._soap_request("GetApplicationList", "")
        if not resp:
            return
        root = ET.fromstring(resp)
        for app in root.findall(".//Application"):
            name_elem = app.find("Name")
            uuid_elem = app.find("Uuid")
            if name_elem is not None and uuid_elem is not None:
                name = (name_elem.text or "").strip()
                uuid = (uuid_elem.text or "").strip()
                if name:
                    self._app_map[name] = uuid

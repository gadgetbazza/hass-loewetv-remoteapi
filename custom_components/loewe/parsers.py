"""Response parsers for Loewe TV SOAP API."""

from __future__ import annotations
from typing import Any, Optional
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.const import STATE_UNKNOWN

import logging
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
LTV_NS = "urn:loewe.de:RemoteTV:Tablet"


# ---------------------- Shared Helper ----------------------

def _extract_response_body(xml: Optional[str]) -> Optional[ET.Element]:
    """Return the <m:XXXResponse> element or None if invalid or empty."""
    if not xml:
        return None
    try:
        root = ET.fromstring(xml)
        body = root.find(f".//{{{SOAP_NS}}}Body")
        if body is None or len(body) == 0:
            return None
        resp = next(iter(body))
        # If it has no children and no text, it’s empty (session invalid)
        if len(resp) == 0 and (resp.text is None or not resp.text.strip()):
            _LOGGER.debug("Empty SOAP body for %s — likely session expired", resp.tag)
            return None
        return resp
    except ET.ParseError:
        _LOGGER.debug("Failed to parse SOAP response XML")
        return None


# ---------------------- Individual Parsers ----------------------

def parse_request_access(xml: Optional[str]) -> dict[str, Any]:
    """Parse RequestAccess SOAP response."""
    resp = _extract_response_body(xml)
    if resp is None:
        return {}

    data: dict[str, Any] = {}
    for child in resp:
        tag = child.tag.split("}", 1)[-1]
        data[tag] = child.text

    # Normalise keys
    if "AccessStatus" in data:
        data["State"] = data.pop("AccessStatus")
    return data

def parse_status(xml: Optional[str]) -> dict[str, Any]:
    """Parse GetCurrentStatus SOAP response."""
    resp = _extract_response_body(xml)
    if resp is None:
        return {}

    result: dict[str, Any] = {}
    for child in resp:
        tag = child.tag.split("}", 1)[-1]
        result[tag] = child.text

    # --- Derive Home Assistant media player state
    power = (result.get("Power") or "").lower()
    if power in ("tv", "on"):
        result["ha_state"] = MediaPlayerState.ON
    elif power in ("standby", "off", "idle"):
        result["ha_state"] = MediaPlayerState.OFF
    else:
        result["ha_state"] = STATE_UNKNOWN

    return result



def parse_playback(xml: Optional[str]) -> dict[str, Any]:
    """Parse GetCurrentPlayback SOAP response."""
    resp = _extract_response_body(xml)
    if resp is None:
        return {}

    result: dict[str, Any] = {}
    for child in resp:
        tag = child.tag.split("}", 1)[-1]
        result[tag] = child.text
    return result


def parse_device_data(xml: Optional[str]) -> dict[str, Any]:
    """Parse GetDeviceData SOAP response."""
    resp = _extract_response_body(xml)
    if resp is None:
        return {}

    result: dict[str, Any] = {}
    for child in resp:
        tag = child.tag.split("}", 1)[-1]
        result[tag] = child.text
    return result


def parse_volume(xml: Optional[str]) -> Any:
    """Parse GetVolume SOAP response."""
    resp = _extract_response_body(xml)
    if resp is None:
        return None

    for child in resp:
        tag = child.tag.split("}", 1)[-1]
        if tag.lower() == "value":
            try:
                return int(child.text)
            except (TypeError, ValueError):
                return None
    return None


def parse_mute(xml: Optional[str]) -> Any:
    """Parse GetMute SOAP response."""
    resp = _extract_response_body(xml)
    if resp is None:
        return None

    for child in resp:
        tag = child.tag.split("}", 1)[-1]
        if tag.lower() == "value":
            return child.text == "1"
    return None


def parse_channel_lists(xml: Optional[str]) -> list[dict[str, str]]:
    """
    Parse GetListOfChannelLists SOAP response into:
    [{"name": <Name>, "view": <View>}, ...]
    """
    resp = _extract_response_body(xml)
    if resp is None:
        return []

    out: list[dict[str, str]] = []
    # The response element contains ResultItemChannelList nodes
    for clist in resp.findall(".//ResultItemChannelList"):
        name_el = clist.find("Name")
        view_el = clist.find("View")
        if name_el is not None and view_el is not None:
            out.append({
                "name": (name_el.text or "").strip(),
                "view": (view_el.text or "").strip(),
            })
    return out


def parse_channel_list(xml: Optional[str]) -> list[dict[str, str]]:
    """
    Parse GetChannelList SOAP response into:
    [{"name": <shortInfo|caption|locator>, "locator": <locator>}, ...]
    """
    resp = _extract_response_body(xml)
    if resp is None:
        return []

    items: list[dict[str, str]] = []
    for ref in resp.findall(".//ResultItemReference"):
        locator = ref.attrib.get("locator")
        short_info = ref.attrib.get("shortInfo")
        caption = ref.attrib.get("caption")
        if locator:
            items.append({
                "name": (short_info or caption or locator).strip(),
                "locator": locator.strip(),
            })
    return items

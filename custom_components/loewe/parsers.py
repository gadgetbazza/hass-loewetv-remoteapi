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


def _local(tag: str) -> str:
    """Strip any {namespace} from an element or attribute name."""
    return tag.split("}", 1)[-1]


def _find(el: ET.Element, name: str) -> Optional[ET.Element]:
    """Return the first descendant whose local name is `name`."""
    return next((e for e in el.iter() if _local(e.tag) == name), None)


def _attr(el: ET.Element, name: str) -> Optional[str]:
    """Return an attribute by local name (the TV sometimes namespaces attributes)."""
    return next((v for k, v in el.attrib.items() if _local(k) == name), None)


def is_empty_response(xml: Optional[str]) -> bool:
    """Return True for a well-formed SOAP reply whose <XXXResponse> has no content.

    This is how the TV answers requests made with an expired/unknown ClientId.
    Network failures (None) and unparsable XML are not treated as empty.
    """
    if not xml:
        return False
    try:
        body = ET.fromstring(xml).find(f".//{{{SOAP_NS}}}Body")
    except ET.ParseError:
        return False
    if body is None or len(body) == 0:
        return False
    resp = body[0]
    return len(resp) == 0 and not (resp.text or "").strip()


def device_mac(device: dict[str, Any]) -> Optional[str]:
    """Return the TV's MAC address from parsed GetDeviceData, if present."""
    mac = device.get("MAC-Address-LAN") or device.get("MAC-Address")
    return mac.strip() if mac else None


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
    # The TV reports standby as Power=idle. Map it to OFF, not IDLE: HA's power
    # toggle treats every state except OFF as on, so IDLE would send power-off again.
    power = (result.get("Power") or "").lower()
    if power in ("tv", "on"):
        result["ha_state"] = MediaPlayerState.ON
    else:
        result["ha_state"] = MediaPlayerState.OFF

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

    out: list[dict[str, Any]] = []
    # The response element contains ResultItemChannelList nodes
    for clist in resp.findall(".//ResultItemChannelList"):
        name_el = clist.find("Name")
        view_el = clist.find("View")
        total_el = clist.find("TotalResults")
        if name_el is not None and view_el is not None:
            try:
                total = int(total_el.text) if total_el is not None else None
            except (TypeError, ValueError):
                total = None
            out.append({
                "name": (name_el.text or "").strip(),
                "view": (view_el.text or "").strip(),
                "total": total,
            })
    return out


def parse_channel_list_page(xml: Optional[str]) -> tuple[list[dict[str, str]], Optional[int]]:
    """
    Parse one page of a GetChannelList SOAP response.

    Returns (items, total_results), each item being
    {"name": <shortInfo|caption|locator>, "locator", "uuid", "number"}.
    "uuid" (mediaItemUuid) identifies a TV channel across lists; it is NOT
    unique for AV inputs, which must be matched by locator.
    """
    resp = _extract_response_body(xml)
    if resp is None:
        return [], None

    total: Optional[int] = None
    fragment = _find(resp, "ResultItemFragment")
    if fragment is not None:
        try:
            total = int(_attr(fragment, "totalResults") or "")
        except ValueError:
            total = None

    items: list[dict[str, str]] = []
    for ref in resp.findall(".//ResultItemReference"):
        locator = ref.attrib.get("locator")
        short_info = ref.attrib.get("shortInfo")
        caption = ref.attrib.get("caption")
        if locator:
            items.append({
                "name": (short_info or caption or locator).strip(),
                "locator": locator.strip(),
                "uuid": (ref.attrib.get("mediaItemUuid") or "").strip(),
                "number": (caption or "").strip(),
            })
    return items, total


def parse_channel_list(xml: Optional[str]) -> list[dict[str, str]]:
    """Parse a GetChannelList SOAP response into its items (see parse_channel_list_page)."""
    return parse_channel_list_page(xml)[0]


def parse_event(xml: Optional[str]) -> dict[str, Any]:
    """
    Parse GetCurrentEvent / GetNextEvent into {"name", "info", "start", "duration"}.

    The TV answers with either <LiveEvent><Name> or (per the spec)
    <MediaEvent><MediaInformation><ShortInfo>; both are handled. "start" is a
    Unix timestamp and "duration" is in seconds. Returns {} if there is no event.
    """
    resp = _extract_response_body(xml)
    if resp is None:
        return {}

    name_el = _find(resp, "Name")
    if name_el is None:
        name_el = _find(resp, "ShortInfo")
    name = (name_el.text or "").strip() if name_el is not None else ""
    if not name:
        return {}

    info_el = _find(resp, "ExtendedInfo")
    event: dict[str, Any] = {
        "name": name,
        "info": (info_el.text or "").strip() if info_el is not None else "",
        "start": None,
        "duration": None,
    }
    sched = _find(resp, "ScheduledTime")
    if sched is not None:
        try:
            event["start"] = int(_attr(sched, "startTime") or "")
            event["duration"] = int(_attr(sched, "duration") or "")
        except ValueError:
            pass
    return event

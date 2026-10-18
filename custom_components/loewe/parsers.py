"""Response parsers for Loewe TV SOAP API."""

from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from homeassistant.components.media_player.const import MediaPlayerState

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
    Parse GetCurrentEvent / GetNextEvent into {"name", "info", "start", "duration", "locator"}.

    The TV answers with either <LiveEvent><Name> or (per the spec)
    <MediaEvent><MediaInformation><ShortInfo>; both are handled. "start" is a
    Unix timestamp and "duration" is in seconds. "locator" is the channel the
    event belongs to (None if not given). Returns {} if there is no event.
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
    locator_el = _find(resp, "Locator")
    if locator_el is None:
        locator_el = _find(resp, "ItemLocator")
    event: dict[str, Any] = {
        "name": name,
        "info": (info_el.text or "").strip() if info_el is not None else "",
        "start": None,
        "duration": None,
        "locator": (locator_el.text or "").strip() or None if locator_el is not None else None,
    }
    sched = _find(resp, "ScheduledTime")
    if sched is not None:
        try:
            event["start"] = int(_attr(sched, "startTime") or "")
            event["duration"] = int(_attr(sched, "duration") or "")
        except ValueError:
            pass
    return event


def full_title(title: str, subtitle: str | None) -> str:
    """Join a guide title cut short with "..." to its continuation.

    UK guide data splits long titles: "The Balkans: Europe's Forgotten..." with
    the rest starting the description ("...Frontier. 1/2. The BBC's...").
    Otherwise the description isn't part of the title.
    """
    if subtitle and title.endswith("...") and subtitle.startswith("..."):
        rest = subtitle[3:].split(". ", 1)[0].rstrip(".")
        return f"{title[:-3]} {rest}" if not title[-4:-3].isspace() else f"{title[:-3]}{rest}"
    return title


# GetTimerList Attributes bits (API spec 9.13.1)
TIMER_ATTR_RECORDING = 0x80
TIMER_ATTR_CONFLICT = 0x20


def parse_timer_list(xml: Optional[str]) -> Optional[list[dict[str, Any]]]:
    """
    Parse GetTimerList into a list of recording timers, sorted by start time.

    Each timer is {"id", "title", "channel", "channel_number", "channel_id",
    "start", "end", "recording_type", "attributes"}; "start"/"end" are Unix
    timestamps. Returns None if the reply has no timer list at all (not
    reachable, or not supported), [] if there are no timers.
    """
    resp = _extract_response_body(xml)
    if resp is None or _find(resp, "ResultTimerListFragment") is None:
        return None

    def text(el: ET.Element, name: str) -> Optional[str]:
        found = _find(el, name)
        return (found.text or "").strip() or None if found is not None else None

    def number(el: ET.Element, name: str) -> Optional[int]:
        try:
            return int(text(el, name) or "")
        except ValueError:
            return None

    timers = []
    for entry in resp.iter():
        if _local(entry.tag) != "ResultTimerList":
            continue
        timers.append({
            "id": text(entry, "EntryUuid"),
            "title": text(entry, "EntryTitle"),
            "channel": text(entry, "SourceName"),
            "channel_number": text(entry, "SourceNo"),
            "channel_id": text(entry, "SourceUuid"),
            "start": number(entry, "Start"),
            "end": number(entry, "End"),
            "recording_type": number(entry, "RecordingType") or 0,
            "attributes": number(entry, "Attributes") or 0,
        })
    return sorted(timers, key=lambda t: t["start"] or 0)


def parse_result(xml: Optional[str]) -> Optional[int]:
    """Return the <Result> code of a command reply (0 = accepted), or None if missing."""
    resp = _extract_response_body(xml)
    found = _find(resp, "Result") if resp is not None else None
    try:
        return int((found.text or "").strip()) if found is not None else None
    except ValueError:
        return None


# de.loewe.sl2.epg fields requested by the guide, in this order (API spec 9.22.1;
# meanings of 2003/2005/2008 found by testing)
EPG_FIELDS = (2003, 2004, 2005, 2007, 2008)  # event id, title, description, start, end


def parse_guide(xml: Optional[str]) -> Optional[list[dict[str, Any]]]:
    """
    Parse a CreateIterator reply over the EPG table (fields EPG_FIELDS).

    Returns [{"event_id", "title", "description", "start", "end"}] with Unix
    timestamps, or None if the reply has no rows element (no answer, or refused).
    """
    resp = _extract_response_body(xml)
    rows = _find(resp, "Rows") if resp is not None else None
    if rows is None:
        return None

    programmes = []
    for row in rows:
        if _local(row.tag) != "Row":
            continue
        values = [(v.text or "").strip() for v in row if _local(v.tag) == "V"]
        if len(values) < len(EPG_FIELDS):
            continue
        event_id, title, description, start, end = values[: len(EPG_FIELDS)]
        try:
            start_ts, end_ts = int(start), int(end)
        except ValueError:
            continue
        if title:
            programmes.append({
                "event_id": event_id or None,
                "title": full_title(title, description),
                "description": description or None,
                "start": start_ts,
                "end": end_ts,
            })
    return programmes


def parse_recordings(xml: Optional[str]) -> Optional[list[dict[str, Any]]]:
    """
    Parse GetDRPlusArchive into the recorder's recordings, newest first.

    Each is {"locator", "title", "subtitle", "channel", "start" (Unix time),
    "duration" (seconds), "image"}. None if the reply has no archive list.
    """
    resp = _extract_response_body(xml)
    if resp is None or _find(resp, "ResultItemDRPlusFragment") is None:
        return None

    def text(el: ET.Element, name: str) -> Optional[str]:
        found = _find(el, name)
        return (found.text or "").strip() or None if found is not None else None

    recordings = []
    for item in resp.iter():
        if _local(item.tag) != "ResultItemDRPlus":
            continue
        locator = text(item, "Locator")
        if not locator:
            continue
        start = None
        if started := text(item, "StartTime"):
            try:
                start = int(datetime.fromisoformat(started).timestamp())
            except ValueError:
                pass
        duration = None
        if length := text(item, "Duration"):  # "HH:MM:SS.mmm"
            try:
                hours, minutes, seconds = length.split(":")
                duration = int(hours) * 3600 + int(minutes) * 60 + int(float(seconds))
            except ValueError:
                pass
        recordings.append({
            "locator": locator,
            "title": full_title(text(item, "Title") or "Recording", text(item, "Subtitle")),
            "subtitle": text(item, "Subtitle"),
            "channel": text(item, "ServiceName"),
            "start": start,
            "duration": duration,
            "image": text(item, "ImageUrl"),
        })
    return sorted(recordings, key=lambda r: r["start"] or 0, reverse=True)

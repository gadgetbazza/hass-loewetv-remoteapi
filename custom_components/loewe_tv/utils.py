"""Utility helpers for Loewe TV integration."""
from __future__ import annotations

import os
import socket
import uuid
import logging
import re
from typing import Optional
from typing import Tuple

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _get_default_route_iface() -> Optional[str]:
    """Return the network interface name used for the default route (Linux/HAOS)."""
    try:
        with open("/proc/net/route", "r") as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4:
                    iface, dest_hex, flags_hex = parts[0], parts[1], parts[3]
                    if dest_hex == "00000000" and (int(flags_hex, 16) & 0x1):
                        return iface
    except Exception as e:
        _LOGGER.debug("Failed to read /proc/net/route: %s", e)

    # Fallback: use a dummy UDP connect to infer outbound interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        _ = s.getsockname()[0]  # not used, just forces a routing decision
        s.close()
        for iface in os.listdir("/sys/class/net"):
            if _read_iface_mac(iface):
                return iface
    except Exception as e:
        _LOGGER.debug("Failed to infer default interface via socket: %s", e)

    return None


def _read_iface_mac(iface: str) -> Optional[str]:
    """Read the MAC address of a given network interface (blocking)."""
    try:
        with open(f"/sys/class/net/{iface}/address", "r") as f:
            mac = f.read().strip().lower()
            if mac and mac != "00:00:00:00:00:00":
                return mac
    except Exception as e:
        _LOGGER.debug("Failed to read MAC for iface %s: %s", iface, e)
    return None


def get_device_uuid(iface: str | None = None) -> str:
    """Blocking helper: derive a stable UUID based on MAC address."""
    iface = iface or _get_default_route_iface()
    mac = _read_iface_mac(iface) if iface else None

    if not mac:
        _LOGGER.warning("No usable MAC found, falling back to random UUID")
        return "001122334455"

    # Generate a namespace-based UUID so it stays stable across restarts
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, mac))


async def async_get_device_uuid(hass: HomeAssistant, iface: str | None = None) -> str:
    """Async wrapper for get_device_uuid (offloads blocking I/O)."""
    return await hass.async_add_executor_job(get_device_uuid, iface)


# --- WOL helpers ------------------------------------------------------------
def _normalize_mac(mac: str) -> bytes:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC: {mac}")
    return bytes.fromhex(cleaned)

def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a Wake-on-LAN magic packet to the given MAC."""
    mac_bytes = _normalize_mac(mac)
    packet = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()

async def async_send_wol(hass: HomeAssistant, mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Async wrapper for send_wol."""
    await hass.async_add_executor_job(send_wol, mac, broadcast, port)

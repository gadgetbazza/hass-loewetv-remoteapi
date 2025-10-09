"""Utility helpers for Loewe TV integration."""

from __future__ import annotations

import os
import re
import socket
import logging
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# --- Network / MAC helpers --------------------------------------------------

def _get_default_route_iface() -> Optional[str]:
    """Return the default network interface name (Linux/HAOS)."""
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

    # Fallback: UDP connect trick to infer outbound iface
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            _ = s.getsockname()[0]
        for iface in os.listdir("/sys/class/net"):
            if _read_iface_mac(iface):
                return iface
    except Exception as e:
        _LOGGER.debug("Failed to infer default interface via socket: %s", e)

    return None


def _read_iface_mac(iface: str) -> Optional[str]:
    """Return the MAC address of a network interface, or None if invalid."""
    try:
        with open(f"/sys/class/net/{iface}/address", "r") as f:
            mac = f.read().strip().lower()
            if mac and mac != "00:00:00:00:00:00":
                return mac
    except Exception as e:
        _LOGGER.debug("Failed to read MAC for iface %s: %s", iface, e)
    return None


def get_device_mac(iface: str | None = None) -> str:
    """Blocking helper: return the MAC address of a network interface."""
    iface = iface or _get_default_route_iface()
    mac = _read_iface_mac(iface) if iface else None

    if not mac:
        _LOGGER.warning("No usable MAC found, falling back to fake MAC 00:11:22:33:44:55")
        return "00:11:22:33:44:55"
    return mac


async def async_get_device_mac(hass: HomeAssistant, iface: str | None = None) -> str:
    """Async wrapper for get_device_mac (offloads blocking I/O)."""
    return await hass.async_add_executor_job(get_device_mac, iface)


# --- Wake-on-LAN helpers ----------------------------------------------------

def _normalize_mac(mac: str) -> bytes:
    """Convert a MAC string to raw bytes for WOL."""
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC: {mac}")
    return bytes.fromhex(cleaned)


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a Wake-on-LAN magic packet."""
    try:
        mac_bytes = _normalize_mac(mac)
    except ValueError as err:
        _LOGGER.error("Invalid MAC for WOL: %s", err)
        return

    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))


async def async_send_wol(
    hass: HomeAssistant,
    mac: str,
    broadcast: str = "255.255.255.255",
    port: int = 9,
) -> None:
    """Async wrapper for send_wol."""
    await hass.async_add_executor_job(send_wol, mac, broadcast, port)

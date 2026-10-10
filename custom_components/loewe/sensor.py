"""Sensor platform for Loewe TV."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LoeweTVCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Loewe TV sensors from a config entry."""
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [CurrentServiceSensor(coordinator, entry), CurrentProgrammeSensor(coordinator, entry)]
    )


def _iso(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


class CurrentServiceSensor(CoordinatorEntity, SensorEntity):
    """Sensor representing the currently active service on the Loewe TV."""

    _attr_has_entity_name = True
    _attr_name = "Current Service"

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_service"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | None:
        """Return the current channel name, or the AV input name."""
        return self.coordinator.current_service_name


class CurrentProgrammeSensor(CoordinatorEntity, SensorEntity):
    """Sensor with the programme currently showing on the tuned TV channel (from the EPG)."""

    _attr_has_entity_name = True
    _attr_name = "Current Programme"
    _attr_icon = "mdi:television-guide"

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_programme"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str | None:
        """Return the programme title, or None when not watching a TV channel."""
        event = (self.coordinator.data or {}).get("event") or {}
        return (event.get("name") or "")[:255] or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        channel = data.get("channel") or {}
        event = data.get("event") or {}
        nxt = data.get("next_event") or {}
        start, duration = event.get("start"), event.get("duration")
        return {
            "channel": channel.get("name"),
            "channel_number": channel.get("number"),
            "description": event.get("info") or None,
            "start": _iso(start),
            "end": _iso(start + duration) if start is not None and duration else None,
            "next_programme": nxt.get("name"),
            "next_start": _iso(nxt.get("start")),
        }

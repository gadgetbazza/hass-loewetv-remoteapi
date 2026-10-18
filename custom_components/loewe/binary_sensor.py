"""Binary sensor platform for Loewe TV."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LoeweConfigEntry, LoeweTVCoordinator
from .parsers import TIMER_ATTR_RECORDING


async def async_setup_entry(
    hass: HomeAssistant, entry: LoeweConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Loewe TV binary sensors from a config entry."""
    async_add_entities([RecordingBinarySensor(entry.runtime_data, entry)])


class RecordingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On while the TV's DR+ recorder is recording a timer."""

    _attr_has_entity_name = True
    _attr_name = "Recording"
    _attr_icon = "mdi:record-rec"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: LoeweTVCoordinator, entry: LoeweConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_recording"
        self._attr_device_info = coordinator.device_info

    @property
    def _active(self) -> list[dict[str, Any]]:
        timers = (self.coordinator.data or {}).get("timers") or []
        return [timer for timer in timers if timer["attributes"] & TIMER_ATTR_RECORDING]

    @property
    def is_on(self) -> bool | None:
        """Return True while a timer is recording, None until the timers have been read."""
        if (self.coordinator.data or {}).get("timers") is None:
            return None
        return bool(self._active)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        active = self._active
        return {
            "title": active[0]["title"] if active else None,
            "channel": active[0]["channel"] if active else None,
        }

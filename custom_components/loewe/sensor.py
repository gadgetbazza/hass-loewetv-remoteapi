"""Sensor platform for Loewe TV."""

from __future__ import annotations

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
    async_add_entities([CurrentServiceSensor(coordinator, entry)])


class CurrentServiceSensor(CoordinatorEntity, SensorEntity):
    """Sensor representing the currently active service on the Loewe TV."""

    _attr_has_entity_name = True
    _attr_name = "Current Service"

    def __init__(self, coordinator: LoeweTVCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_service"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": coordinator.device_name or "Loewe TV",
            "manufacturer": "Loewe",
            "model": coordinator._device_info.get("Chassis", "Unknown") if coordinator._device_info else "Unknown",
            "sw_version": coordinator._device_info.get("SW-Version", "") if coordinator._device_info else "",
        }

    @property
    def native_value(self) -> str | None:
        """Return the current service name."""
        status = self.coordinator.data.get("status") if self.coordinator.data else {}
        return status.get("ServiceName") or status.get("CurrentService")

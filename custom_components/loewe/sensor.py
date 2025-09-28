from __future__ import annotations
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .coordinator import LoeweTVCoordinator
from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CurrentServiceSensor(coordinator, entry.entry_id)])

class CurrentServiceSensor(Entity):
    _attr_should_poll = False

    def __init__(self, coordinator: LoeweTVCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = "Loewe TV Current Service"
        self._attr_unique_id = f"{entry_id}_service"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": self.coordinator.device_name or "Loewe TV",
            "manufacturer": "Loewe",
        }

    @property
    def state(self):
        status = self.coordinator.data.get("status") if self.coordinator.data else {}
        svc = status.get("ServiceName") or status.get("CurrentService") or None
        return svc

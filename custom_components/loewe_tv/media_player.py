from __future__ import annotations
import logging
from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerDeviceClass, SUPPORT_VOLUME_SET, SUPPORT_VOLUME_STEP, SUPPORT_TURN_ON, SUPPORT_TURN_OFF
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LoeweTVCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LoeweMediaPlayer(coordinator, entry.entry_id)])

class LoeweMediaPlayer(MediaPlayerEntity):
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_should_poll = False

    def __init__(self, coordinator: LoeweTVCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = self.coordinator.device_name or "Loewe TV"
        self._attr_unique_id = f"{entry_id}_media"
        self._state = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": self.coordinator.device_name or "Loewe TV",
            "manufacturer": "Loewe",
            "model": self.coordinator._device_info.get("Chassis", "Unknown"),
        }

    @property
    def state(self):
        return self._state

    @property
    def supported_features(self):
        return SUPPORT_VOLUME_STEP | SUPPORT_TURN_ON | SUPPORT_TURN_OFF

    async def async_volume_up(self) -> None:
        await self.coordinator.async_inject_rc_key(21)

    async def async_volume_down(self) -> None:
        await self.coordinator.async_inject_rc_key(20)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_inject_rc_key(22)
        self._state = "on"

    async def async_turn_off(self) -> None:
        await self.coordinator.async_inject_rc_key(25)
        self._state = "off"

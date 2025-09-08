from __future__ import annotations
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .coordinator import LoeweTVCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

RC_KEYS = {
    "Volume Up": 21,
    "Volume Down": 20,
    "Mute": 13,
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        LoeweTVButton(coordinator, entry.entry_id, name, code)
        for name, code in RC_KEYS.items()
    ]
    async_add_entities(entities, True)

class LoeweTVButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LoeweTVCoordinator, entry_id: str, name: str, code: int) -> None:
        self._coordinator = coordinator
        self._entry_id = entry_id
        self._code = code
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_btn_{code}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._coordinator.device_name or "Loewe TV",
            manufacturer="Loewe",
            model=self._coordinator._device_info.get("Chassis", "Unknown"),
            sw_version=self._coordinator._device_info.get("SW-Version", ""),
        )

    async def async_press(self) -> None:
        _LOGGER.debug("Button pressed: %s (RC %s)", self._attr_name, self._code)
        ok = await self._coordinator.async_inject_rc_key(self._code)
        if ok:
            _LOGGER.debug("%s command succeeded", self._attr_name)
        else:
            _LOGGER.warning("%s command failed", self._attr_name)

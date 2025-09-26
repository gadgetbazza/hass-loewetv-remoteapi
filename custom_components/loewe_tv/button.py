from __future__ import annotations
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .coordinator import LoeweTVCoordinator
from .const import DOMAIN, LOEWE_RC_CODES  # import the shared dictionary

_LOGGER = logging.getLogger(__name__)

# Curated subset of buttons to expose
RC_BUTTONS = {
    "Volume Up": "volume_up",
    "Volume Down": "volume_down",
    "Mute": "mute",
    "Menu": "menu",
    "Back": "back",
    "Info": "info",
    "Red": "red",
    "Green": "green",
    "Yellow": "yellow",
    "Blue": "blue",
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        LoeweTVButton(coordinator, entry.entry_id, name, key)
        for name, key in RC_BUTTONS.items()
    ]
    async_add_entities(entities, True)

class LoeweTVButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False   # 🔹 hide by default

    def __init__(self, coordinator: LoeweTVCoordinator, entry_id: str, name: str, rc_key: str) -> None:
        self._coordinator = coordinator
        self._entry_id = entry_id
        self._rc_key = rc_key
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_btn_{rc_key}"

    @property
    def device_info(self) -> DeviceInfo:
        device_info = self._coordinator._device_info or {}
        base_name = (
            device_info.get("NetworkHostName")
            or self._coordinator.device_name
            or "Loewe TV"
        )

        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=base_name,
            manufacturer="Loewe",
            model=device_info.get("Chassis", "Unknown"),
            sw_version=device_info.get("SW-Version", ""),
        )

    async def async_press(self) -> None:
        keycode = LOEWE_RC_CODES.get(self._rc_key)
        if keycode is None:
            _LOGGER.error("Unknown RC key: %s", self._rc_key)
            return

        _LOGGER.debug("Button pressed: %s (RC %s)", self._attr_name, keycode)
        ok = await self._coordinator.async_inject_rc_key(keycode)
        if ok:
            _LOGGER.debug("%s command succeeded", self._attr_name)
        else:
            _LOGGER.warning("%s command failed", self._attr_name)


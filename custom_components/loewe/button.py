"""Button platform for Loewe TV."""

from __future__ import annotations
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LoeweConfigEntry, LoeweTVCoordinator
from .const import LOEWE_RC_CODES

_LOGGER = logging.getLogger(__name__)

# Curated subset of RC buttons to expose in HA
RC_BUTTONS: dict[str, str] = {
    "Volume Up": "vol_up",
    "Volume Down": "vol_down",
    "Mute": "mute",
    "Channel Up": "prog_up",
    "Channel Down": "prog_down",
    "Menu": "menu",
    "Info": "info",
    "Red": "red",
    "Green": "green",
    "Yellow": "yellow",
    "Blue": "blue",
    "Right": "right",
    "Left": "left",
    "Up": "up",
    "Down": "down",
    "OK": "ok",
    "Home": "media",
    "Back": "end",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LoeweConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Loewe TV buttons from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        LoeweTVButton(coordinator, entry.entry_id, name, key)
        for name, key in RC_BUTTONS.items()
    ]
    async_add_entities(entities)


class LoeweTVButton(CoordinatorEntity[LoeweTVCoordinator], ButtonEntity):
    """Representation of a Loewe RC button in HA."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False  # Hide by default

    def __init__(
        self,
        coordinator: LoeweTVCoordinator,
        entry_id: str,
        name: str,
        rc_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._rc_key = rc_key
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_btn_{rc_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return Loewe device info so buttons group under the TV device."""
        return self.coordinator.device_info

    async def async_press(self) -> None:
        """Send the RC key associated with this button."""
        keycode = LOEWE_RC_CODES.get(self._rc_key)
        if keycode is None:
            _LOGGER.error("Unknown RC key: %s", self._rc_key)
            return

        _LOGGER.debug("LoeweTV Button pressed: %s (RC %s)", self._attr_name, keycode)
        if await self.coordinator.async_inject_rc_key(keycode):
            _LOGGER.debug("%s command succeeded", self._attr_name)
        else:
            _LOGGER.warning("%s command failed", self._attr_name)

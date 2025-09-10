from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LoeweTVCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LoeweTVMediaPlayer(coordinator, entry.entry_id)])


class LoeweTVMediaPlayer(MediaPlayerEntity):
    _attr_should_poll = False

    def __init__(self, coordinator: LoeweTVCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_unique_id = entry_id
        self._attr_name = coordinator.device_name or "Loewe TV"
        self._attr_supported_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_name = self.coordinator.device_name or self._attr_name
        self.async_write_ha_state()

    def _status(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("status", {}) if getattr(self.coordinator, "data", None) else {}

    @property
    def available(self) -> bool:
        return self.coordinator is not None

    @property
    def state(self) -> Optional[MediaPlayerState]:
        status = self._status()
        power = (status.get("Power") or "").lower()
        if power in ("tv", "on"):
            return MediaPlayerState.ON
        if power in ("idle", "standby", "off"):
            return MediaPlayerState.OFF
        return MediaPlayerState.OFF if not status else MediaPlayerState.ON

    @property
    def is_volume_muted(self) -> Optional[bool]:
        status = self._status()
        raw = status.get("MuteRaw")
        if raw is None:
            return None
        return bool(int(raw))

    def _infer_scale(self, raw: int) -> int:
        return 1000 if raw <= 100000 else 10000

    @property
    def volume_level(self) -> Optional[float]:
        status = self._status()
        raw = status.get("VolumeRaw")
        if raw is None:
            return None
        try:
            iv = int(raw)  # e.g. 180000 for OSD 18
            vol_0_100 = int(round(iv / 10000))  # → 0..100
            vol_0_100 = max(0, min(100, vol_0_100))
            return vol_0_100 / 100.0
        except Exception:
            return None

    @property
    def device_info(self) -> dict[str, Any]:
        info = getattr(self.coordinator, "_device_info", {}) or {}
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "manufacturer": "Loewe",
            "name": self.coordinator.device_name or "Loewe TV",
            "model": info.get("Chassis", "Unknown"),
            "sw_version": info.get("SW-Version", None),
        }

    async def async_turn_on(self) -> None:
        _LOGGER.debug("Turn on via RC key")
        await self.coordinator.async_inject_rc_key(22)
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        _LOGGER.debug("Turn off via RC key")
        await self.coordinator.async_inject_rc_key(25)
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        await self.coordinator.async_inject_rc_key(21)
        self.async_write_ha_state()

    async def async_volume_down(self) -> None:
        await self.coordinator.async_inject_rc_key(20)
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.async_inject_rc_key(13)
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        # HA slider 0.0–1.0 → 0–100
        target_0_100 = int(round(max(0.0, min(1.0, volume)) * 100))

        # API expects ~0..999999, with 1 OSD step = 10_000 units.
        # Use 999_999 for 100 to avoid overshooting the documented max.
        api_value = 999_999 if target_0_100 >= 100 else target_0_100 * 10_000

        ok = await self.coordinator.async_set_volume(api_value)
        if ok:
            self.async_write_ha_state()
            return

        # Fallback: step via RC keys if SOAP failed
        current = self.volume_level
        current_0_100 = int(round(current * 100)) if current is not None else 50
        step = target_0_100 - current_0_100
        key = 21 if step > 0 else 20
        for _ in range(abs(step)):
            await self.coordinator.async_inject_rc_key(key)

        self.async_write_ha_state()

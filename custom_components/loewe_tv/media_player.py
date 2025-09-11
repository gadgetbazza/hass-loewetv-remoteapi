"""Media Player entity for Loewe TV using the Remote API."""

from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

# Import constants (including RC key codes) from const.py
from .const import (
    DOMAIN,
    RC_KEY_MUTE_TOGGLE,
    RC_KEY_POWER,
    RC_KEY_VOL_DOWN,
    RC_KEY_VOL_UP,
)

# Coordinator class
from .coordinator import LoeweCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Loewe TV media player from a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: LoeweCoordinator | None = data.get("coordinator")

    if coordinator is None:
        # Defensive fallback: construct a coordinator if integration didn't stash one
        base_url = entry.data.get("base_url") or entry.data.get("host") or entry.data.get("url")
        if not base_url:
            raise RuntimeError("Loewe base URL missing from config entry")
        coordinator = LoeweCoordinator(
            hass,
            base_url=base_url,
            client_name="HomeAssistant",
            device_name=entry.title or "Loewe TV",
            unique_id=entry.unique_id,
        )
        await coordinator.async_config_entry_first_refresh()

    entity = LoeweTVMediaPlayer(coordinator, entry)
    async_add_entities([entity])


class LoeweTVMediaPlayer(CoordinatorEntity[LoeweCoordinator], MediaPlayerEntity):
    """Representation of a Loewe TV as a MediaPlayer."""

    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: LoeweCoordinator, entry: ConfigEntry) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        MediaPlayerEntity.__init__(self)

        self._entry = entry
        device = (coordinator.data or {}).get("device", {})
        self._attr_name = device.get("name") or entry.title or "Loewe TV"
        self._attr_unique_id = device.get("unique_id") or entry.entry_id

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "manufacturer": device.get("manufacturer") or "Loewe",
            "model": device.get("model") or "TV",
            "sw_version": device.get("sw_version"),
            "name": self._attr_name,
        }

    def _status(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("status") or {}

    @property
    def state(self) -> Optional[MediaPlayerState]:
        power = (self._status().get("Power") or "").strip().lower()
        if power in ("tv", "on"):
            return MediaPlayerState.ON
        if power in ("idle", "standby", "off"):
            return MediaPlayerState.OFF
        return MediaPlayerState.ON if self._status() else None

    @property
    def is_volume_muted(self) -> Optional[bool]:
        raw = self._status().get("MuteRaw")
        if raw is None:
            return None
        try:
            return bool(int(raw))
        except Exception:
            return None

    @property
    def volume_level(self) -> Optional[float]:
        """Return volume in 0.0..1.0 (Loewe native is 0..1,000,000 → OSD = raw/10_000)."""
        raw = self._status().get("VolumeRaw")
        if raw is None:
            return None
        try:
            iv = int(raw) // 10_000  # → 0..100
            iv = max(0, min(100, iv))
            return iv / 100.0
        except Exception:
            return None

    # ─────────────────────────── control methods ──────────────────────────────
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume (0.0..1.0). Attempt SOAP first, fallback to RC steps."""
        volume = max(0.0, min(1.0, float(volume)))
        target_0_100 = int(round(volume * 100))
        # Loewe expects 0..1_000_000 (OSD = raw/10_000)
        ok = await self.coordinator.async_set_volume(target_0_100 * 10_000)
        if not ok:
            current = self.volume_level
            if current is not None:
                cur = int(round(current * 100))
                steps = target_0_100 - cur
                for _ in range(abs(steps)):
                    await self.coordinator.async_inject_rc_key(RC_KEY_VOL_UP if steps > 0 else RC_KEY_VOL_DOWN)
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        await self.coordinator.async_inject_rc_key(RC_KEY_VOL_UP)
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self.coordinator.async_inject_rc_key(RC_KEY_VOL_DOWN)
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        """Set mute on/off. Try SOAP first; fallback to RC toggle if needed."""
        current = self.is_volume_muted
        if current is not None and current == bool(mute):
            return

        ok = await self.coordinator.async_set_mute(bool(mute))
        if not ok:
            # Fallback: toggle once. Since we checked current above, one toggle should reach target.
            await self.coordinator.async_inject_rc_key(RC_KEY_MUTE_TOGGLE)

        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.coordinator.async_inject_rc_key(RC_KEY_POWER)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.coordinator.async_inject_rc_key(RC_KEY_POWER)
        await self.coordinator.async_request_refresh()

    # ─────────────────────────── lifecycle hooks ──────────────────────────────
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


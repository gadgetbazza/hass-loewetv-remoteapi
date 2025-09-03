import logging
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)

RC_KEY_POWER_ON = 22
RC_KEY_POWER_OFF = 25
RC_KEY_VOL_UP = 21
RC_KEY_VOL_DOWN = 20

SUPPORT_LOEWE = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    coordinator: LoeweTVCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data["name"]
    async_add_entities([LoeweTVMediaPlayer(coordinator, name)], True)


class LoeweTVMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of the Loewe TV as a MediaPlayer entity."""

    def __init__(self, coordinator: LoeweTVCoordinator, name: str):
        super().__init__(coordinator)
        self._attr_name = name
        self._coordinator = coordinator

    @property
    def unique_id(self) -> str:
        return f"{self._coordinator.host}_media_player"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.host)},
            name=self._attr_name,
            manufacturer="Loewe",
            model="Bild TV",
            sw_version="Remote API",
        )

    @property
    def state(self):
        state = self._coordinator.data.get("state")
        return STATE_ON if state == "on" else STATE_OFF

    @property
    def supported_features(self):
        return SUPPORT_LOEWE

    @property
    def volume_level(self):
        return self._coordinator.data.get("volume", 0.0)

    @property
    def is_volume_muted(self):
        return self._coordinator.data.get("muted", False)

    @property
    def source(self):
        return self._coordinator.data.get("source")

    @property
    def source_list(self):
        return list(self._coordinator.data.get("inputs", {})) +                    list(self._coordinator.data.get("channels", {})) +                    list(self._coordinator.data.get("apps", {}))

    @property
    def extra_state_attributes(self):
        return {
            "current_channel": self._coordinator.data.get("channel"),
            "current_app": self._coordinator.data.get("app"),
            "current_input": self._coordinator.data.get("input"),
            "host": self._coordinator.host,
        }

    # --- Commands ---
    async def async_turn_on(self):
        await self._coordinator.send_rc_key(RC_KEY_POWER_ON)

    async def async_turn_off(self):
        await self._coordinator.send_rc_key(RC_KEY_POWER_OFF)

    async def async_volume_up(self):
        await self._coordinator.send_rc_key(RC_KEY_VOL_UP)

    async def async_volume_down(self):
        await self._coordinator.send_rc_key(RC_KEY_VOL_DOWN)

    async def async_set_volume_level(self, volume: float):
        loewe_val = max(0, min(999999, int(volume * 999999)))
        await self._coordinator._soap_request("SetVolume", f"<Value>{loewe_val}</Value>")

    async def async_mute_volume(self, mute: bool):
        await self._coordinator._soap_request("SetMute", f"<Value>{1 if mute else 0}</Value>")

    async def async_select_source(self, source: str):
        if source in self._coordinator._input_map:
            uuid = self._coordinator._input_map[source]
            await self._coordinator._soap_request("ZapToMedia", f"<Uuid>{uuid}</Uuid>")
        elif source in self._coordinator._channel_map:
            uuid = self._coordinator._channel_map[source]
            await self._coordinator._soap_request("ZapToMedia", f"<Uuid>{uuid}</Uuid>")
        elif source in self._coordinator._app_map:
            uuid = self._coordinator._app_map[source]
            await self._coordinator._soap_request("ZapToApplication", f"<Uuid>{uuid}</Uuid>")

"""Config flow for Loewe TV integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_RESOURCE_PATH,
    CONF_CLIENT_ID,
    CONF_FCID,
    CONF_TV_MAC,
    CONF_CLIENT_MAC,
    DEFAULT_RESOURCE_PATH,
)
from .coordinator import LoeweTVCoordinator
from .network import async_get_device_mac
from .parsers import device_mac

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_RESOURCE_PATH, default=DEFAULT_RESOURCE_PATH): str,
    }
)


class LoeweTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Loewe TV Remote API."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        host = user_input[CONF_HOST].strip()
        resource_path = (
            user_input.get(CONF_RESOURCE_PATH, DEFAULT_RESOURCE_PATH) or DEFAULT_RESOURCE_PATH
        ).strip()

        # Avoid duplicates before pairing; the TV MAC (checked below) is the real unique ID
        self._async_abort_entries_match({CONF_HOST: host})

        coordinator = LoeweTVCoordinator(self.hass, host=host, resource_path=resource_path)

        result: dict[str, Any] | None = None
        device_info: dict[str, Any] = {}
        try:
            for attempt in range(1, 7):
                _LOGGER.debug("RequestAccess attempt %s/6 (host=%s)", attempt, host)
                result = await coordinator.async_request_access("HomeAssistant")

                if result and result.get("State", "").lower() == "accepted":
                    if result.get("ClientId") and result.get("fcid"):
                        break

                await asyncio.sleep(1)

            # Read device data over the session we just paired (needed for the TV MAC)
            if coordinator.client_id and coordinator.fcid:
                device_info = await coordinator.async_get_device_data()

        except Exception as err:
            _LOGGER.error("RequestAccess failed: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        if not result:
            _LOGGER.error("RequestAccess returned no result after all attempts")
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        if result.get("State", "").lower() != "accepted":
            _LOGGER.error("RequestAccess never reached accepted state: %s", result)
            errors["base"] = "pairing_not_accepted"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        # ----------------------------
        # Build the initial config data
        # ----------------------------
        # Use the coordinator's IDs: GetDeviceData may have re-paired the session
        data = {
            CONF_HOST: host,
            CONF_RESOURCE_PATH: resource_path,
            CONF_CLIENT_ID: coordinator.client_id or result.get("ClientId"),
            CONF_FCID: coordinator.fcid or result.get("fcid"),
        }

        # ----------------------------
        # Capture the TV's MAC address (used for Wake-on-LAN)
        # ----------------------------
        if tv_mac := device_mac(device_info):
            data[CONF_TV_MAC] = tv_mac
            _LOGGER.debug("Captured TV MAC during config flow: %s", tv_mac)
            # Same TV on a new IP address: update the existing entry instead of adding another
            await self.async_set_unique_id(format_mac(tv_mac))
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        else:
            _LOGGER.warning("Could not read TV MAC from GetDeviceData; it will be filled in on a later poll")
            await self.async_set_unique_id(f"{DOMAIN}-{host}")
            self._abort_if_unique_id_configured()

        # ----------------------------
        # Capture the HA client's MAC address (sent as DeviceUUID when pairing)
        # ----------------------------
        data[CONF_CLIENT_MAC] = await async_get_device_mac(self.hass)
        _LOGGER.debug("Captured HA Client MAC during config flow: %s", data[CONF_CLIENT_MAC])

        # ----------------------------
        # Final logging and entry creation
        # ----------------------------
        _LOGGER.debug(
            "Pairing success: ClientId=%s TV_MAC=%s CLIENT_MAC=%s State=%s",
            data.get(CONF_CLIENT_ID),
            data.get(CONF_TV_MAC),
            data.get(CONF_CLIENT_MAC),
            result.get("State"),
        )

        return self.async_create_entry(title=f"Loewe TV ({host})", data=data)

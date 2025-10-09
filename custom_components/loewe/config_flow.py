"""Config flow for Loewe TV integration."""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_RESOURCE_PATH,
    CONF_CLIENT_ID,
    CONF_DEVICE_UUID,
    CONF_FCID,
    CONF_TV_MAC,
    DEFAULT_RESOURCE_PATH,
)
from .coordinator import LoeweTVCoordinator

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

        # Avoid duplicates
        await self.async_set_unique_id(f"{DOMAIN}-{host}")
        self._abort_if_unique_id_configured()

        coordinator = LoeweTVCoordinator(self.hass, host=host, resource_path=resource_path)

        result: dict[str, Any] | None = None
        try:
            for attempt in range(1, 7):
                _LOGGER.debug("RequestAccess attempt %s/6 (host=%s)", attempt, host)
                result = await coordinator.async_request_access("HomeAssistant")

                if result and result.get("State", "").lower() == "accepted":
                    if result.get("ClientId") and result.get("fcid"):
                        break

                await asyncio.sleep(1)

        except Exception as err:
            _LOGGER.error("RequestAccess failed: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)
        finally:
            await coordinator.async_close()

        if not result:
            _LOGGER.error("RequestAccess returned no result after all attempts")
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        if result.get("State", "").lower() != "accepted":
            _LOGGER.error("RequestAccess never reached accepted state: %s", result)
            errors["base"] = "pairing_not_accepted"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        data = {
            CONF_HOST: host,
            CONF_RESOURCE_PATH: resource_path,
            CONF_CLIENT_ID: result.get("ClientId"),
            CONF_DEVICE_UUID: coordinator.device_uuid,  # actually MAC in this design
            CONF_FCID: result.get("fcid"),
        }

        # Fetch and persist the TV's MAC so WOL works
        try:
            device_info = await coordinator.async_get_device_data()
            mac = device_info.get("MAC-Address-LAN") or device_info.get("MAC-Address")
            if mac:
                data[CONF_TV_MAC] = mac.strip()
                _LOGGER.debug("Captured TV MAC during config flow: %s", data[CONF_TV_MAC])
        except Exception as e:
            _LOGGER.warning("Could not parse MAC from GetDeviceData: %s", e)

        _LOGGER.debug(
            "Pairing success: ClientId=%s DeviceUUID=%s State=%s",
            data.get(CONF_CLIENT_ID),
            data.get(CONF_DEVICE_UUID),
            result.get("State"),
        )

        return self.async_create_entry(title=f"Loewe TV ({host})", data=data)

"""Config flow for Loewe TV integration."""
from __future__ import annotations

from typing import Any
import voluptuous as vol
import logging
import asyncio

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_RESOURCE_PATH,
    CONF_CLIENT_ID,
    CONF_DEVICE_UUID,
    CONF_FCID,   # <-- add this
    DEFAULT_RESOURCE_PATH,
)

from .coordinator import LoeweTVCoordinator, SOAP_ENDPOINTS

_LOGGER = logging.getLogger(__name__)


class LoeweTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Loewe TV Remote API."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Optional(CONF_RESOURCE_PATH, default=DEFAULT_RESOURCE_PATH): str,
                    }
                ),
                errors=errors,
            )

        host = user_input[CONF_HOST].strip()
        resource_path = (user_input.get(CONF_RESOURCE_PATH, DEFAULT_RESOURCE_PATH) or DEFAULT_RESOURCE_PATH).strip()

        # Avoid duplicates
        await self.async_set_unique_id(f"{DOMAIN}-{host}")
        self._abort_if_unique_id_configured()

        coordinator = LoeweTVCoordinator(self.hass, host=host, resource_path=resource_path)

        result: dict[str, Any] | None = None
        try:
            # Retry RequestAccess until accepted
            url = SOAP_ENDPOINTS["RequestAccess"]["url"].format(host=host)
            for attempt in range(1, 7):
                _LOGGER.debug("RequestAccess attempt %s/6 (url=%s)", attempt, url)
                result = await coordinator.async_request_access("HomeAssistant")

                if result:
                    _LOGGER.debug("RequestAccess attempt %s parsed result: %s", attempt, result)
                    if result.get("ClientId") and result.get("fcid"):
                        return self.async_create_entry(
                            title=f"Loewe TV ({host})",
                            data={
                                "host": host,
                                "resource_path": resource_path,
                                "client_id": result["ClientId"],
                                "device_uuid": coordinator.device_uuid,
                                "fcid": result["fcid"],
                            },
                        )
                else:
                    # Log the raw text that came back, if any
                    if coordinator._last_raw_response:
                        _LOGGER.debug("RequestAccess attempt %s raw response:\n%s",
                                      attempt, coordinator._last_raw_response)
                    else:
                        _LOGGER.debug("RequestAccess attempt %s returned no response", attempt)

                await asyncio.sleep(2)

        except Exception as err:
            _LOGGER.error("RequestAccess failed: %s", err, exc_info=True)
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=host): str,
                        vol.Optional(CONF_RESOURCE_PATH, default=resource_path): str,
                    }
                ),
                errors=errors,
            )
        finally:
            await coordinator.async_close()

        if not result:
            _LOGGER.error("RequestAccess returned no result after all attempts")
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=host): str,
                        vol.Optional(CONF_RESOURCE_PATH, default=resource_path): str,
                    }
                ),
                errors=errors,
            )

        if result.get("State") != "accepted":
            _LOGGER.error("RequestAccess never reached accepted state: %s", result)
            errors["base"] = "pairing_not_accepted"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=host): str,
                        vol.Optional(CONF_RESOURCE_PATH, default=resource_path): str,
                    }
                ),
                errors=errors,
            )

        client_id = result.get("ClientId")
        device_uuid = coordinator.device_uuid
        fcid = result.get("fcid")

        if not client_id:
            _LOGGER.warning("RequestAccess response did not include a ClientId. Result=%s", result)
        if not fcid:
            _LOGGER.warning("RequestAccess response did not include an fcid. Result=%s", result)

        data = {
            CONF_HOST: host,
            CONF_RESOURCE_PATH: resource_path,
            CONF_CLIENT_ID: client_id,
            CONF_DEVICE_UUID: device_uuid,
            CONF_FCID: fcid,
        }

        _LOGGER.debug(
            "Pairing success: ClientId=%s DeviceUUID=%s State=%s",
            client_id,
            device_uuid,
            result.get("State"),
        )

        return self.async_create_entry(title=f"Loewe TV ({host})", data=data)


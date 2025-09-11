from __future__ import annotations
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
    DEFAULT_RESOURCE_PATH,
)
from .coordinator import LoeweTVCoordinator


class LoeweTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Loewe TV Remote API."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is None:
            # Show initial form
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

        try:
            ok = await coordinator.async_test_connection()
            info = None
        finally:
            await coordinator.async_close()

        if not ok:
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

        data = {
            CONF_HOST: host,
            CONF_RESOURCE_PATH: resource_path,
        }

        # Store client_id if we obtained one
        if coordinator.client_id:
            data[CONF_CLIENT_ID] = coordinator.client_id

        # Store device UUID if available
        if isinstance(info, dict):
            dev_uuid = info.get("DeviceUUID") or info.get("DeviceId")
            if dev_uuid:
                data[CONF_DEVICE_UUID] = dev_uuid

        return self.async_create_entry(title=f"Loewe TV ({host})", data=data)


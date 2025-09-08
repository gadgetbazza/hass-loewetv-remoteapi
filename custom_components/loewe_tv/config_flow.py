from __future__ import annotations
import logging
from typing import Any, Dict, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_RESOURCE_PATH,
    DEFAULT_RESOURCE_PATH,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import LoeweTVCoordinator

_LOGGER = logging.getLogger(__name__)


def _schema_user(defaults: Optional[Dict[str, Any]] = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_RESOURCE_PATH, default=defaults.get(CONF_RESOURCE_PATH, DEFAULT_RESOURCE_PATH)): str,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            resource_path = user_input.get(CONF_RESOURCE_PATH) or DEFAULT_RESOURCE_PATH

            coordinator = LoeweTVCoordinator(self.hass, host, resource_path)
            ok, dev = await coordinator.async_test_connection()
            if ok:
                access = await coordinator.async_request_access()
                client_id = access.get("ClientId") if access else None
                await self.async_set_unique_id(f"{host}-{resource_path}")
                self._abort_if_unique_id_configured()
                data = {
                    "host": host,
                    "resource_path": resource_path,
                }
                if client_id:
                    data["client_id"] = client_id
                return self.async_create_entry(title=dev.get("NetworkHostName", "Loewe TV"), data=data)
            errors["base"] = "cannot_connect"

        return self.async_show_form(step_id="user", data_schema=_schema_user(user_input), errors=errors)

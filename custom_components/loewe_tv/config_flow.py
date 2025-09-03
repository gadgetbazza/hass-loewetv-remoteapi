import voluptuous as vol
import aiohttp
import xml.etree.ElementTree as ET

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .const import DOMAIN, DEFAULT_NAME

SOAP_URL = "http://{host}:905/LOEWE/RemoteService"
SOAP_NS = "urn:loewe-remote:service:Remote:1"


async def _test_connection(host: str) -> bool:
    """Try a quick SOAP call to test connectivity."""
    url = SOAP_URL.format(host=host)
    headers = {"Content-Type": "text/xml; charset=utf-8"}
    envelope = f"""
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body>
        <m:GetMute xmlns:m="{SOAP_NS}" />
      </s:Body>
    </s:Envelope>
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=envelope, headers=headers, timeout=5) as resp:
                if resp.status != 200:
                    return False
                text = await resp.text()
                ET.fromstring(text)  # minimal parse
                return True
    except Exception:
        return False


class LoeweTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Loewe TV."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            name = user_input[CONF_NAME]

            ok = await _test_connection(host)
            if not ok:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_NAME: name,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

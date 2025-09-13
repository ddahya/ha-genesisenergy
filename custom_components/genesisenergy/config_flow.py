# custom_components/genesisenergy/config_flow.py

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

from .api import GenesisEnergyApi
from .const import DOMAIN, INTEGRATION_NAME
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)

class GenesisEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Genesis Energy."""
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            api = GenesisEnergyApi(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
            
            try:
                await api._ensure_valid_token()
                _LOGGER.info("Config flow: Authentication successful.")
                return self.async_create_entry(title=INTEGRATION_NAME, data=user_input)
            
            except InvalidAuth as e:
                _LOGGER.warning(f"Config flow failed with InvalidAuth: {e}")
                errors["base"] = "invalid_auth"
            except CannotConnect as e:
                _LOGGER.warning(f"Config flow failed with CannotConnect: {e}")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Config flow failed with an unexpected exception")
                errors["base"] = "unknown"
            finally:
                await api.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }),
            errors=errors,
        )
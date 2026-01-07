# custom_components/genesisenergy/config_flow.py

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

from .api import GenesisEnergyApi
from homeassistant.core import callback
from .const import DOMAIN, INTEGRATION_NAME, CONF_ENABLE_AUTO_CORRECTION
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)

class GenesisEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Genesis Energy."""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GenesisEnergyOptionsFlow(config_entry)

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

class GenesisEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the Genesis Energy integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # NOTE: In recent HA versions, self.config_entry is a property and cannot be set.
        # We simply pass here; the property will work automatically in async_step_init.
        pass

    async def async_step_init(self, user_input: dict | None = None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Default is False (Disabled)
        current_value = self.config_entry.options.get(CONF_ENABLE_AUTO_CORRECTION, False)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_AUTO_CORRECTION, default=current_value): bool,
            }),
        )
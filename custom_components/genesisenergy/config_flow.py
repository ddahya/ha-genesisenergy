# custom_components/genesisenergy/config_flow.py

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

from .api import GenesisEnergyApi
from homeassistant.core import callback
from .const import DOMAIN, INTEGRATION_NAME, CONF_ENABLE_AUTO_CORRECTION, CONF_REFRESH_TOKEN, CONF_VERIFICATION_CODE
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)

class GenesisEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Genesis Energy with PKCE & 90-day tokens."""
    VERSION = 1

    def __init__(self):
        self._email: str | None = None
        self._password: str | None = None
        self._api: GenesisEnergyApi | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GenesisEnergyOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None):
        """Step 1: Enter email and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().lower()
            self._password = user_input[CONF_PASSWORD].strip()

            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()

            self._api = GenesisEnergyApi(self._email, self._password)

            try:
                res = await self._api.async_start_login()
                if res == "MFA_REQUIRED":
                    return await self.async_step_mfa()
                
                # Direct PKCE login succeeded
                _LOGGER.info("Config flow: PKCE direct authentication successful.")
                return self.async_create_entry(
                    title=INTEGRATION_NAME,
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_REFRESH_TOKEN: self._api.refresh_token,
                    }
                )

            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception("Config flow step user exception: %s", e)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }),
            errors=errors,
        )

    async def async_step_mfa(self, user_input: dict | None = None):
        """Step 2: (Fallback) Enter 6-digit email code if ever prompted."""
        errors: dict[str, str] = {}
        if user_input is not None and self._api:
            code = user_input[CONF_VERIFICATION_CODE].strip()
            try:
                success = await self._api.async_submit_mfa_code(code)
                if success:
                    return self.async_create_entry(
                        title=INTEGRATION_NAME,
                        data={
                            CONF_EMAIL: self._email,
                            CONF_PASSWORD: self._password,
                            CONF_REFRESH_TOKEN: self._api.refresh_token,
                        }
                    )
                errors["base"] = "invalid_auth"

            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.exception("MFA verification error: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({
                vol.Required(CONF_VERIFICATION_CODE): cv.string,
            }),
            description_placeholders={"email": self._email or "your email"},
            errors=errors,
        )

class GenesisEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the Genesis Energy integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        pass

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_value = self.config_entry.options.get(CONF_ENABLE_AUTO_CORRECTION, False)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_AUTO_CORRECTION, default=current_value): bool,
            }),
        )
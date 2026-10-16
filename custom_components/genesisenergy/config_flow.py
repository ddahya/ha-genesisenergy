import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .api import GenesisEnergyApi
from .const import (
    DOMAIN,
    INTEGRATION_NAME,
    CONF_ENABLE_AUTO_CORRECTION,
    CONF_POWERSHOUT_POLL_MINUTES,
    DEFAULT_POWERSHOUT_POLL_MINUTES,
    CONF_REFRESH_TOKEN,
    CONF_ACCESS_TOKEN,
    CONF_TOKEN_EXPIRY,
    CONF_VERIFICATION_CODE,
)
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)


class GenesisEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        self._api: GenesisEnergyApi | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GenesisEnergyOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().lower()
            self._password = user_input[CONF_PASSWORD].strip()

            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()

            if self._api:
                await self._api.close()
            self._api = GenesisEnergyApi(self._email, self._password)

            try:
                res = await self._api.async_start_login()
                if res == "MFA_REQUIRED":
                    return await self.async_step_mfa()

                _LOGGER.info("Config flow: PKCE direct authentication successful.")
                entry_data = {
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_REFRESH_TOKEN: self._api.refresh_token,
                    CONF_ACCESS_TOKEN: self._api.access_token,
                    CONF_TOKEN_EXPIRY: self._api.token_expiry,
                }
                await self._api.close()
                return self.async_create_entry(title=INTEGRATION_NAME, data=entry_data)

            except InvalidAuth:
                await self._api.close()
                errors["base"] = "invalid_auth"
            except CannotConnect:
                await self._api.close()
                errors["base"] = "cannot_connect"
            except Exception as e:
                await self._api.close()
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
        errors: dict[str, str] = {}
        if user_input is not None and self._api:
            code = user_input[CONF_VERIFICATION_CODE].strip()
            try:
                success = await self._api.async_submit_mfa_code(code)
                if success:
                    entry_data = {
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_REFRESH_TOKEN: self._api.refresh_token,
                        CONF_ACCESS_TOKEN: self._api.access_token,
                        CONF_TOKEN_EXPIRY: self._api.token_expiry,
                    }
                    await self._api.close()
                    return self.async_create_entry(title=INTEGRATION_NAME, data=entry_data)
                errors["base"] = "invalid_auth"

            except InvalidAuth:
                await self._api.close()
                errors["base"] = "invalid_auth"
            except Exception as e:
                await self._api.close()
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
    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        auto_corr = self.config_entry.options.get(CONF_ENABLE_AUTO_CORRECTION, False)
        poll_mins = self.config_entry.options.get(CONF_POWERSHOUT_POLL_MINUTES, DEFAULT_POWERSHOUT_POLL_MINUTES)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_AUTO_CORRECTION, default=auto_corr): bool,
                vol.Optional(CONF_POWERSHOUT_POLL_MINUTES, default=poll_mins): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=60)
                ),
            }),
        )
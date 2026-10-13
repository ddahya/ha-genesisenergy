# custom_components/genesisenergy/exceptions.py

try:
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError:
    class HomeAssistantError(Exception):
        """Fallback base when Home Assistant is not installed."""

class GenesisEnergyError(HomeAssistantError):
    """Base class for Genesis Energy integration errors."""

class CannotConnect(GenesisEnergyError):
    """Error to indicate we cannot connect."""

class InvalidAuth(GenesisEnergyError):
    """Error to indicate there is invalid auth."""

class ApiError(GenesisEnergyError):
    """Error returned by the Genesis API."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_type: str | None = None,
        response_data: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.response_data = response_data

class PowerShoutValidationError(GenesisEnergyError):
    """Error raised for an invalid Power Shout selection."""

class PowerShoutUnavailableError(GenesisEnergyError):
    """Error raised when Power Shout cannot be used."""
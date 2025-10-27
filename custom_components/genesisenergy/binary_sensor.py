# custom_components/genesisenergy/binary_sensor.py
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    DATA_API_POWERSHOUT_BALANCE,
)
from .coordinator import GenesisEnergyDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensor entities."""
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BinarySensorEntity] = []

    if coordinator.data.get(DATA_API_POWERSHOUT_BALANCE) is not None:
        entities.append(PowerShoutOffersAvailableBinarySensor(coordinator))

    async_add_entities(entities)


class PowerShoutOffersAvailableBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that indicates if any Power Shout offers are available."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Offers Available"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_powershout_offers_available"
        self._attr_icon = "mdi:gift-outline"

    @property
    def is_on(self) -> bool:
        """Return True if there are active offers."""
        data = self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE, {})
        count = data.get("active_offers_count", 0)
        return count > 0

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the raw balance data for debugging and dashboards."""
        return self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE, {})

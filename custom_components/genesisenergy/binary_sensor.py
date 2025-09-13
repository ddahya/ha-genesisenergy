# custom_components/genesisenergy/binary_sensor.py
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import STATE_UNKNOWN

from .const import DOMAIN, LOGGER, UPDATE_TRIGGERS, SERVICE_FORCE_UPDATE_ELECTRICITY, SERVICE_FORCE_UPDATE_GAS
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .model import GenesisEnergyBinarySensorEntityDescription

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    entities = [GenesisEnergyUpdaterBinarySensor(coordinator, desc) for desc in UPDATE_TRIGGERS]
    async_add_entities(entities)

class GenesisEnergyUpdaterBinarySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    entity_description: GenesisEnergyBinarySensorEntityDescription

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, description: GenesisEnergyBinarySensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = coordinator.device_info

        fuel_type = "electricity" if "electricity" in description.key else "gas"

        self._attr_name = f"Force Update {fuel_type.capitalize()} Statistics"

        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_force_update_{fuel_type}"
        
        self._attr_is_on = False
        LOGGER.info(f"Initialized BinarySensor '{self.name}' (UID: {self.unique_id})")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.state == STATE_UNKNOWN:
            self._attr_is_on = False
            self.async_write_ha_state()

        service_name = None
        if "electricity" in self.entity_description.key: 
            service_name = SERVICE_FORCE_UPDATE_ELECTRICITY
        elif "gas" in self.entity_description.key: 
            service_name = SERVICE_FORCE_UPDATE_GAS

        if service_name:
            self.platform.async_register_entity_service(
                name=service_name, schema={}, func="async_trigger_service"
            )
            LOGGER.info(f"Successfully registered service '{service_name}' for {self.entity_id}")

    async def async_trigger_service(self) -> None:
        LOGGER.info("Service triggered for %s", self.entity_id)
        self._attr_is_on = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
        self._attr_is_on = False
        self.async_write_ha_state()
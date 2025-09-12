# custom_components/genesisenergy/sensor.py
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Mapping
import json

from homeassistant.components.sensor import (
    SensorEntity, SensorEntityDescription, SensorStateClass, SensorDeviceClass
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics, get_last_statistics

from .const import (
    DOMAIN, LOGGER, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE, DATA_API_POWERSHOUT_INFO,
    DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS, DATA_API_POWERSHOUT_OFFERS,
    DATA_API_POWERSHOUT_EXPIRING, DATA_API_BILLING_PLANS, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS,
    STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST,
    STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST, SENSOR_KEY_POWERSHOUT_ELIGIBLE,
    SENSOR_KEY_POWERSHOUT_BALANCE, SENSOR_KEY_ACCOUNT_DETAILS,
    DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST,
    DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
    SENSOR_KEY_BILL_ELEC_USED, SENSOR_KEY_BILL_GAS_USED, SENSOR_KEY_BILL_TOTAL_USED,
    SENSOR_KEY_BILL_ESTIMATED_TOTAL, SENSOR_KEY_BILL_ESTIMATED_FUTURE,
    DATA_API_GENERATION_MIX, SENSOR_KEY_GENERATION_MIX, DATA_API_EV_PLAN_USAGE,
    SENSOR_KEY_EV_DAY_USAGE, SENSOR_KEY_EV_DAY_COST, SENSOR_KEY_EV_NIGHT_USAGE,
    SENSOR_KEY_EV_NIGHT_COST, SENSOR_KEY_EV_TOTAL_SAVINGS,
    DATA_API_ELECTRICITY_FORECAST, SENSOR_KEY_FORECAST_USAGE, SENSOR_KEY_FORECAST_COST,
    DATA_API_USAGE_BREAKDOWN, SENSOR_KEY_BREAKDOWN_APPLIANCES, SENSOR_KEY_BREAKDOWN_ELECTRONICS,
    SENSOR_KEY_BREAKDOWN_LIGHTING, SENSOR_KEY_BREAKDOWN_OTHER,
    DATA_API_LPG_ORDER_STATUS, DATA_API_LPG_DELIVERY_HISTORY,
    SENSOR_KEY_LPG_ORDER_STATUS, SENSOR_KEY_LPG_DELIVERY_HISTORY
)
from .coordinator import GenesisEnergyDataUpdateCoordinator

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    
    has_electricity, has_gas = False, False
    billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
    if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
        for site in billing_plans_data["billingAccountSites"]:
            if isinstance(site.get("supplyPoints"), list):
                for supply_point in site["supplyPoints"]:
                    if isinstance(supply_point, dict):
                        supply_type = supply_point.get("supplyType")
                        if supply_type == "electricity": has_electricity = True
                        elif supply_type == "naturalGas": has_gas = True
    
    if has_electricity:
        entities.append(GenesisEnergyStatisticsSensor(coordinator, "Electricity"))
        if coordinator.data.get(DATA_API_GENERATION_MIX):
            entities.append(GenerationMixSensor(coordinator))
        if coordinator.data.get(DATA_API_ELECTRICITY_FORECAST):
            LOGGER.info("Electricity forecast data found. Adding forecast sensors.")
            entities.extend([
                ForecastUsageSensor(coordinator),
                ForecastCostSensor(coordinator),
            ])
        if coordinator.data.get(DATA_API_USAGE_BREAKDOWN):
            LOGGER.info("Usage breakdown data found. Adding breakdown sensors.")
            entities.extend([
                UsageBreakdownSensor(coordinator, "Appliances", SENSOR_KEY_BREAKDOWN_APPLIANCES),
                UsageBreakdownSensor(coordinator, "Electronics", SENSOR_KEY_BREAKDOWN_ELECTRONICS),
                UsageBreakdownSensor(coordinator, "Lighting", SENSOR_KEY_BREAKDOWN_LIGHTING),
                UsageBreakdownSensor(coordinator, "Other", SENSOR_KEY_BREAKDOWN_OTHER),
            ])

    if lpg_status_data := coordinator.data.get(DATA_API_LPG_ORDER_STATUS):
        LOGGER.info("LPG data found. Adding LPG sensors.")
        lpg_history_data = coordinator.data.get(DATA_API_LPG_DELIVERY_HISTORY, [])
        
        for site in lpg_status_data.get("billingAccountSites", []):
            for supply_point in site.get("supplyPoints", []):
                sa_id = supply_point.get("supplyAgreementId")
                
                matching_history = next((h for h in lpg_history_data if isinstance(h, dict) and h.get("deliveryHistory") and h.get("deliveryHistory")[0].get("supplyAgreementId") == sa_id), None)

                entities.append(LpgOrderStatusSensor(coordinator, supply_point))
                if matching_history:
                    entities.append(LpgDeliveryHistorySensor(coordinator, supply_point, matching_history))

    if has_gas:
        entities.append(GenesisEnergyStatisticsSensor(coordinator, "Gas"))
        
    if coordinator.data.get(DATA_API_EV_PLAN_USAGE):
        LOGGER.info("EV Plan data found. Adding EV plan sensors.")
        entities.extend([
            EVDayUsageSensor(coordinator),
            EVDayCostSensor(coordinator),
            EVNightUsageSensor(coordinator),
            EVNightCostSensor(coordinator),
            EVTotalSavingsSensor(coordinator)
        ])

    entities.extend([
        PowerShoutEligibilitySensor(coordinator),
        PowerShoutBalanceSensor(coordinator),
        GenesisEnergyAccountSensor(coordinator)
    ])
    
    if coordinator.data.get(DATA_API_WIDGET_SIDEKICK):
        LOGGER.info("Sidekick widget data found. Adding billing sensors.")
        entities.append(TotalUsedSensor(coordinator))
        entities.append(EstimatedTotalSensor(coordinator))
        entities.append(EstimatedFutureUseSensor(coordinator))
        if has_electricity:
            entities.append(ElectricityUsedSensor(coordinator))
        if has_gas:
            entities.append(GasUsedSensor(coordinator))
    else:
        LOGGER.warning("Sidekick widget data not found. Skipping billing sensors.")
    
    async_add_entities(entities)


class GenesisEnergyStatisticsSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True; _attr_should_poll = False
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, fuel_type: str):
        super().__init__(coordinator)
        self._fuel_type = fuel_type
        self._data_key = DATA_API_ELECTRICITY_USAGE if fuel_type == "Electricity" else DATA_API_GAS_USAGE
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(key=f"{fuel_type.lower()}_statistics_updater", name=f"{fuel_type.capitalize()} Statistics Updater", icon="mdi:chart-line" if self._fuel_type == "Electricity" else "mdi:chart-bell-curve-cumulative")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        if self._fuel_type == "Electricity":
            self._consumption_statistic_id, self._cost_statistic_id = STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST
        else:
            self._consumption_statistic_id, self._cost_statistic_id = STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST
        self._consumption_statistic_name, self._cost_statistic_name = f"Genesis {fuel_type} Consumption Daily", f"Genesis {fuel_type} Cost Daily"
        self._unit, self._currency, self._processed_data_hash = "kWh", "NZD", None
        self._utc_tz = ZoneInfo("UTC")

    @property
    def native_value(self) -> str:
        if self.coordinator.data and (api_data := self.coordinator.data.get(self._data_key)) and api_data.get("usage"): return "ok"
        elif self.coordinator.last_update_success: return "no_data"
        return "error"

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success: self.async_write_ha_state(); return
        if api_data := self.coordinator.data.get(self._data_key):
            if raw_usage_list := api_data.get('usage'):
                if isinstance(raw_usage_list, list) and raw_usage_list:
                    current_hash = (len(raw_usage_list), raw_usage_list[0].get('startDate'), raw_usage_list[-1].get('startDate'))
                    if self._processed_data_hash != current_hash:
                        self.hass.async_create_task(self.async_process_statistics_data(list(raw_usage_list)))
                        self._processed_data_hash = current_hash
        self.async_write_ha_state()

    async def async_process_statistics_data(self, usage_data: list):
        if not usage_data: return
        try:
            sorted_usage_data = sorted(usage_data, key=lambda x: x['startDate'])
        except (KeyError, TypeError): return
        
        async def _process_one_statistic(statistic_id: str, stat_name: str, unit: str, value_key: str):
            last_stat_list = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
            )
            last_stat = last_stat_list.get(statistic_id, [{}])[0]
            running_sum = float(last_stat.get('sum', 0.0))
            last_ts = last_stat.get('start', 0)
            stats_to_add = []
            for entry in sorted_usage_data:
                try:
                    value = float(entry[value_key])
                    start_dt_utc = datetime.fromisoformat(entry['startDate']).astimezone(self._utc_tz)
                    start_ts = start_dt_utc.timestamp()
                except (KeyError, ValueError, TypeError): continue
                if start_ts > last_ts:
                    running_sum += value
                    stats_to_add.append(StatisticData(start=start_dt_utc, state=round(value, 2), sum=round(running_sum, 2)))
            if stats_to_add:
                meta = StatisticMetaData(has_mean=False, has_sum=True, name=stat_name, source=DOMAIN, statistic_id=statistic_id, unit_of_measurement=unit)
                async_add_external_statistics(self.hass, meta, stats_to_add)
                LOGGER.info(f"Imported {len(stats_to_add)} new '{stat_name}' statistics.")
            else:
                 LOGGER.info(f"No new data to import for '{stat_name}' (all data was older or the same as existing).")
        
        await _process_one_statistic(self._consumption_statistic_id, self._consumption_statistic_name, self._unit, 'kw')
        await _process_one_statistic(self._cost_statistic_id, self._cost_statistic_name, self._currency, 'costNZD')


class GenerationMixSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:leaf"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key=SENSOR_KEY_GENERATION_MIX,
            name="Grid Generation Eco-Friendly",
        )
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        self._nz_tz = ZoneInfo('Pacific/Auckland')

    @property
    def native_value(self) -> float | None:
        gen_mix_data = self.coordinator.data.get(DATA_API_GENERATION_MIX)
        if not gen_mix_data or not isinstance(gen_mix_data, list):
            return None

        now_nz = dt_util.now(self._nz_tz)
        today_str = now_nz.strftime('%Y-%m-%d')
        current_hour = now_nz.hour

        for day_data in gen_mix_data:
            if day_data.get("Day") == today_str:
                for hour_data in day_data.get("HourlyBreakdown", []):
                    if hour_data.get("Hour") == current_hour:
                        eco_percentage = hour_data.get("EcoFriendlyPercentage")
                        if eco_percentage is not None:
                            return float(eco_percentage)
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if gen_mix_data := self.coordinator.data.get(DATA_API_GENERATION_MIX):
            return {"forecast": gen_mix_data}
        return None

class GenesisEVPlanSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = "Data from latest full day"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, desc: SensorEntityDescription):
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{desc.key}"
    
    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.get(DATA_API_EV_PLAN_USAGE) is not None

    @property
    def _latest_day_data(self) -> dict | None:
        ev_data = self.coordinator.data.get(DATA_API_EV_PLAN_USAGE)
        if not ev_data or not isinstance(ev_data, list):
            return None
        return ev_data[-1]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if data := self._latest_day_data:
            if reading_date := data.get("date"):
                try:
                    dt_obj = datetime.fromisoformat(reading_date)
                    return {"reading_date": dt_obj.strftime("%A, %d %B %Y")}
                except (ValueError, TypeError):
                    return {"reading_date": reading_date}
        return None

class EVDayUsageSensor(GenesisEVPlanSensor):
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_EV_DAY_USAGE, name="EV Plan Day Usage")
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        if data := self._latest_day_data:
            return data.get("kWhDay")
        return None

class EVDayCostSensor(GenesisEVPlanSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_EV_DAY_COST, name="EV Plan Day Cost")
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        if data := self._latest_day_data:
            try:
                return float(data.get("usageCostDay"))
            except (ValueError, TypeError):
                return None
        return None

class EVNightUsageSensor(GenesisEVPlanSensor):
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_EV_NIGHT_USAGE, name="EV Plan Night Usage")
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        if data := self._latest_day_data:
            return data.get("kWhNight")
        return None

class EVNightCostSensor(GenesisEVPlanSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_EV_NIGHT_COST, name="EV Plan Night Cost")
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        if data := self._latest_day_data:
            try:
                return float(data.get("usageCostNight"))
            except (ValueError, TypeError):
                return None
        return None

class EVTotalSavingsSensor(GenesisEVPlanSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:piggy-bank-outline"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_EV_TOTAL_SAVINGS, name="EV Plan Savings")
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        if data := self._latest_day_data:
            try:
                cost_with_day_rate = float(data.get("costWithDayRate"))
                actual_night_cost = float(data.get("usageCostNight"))
                return round(cost_with_day_rate - actual_night_cost, 2)
            except (ValueError, TypeError, KeyError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the date of the reading and the full history."""
        attrs = {}
        if data := self._latest_day_data:
            if reading_date := data.get("date"):
                try:
                    dt_obj = datetime.fromisoformat(reading_date)
                    attrs["reading_date"] = dt_obj.strftime("%A, %d %B %Y")
                except (ValueError, TypeError):
                    attrs["reading_date"] = reading_date
        
        if history := self.coordinator.data.get(DATA_API_EV_PLAN_USAGE):
            attrs["history"] = history
            
        return attrs if attrs else None

class ForecastSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = "Forecast data from Genesis Energy"
    
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, desc: SensorEntityDescription):
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{desc.key}"
    
    @property
    def available(self) -> bool:
        if not (forecast_data := self.coordinator.data.get(DATA_API_ELECTRICITY_FORECAST)):
            return False
        return "IcpForecasts" in forecast_data and forecast_data["IcpForecasts"] and "Forecast" in forecast_data["IcpForecasts"][0]

    @property
    def _today_forecast_data(self) -> dict | None:
        if not self.available:
            return None
        return self.coordinator.data[DATA_API_ELECTRICITY_FORECAST]["IcpForecasts"][0]["Forecast"][0]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not (today_data := self._today_forecast_data):
            return None
            
        attrs = {
            "prediction_low_kwh": today_data.get("PredictionLowInkWh"),
            "prediction_high_kwh": today_data.get("PredictionHighInkWh"),
            "prediction_low_cost": today_data.get("PredictionLowCost"),
            "prediction_high_cost": today_data.get("PredictionHighCost"),
            "daily_forecast": self.coordinator.data[DATA_API_ELECTRICITY_FORECAST]["IcpForecasts"][0]["Forecast"]
        }
        return attrs

class ForecastUsageSensor(ForecastSensor):
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_FORECAST_USAGE, name="Today's Forecast Usage")
        super().__init__(coordinator, description)
    
    @property
    def native_value(self) -> float | None:
        if data := self._today_forecast_data:
            return data.get("PredictionInkWh")
        return None

class ForecastCostSensor(ForecastSensor):
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_FORECAST_COST, name="Today's Forecast Cost")
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        if data := self._today_forecast_data:
            return data.get("PredictionCost")
        return None

class UsageBreakdownSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, category_name: str, key: str):
        super().__init__(coordinator)
        self._category_name = category_name
        self.entity_description = SensorEntityDescription(key=key, name=f"Usage Breakdown - {category_name}")
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"

    @property
    def _latest_breakdown_period(self) -> dict | None:
        breakdown_data = self.coordinator.data.get(DATA_API_USAGE_BREAKDOWN)
        if (
            not breakdown_data 
            or "electricity" not in breakdown_data 
            or not breakdown_data["electricity"].get("breakdowns")
        ):
            return None
        return breakdown_data["electricity"]["breakdowns"][0]

    @property
    def _category_data(self) -> dict | None:
        if breakdown := self._latest_breakdown_period:
            for category in breakdown.get("categories", []):
                if category.get("name") == self._category_name:
                    return category
        return None

    @property
    def native_value(self) -> float | None:
        if category_data := self._category_data:
            return category_data.get("kWh", {}).get("value")
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = {}
        if period_data := self._latest_breakdown_period:
            attrs["period"] = period_data.get("period")
        if category_data := self._category_data:
            attrs["percentage"] = category_data.get("kWh", {}).get("percentage")
            attrs["daily_average_kwh"] = category_data.get("kWh", {}).get("dailyAverageUsage")
        return attrs

class GenesisBillSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "NZD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:cash"
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, desc: SensorEntityDescription):
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{desc.key}"
    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data and self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK) is not None

class ElectricityUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_ELEC_USED, name="Genesis Bill - Electricity Used", state_class=SensorStateClass.TOTAL)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        for supply in sidekick_data.get('supplyTypesArea', {}).get('supplyTypes', []):
            if supply.get('type') == 'electricity':
                try: return float(supply.get('value'))
                except (ValueError, TypeError): return None
        return 0.0

class GasUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_GAS_USED, name="Genesis Bill - Gas Used", state_class=SensorStateClass.TOTAL)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        for supply in sidekick_data.get('supplyTypesArea', {}).get('supplyTypes', []):
            if supply.get('type') == 'naturalGas':
                try: return float(supply.get('value'))
                except (ValueError, TypeError): return None
        return 0.0

class TotalUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_TOTAL_USED, name="Genesis Bill - Total Used", state_class=SensorStateClass.TOTAL)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        if (value := sidekick_data.get('titleArea', {}).get('value')) is not None:
            try: return float(value)
            except (ValueError, TypeError): return None
        return None

class EstimatedTotalSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_TOTAL, name="Genesis Bill - Estimated Total", state_class=None)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        title = sidekick_data.get('billArea', {}).get('title')
        if title and '$' in title:
            try: return float(title.split('$')[1])
            except (ValueError, IndexError): return None
        return None

class EstimatedFutureUseSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_FUTURE, name="Genesis Bill - Estimated Future Use", state_class=None)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        estimated_val, used_val = 0.0, 0.0
        title = sidekick_data.get('billArea', {}).get('title')
        if title and '$' in title:
            try: estimated_val = float(title.split('$')[1])
            except (ValueError, IndexError): pass
        if (value := sidekick_data.get('titleArea', {}).get('value')) is not None:
            try: used_val = float(value)
            except (ValueError, TypeError): pass
        future_use = estimated_val - used_val
        return round(future_use, 2) if future_use >= 0 else 0.0

class PowerShoutEligibilitySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator); self._attr_device_info = coordinator.device_info; self.entity_description = SensorEntityDescription(key=SENSOR_KEY_POWERSHOUT_ELIGIBLE, name="Power Shout Eligible", icon="mdi:lightning-bolt-outline"); self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self):
        if ps_info := self.coordinator.data.get(DATA_API_POWERSHOUT_INFO): return ps_info.get("isEligible")
        return None
class PowerShoutBalanceSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator); self._attr_device_info = coordinator.device_info; self.entity_description = SensorEntityDescription(key=SENSOR_KEY_POWERSHOUT_BALANCE, name="Power Shout Balance", native_unit_of_measurement="hr", icon="mdi:timer-sand", state_class=SensorStateClass.MEASUREMENT); self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self):
        if ps_balance := self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE):
            if (val := ps_balance.get("balance")) is not None:
                try: return float(val)
                except (ValueError, TypeError): return None
        return None
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = {};
        if not self.coordinator.data: return None
        if offers := self.coordinator.data.get(DATA_API_POWERSHOUT_OFFERS, {}): 
            attrs["active_offers_count"] = len(offers.get("activeOffers", []))
            attrs["active_offers"] = offers.get("activeOffers", [])
        if expiring := self.coordinator.data.get(DATA_API_POWERSHOUT_EXPIRING, {}):
            if msg := expiring.get("expiringHoursMessage", {}): attrs["expiring_hours_message"] = msg.get("title")
        if bookings := self.coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS, {}):
            utc = ZoneInfo("UTC")
            upcoming = [b for b in bookings.get("bookings", []) if isinstance(b, dict) and datetime.fromisoformat(b.get("startDate")).astimezone(utc) > dt_util.utcnow()]
            if upcoming: upcoming.sort(key=lambda b: b["start"]); attrs["next_booking_start"] = upcoming[0].get("startDate")
        return attrs
class GenesisEnergyAccountSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator); self._attr_device_info = coordinator.device_info; self.entity_description = SensorEntityDescription(key=SENSOR_KEY_ACCOUNT_DETAILS, name="Account Details", icon="mdi:account-details"); self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self) -> str: return dt_util.utcnow().isoformat() if self.coordinator.last_update_success else "error"
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.coordinator.data: return None
        attribute_keys = [DATA_API_BILLING_PLANS, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS, DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER, DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT, DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST, DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION]
        attrs = {}; [attrs.update({key.replace("api_", ""): data}) for key in attribute_keys if (data := self.coordinator.data.get(key)) is not None]
        return {k: (json.dumps(v, indent=2) if isinstance(v, (dict, list)) else v) for k, v in attrs.items()}
    
class LpgOrderStatusSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    """Sensor for LPG order status."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, supply_point_data: dict):
        super().__init__(coordinator)
        self._supply_point_id = supply_point_data.get("id")
        # Extract last 4 chars of ICP for a unique-ish name
        icp_suffix = self._supply_point_id[-4:]
        self._attr_name = f"LPG Order Status {icp_suffix}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{SENSOR_KEY_LPG_ORDER_STATUS}_{self._supply_point_id}"
        self._attr_device_info = coordinator.device_info

    @property
    def _order_data(self) -> dict | None:
        """Find the specific order data for this sensor."""
        data = self.coordinator.data.get(DATA_API_LPG_ORDER_STATUS)
        if data:
            for site in data.get("billingAccountSites", []):
                for sp in site.get("supplyPoints", []):
                    if sp.get("id") == self._supply_point_id:
                        # Return the first (most recent) order
                        return sp.get("orders", [None])[0]
        return None

    @property
    def state(self) -> str | None:
        if order := self._order_data:
            return order.get("statusInfo")
        return "No order information"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if order := self._order_data:
            return {
                "estimated_delivery_date": order.get("estimatedDeliveryDate"),
                "bottle_size": order.get("bottleSize"),
                "number_of_bottles": order.get("numberOfBottles"),
                "reference_number": order.get("referenceNumber"),
                "order_created": order.get("orderCreated"),
                "status": order.get("status"),
            }
        return None

class LpgDeliveryHistorySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    """Sensor for LPG delivery history."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:gas-cylinder"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, supply_point_data: dict, history_data: dict):
        super().__init__(coordinator)
        self._supply_point_id = supply_point_data.get("id")
        self._supply_agreement_id = supply_point_data.get("supplyAgreementId")
        icp_suffix = self._supply_point_id[-4:]
        self._attr_name = f"LPG Last Delivery {icp_suffix}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{SENSOR_KEY_LPG_DELIVERY_HISTORY}_{self._supply_point_id}"
        self._attr_device_info = coordinator.device_info
        
    @property
    def _history_data(self) -> dict | None:
        """Find the specific history data for this sensor."""
        all_histories = self.coordinator.data.get(DATA_API_LPG_DELIVERY_HISTORY, [])
        for history in all_histories:
            if isinstance(history, dict) and history.get("deliveryHistory") and history["deliveryHistory"][0].get("supplyAgreementId") == self._supply_agreement_id:
                return history
        return None

    @property
    def _order_data(self) -> dict | None:
        """Find the specific order data for this sensor."""
        data = self.coordinator.data.get(DATA_API_LPG_ORDER_STATUS)
        if data:
            for site in data.get("billingAccountSites", []):
                for sp in site.get("supplyPoints", []):
                    if sp.get("id") == self._supply_point_id:
                        return sp.get("orders", [None])[0]
        return None
        
    @property
    def state(self) -> str | None:
        if order := self._order_data:
            return order.get("lastOrderMessage")
        return "No delivery information"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if history := self._history_data:
            return {"delivery_history": history.get("deliveryHistory")}
        return None
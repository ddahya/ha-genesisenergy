# custom_components/genesisenergy/sensor.py
import logging
from datetime import datetime, date, timedelta, timezone
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
from homeassistant.components.recorder.statistics import async_add_external_statistics, get_last_statistics, statistics_during_period

from .const import (
    DOMAIN, LOGGER, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE, DATA_API_POWERSHOUT_INFO,
    DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS, DATA_API_POWERSHOUT_OFFERS,
    DATA_API_POWERSHOUT_EXPIRING, DATA_API_BILLING_PLANS, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS,
    STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST,
    STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST, SENSOR_KEY_POWERSHOUT_ELIGIBLE,
    SENSOR_KEY_POWERSHOUT_BALANCE, SENSOR_KEY_ACCOUNT_DETAILS,
    DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_BILLS_V2, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST,
    DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
    SENSOR_KEY_BILL_ELEC_USED, SENSOR_KEY_BILL_GAS_USED, SENSOR_KEY_BILL_TOTAL_USED,
    SENSOR_KEY_BILL_ESTIMATED_TOTAL, SENSOR_KEY_BILL_ESTIMATED_FUTURE,
    DATA_API_GENERATION_MIX, DATA_API_GENERATION_MIX_REALTIME, SENSOR_KEY_GENERATION_MIX,
    DATA_API_EV_PLAN_USAGE, DATA_API_EV_RATES, DATA_API_EV_INSIGHTS,
    SENSOR_KEY_EV_DAY_USAGE, SENSOR_KEY_EV_DAY_COST, SENSOR_KEY_EV_NIGHT_USAGE,
    SENSOR_KEY_EV_NIGHT_COST, SENSOR_KEY_EV_TOTAL_SAVINGS,
    DATA_API_ELECTRICITY_FORECAST, SENSOR_KEY_FORECAST_USAGE, SENSOR_KEY_FORECAST_COST,
    DATA_API_USAGE_BREAKDOWN, SENSOR_KEY_BREAKDOWN_APPLIANCES, SENSOR_KEY_BREAKDOWN_ELECTRONICS,
    SENSOR_KEY_BREAKDOWN_LIGHTING, SENSOR_KEY_BREAKDOWN_OTHER, DATA_API_LPG_DETAILS, SENSOR_KEY_LPG_DETAILS,
    CONF_ENABLE_AUTO_CORRECTION, DAILY_OVERWRITE_HOUR
)
from .coordinator import GenesisEnergyDataUpdateCoordinator

def safe_json_dumps(data):
    def default_serializer(o):
        return str(o) 
    return json.dumps(data, indent=2, default=default_serializer)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    
    has_electricity, has_gas = False, False
    billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
    
    # 1. DYNAMIC PRICE SENSORS
    if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
        price_sensor_count = 0
        for site in billing_plans_data["billingAccountSites"]:
            for supply_point in site.get("supplyPoints", []):
                supply_type = supply_point.get("supplyType")
                if supply_type == "electricity": has_electricity = True
                elif supply_type == "naturalGas": has_gas = True
                
                for tariff in supply_point.get("tariffs", []):
                    t_name = tariff.get("name")
                    safe_id = t_name.lower().replace(" ", "_").replace("/", "_")
                    entities.append(
                        GenesisPriceSensor(
                            coordinator, 
                            supply_type, 
                            t_name, 
                            tariff.get("unit"),
                            f"price_{supply_type}_{safe_id}"
                        )
                    )
                    price_sensor_count += 1
        if price_sensor_count > 0:
            LOGGER.info(f"Adding {price_sensor_count} dynamic price sensors from Genesis plan data. ✅")

    if not has_electricity and (coordinator.data.get(DATA_API_ELECTRICITY_USAGE) or coordinator.data.get(DATA_API_EV_RATES)):
        has_electricity = True

    if has_electricity:
        elec_sensor = GenesisEnergyStatisticsSensor(coordinator, "Electricity")
        entities.append(elec_sensor)
        coordinator.statistics_sensors.append(elec_sensor)
        
        # Grid Generation Sensor (supports both realTime and nextTwoDays)
        if coordinator.data.get(DATA_API_GENERATION_MIX_REALTIME) or coordinator.data.get(DATA_API_GENERATION_MIX):
            entities.append(GenerationMixSensor(coordinator))
            
        if coordinator.data.get(DATA_API_ELECTRICITY_FORECAST):
            LOGGER.info("Electricity forecast data found. Adding forecast sensors. ✅")
            entities.extend([ForecastUsageSensor(coordinator), ForecastCostSensor(coordinator)])
            
        if coordinator.data.get(DATA_API_USAGE_BREAKDOWN):
            LOGGER.info("Usage breakdown data found. Adding breakdown sensors. ✅")
            entities.extend([
                UsageBreakdownSensor(coordinator, "Appliances", SENSOR_KEY_BREAKDOWN_APPLIANCES),
                UsageBreakdownSensor(coordinator, "Electronics", SENSOR_KEY_BREAKDOWN_ELECTRONICS),
                UsageBreakdownSensor(coordinator, "Lighting", SENSOR_KEY_BREAKDOWN_LIGHTING),
                UsageBreakdownSensor(coordinator, "Other", SENSOR_KEY_BREAKDOWN_OTHER),
            ])
        
    if has_gas or coordinator.data.get(DATA_API_GAS_USAGE):
        gas_sensor = GenesisEnergyStatisticsSensor(coordinator, "Gas")
        entities.append(gas_sensor)
        coordinator.statistics_sensors.append(gas_sensor)
        
    if coordinator.data.get(DATA_API_EV_PLAN_USAGE):
        LOGGER.info("EV Plan data found. Adding EV plan sensors. ✅")
        entities.extend([
            EVDayUsageSensor(coordinator), EVDayCostSensor(coordinator),
            EVNightUsageSensor(coordinator), EVNightCostSensor(coordinator),
            EVTotalSavingsSensor(coordinator)
        ])

    entities.extend([
        PowerShoutEligibilitySensor(coordinator),
        PowerShoutBalanceSensor(coordinator),
        GenesisEnergyAccountSensor(coordinator)
    ])
    
    # Billing summary sensors
    if coordinator.data.get(DATA_API_WIDGET_SIDEKICK) or coordinator.data.get(DATA_API_WIDGET_BILLS_V2):
        LOGGER.info("Billing summary data found. Adding billing sensors. ✅")
        entities.extend([TotalUsedSensor(coordinator), EstimatedTotalSensor(coordinator), EstimatedFutureUseSensor(coordinator)])
        if has_electricity: entities.append(ElectricityUsedSensor(coordinator))
        if has_gas: entities.append(GasUsedSensor(coordinator))
    
    if coordinator.data.get(DATA_API_LPG_DETAILS):
        LOGGER.info("LPG details data found. Adding LPG sensor. ✅")
        entities.append(LPGDetailsSensor(coordinator))
    
    async_add_entities(entities)

class GenesisPriceSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, supply_type, tariff_name, unit, unique_id):
        super().__init__(coordinator)
        self._supply_type, self._tariff_name, self._unit = supply_type, tariff_name, unit
        self._attr_name = f"{supply_type.capitalize()} {tariff_name}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{unique_id}"
        self._attr_device_info = coordinator.device_info
        if self._unit == "kWh":
            self._attr_device_class, self._attr_native_unit_of_measurement, self._attr_icon = SensorDeviceClass.MONETARY, "NZD/kWh", "mdi:currency-usd"
        elif self._unit == "day":
            self._attr_native_unit_of_measurement, self._attr_icon = "NZD/day", "mdi:cash-check"

    @property
    def native_value(self) -> float | None:
        # 1. Check direct EV rates endpoint first
        ev_rates = self.coordinator.data.get(DATA_API_EV_RATES)
        if ev_rates and isinstance(ev_rates, dict):
            if "Day" in self._tariff_name and "dayRate" in ev_rates:
                return float(ev_rates["dayRate"].get("value", 0))
            if "Night" in self._tariff_name and "nightRate" in ev_rates:
                return float(ev_rates["nightRate"].get("value", 0))

        # 2. Fallback to billing plans
        plans = self.coordinator.data.get(DATA_API_BILLING_PLANS, {})
        for site in plans.get("billingAccountSites", []):
            for supply in site.get("supplyPoints", []):
                if supply.get("supplyType") == self._supply_type:
                    for tariff in supply.get("tariffs", []):
                        if tariff.get("name") == self._tariff_name:
                            return abs(float(tariff.get("value", 0)))
        return None

class LPGDetailsSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name, _attr_icon = True, "mdi:gas-cylinder"
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(key=SENSOR_KEY_LPG_DETAILS, name="LPG Details")
        self._attr_device_info, self._attr_unique_id = coordinator.device_info, f"{coordinator.config_entry.entry_id}_{SENSOR_KEY_LPG_DETAILS}"

    @property
    def native_value(self) -> str: return dt_util.utcnow().isoformat() if self.coordinator.last_update_success else "error"
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.coordinator.data or (data := self.coordinator.data.get(DATA_API_LPG_DETAILS)) is None: return None
        return {"data": safe_json_dumps(data)} if isinstance(data, (dict, list)) else {"data": data}

class GenesisEnergyStatisticsSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name, _attr_should_poll = True, False
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, fuel_type: str):
        super().__init__(coordinator); self._fuel_type, self._data_key = fuel_type, DATA_API_ELECTRICITY_USAGE if fuel_type == "Electricity" else DATA_API_GAS_USAGE
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(key=f"{fuel_type.lower()}_statistics_updater", name=f"{fuel_type.capitalize()} Statistics Updater", icon="mdi:chart-line" if self._fuel_type == "Electricity" else "mdi:chart-bell-curve-cumulative")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        if self._fuel_type == "Electricity": self._consumption_statistic_id, self._cost_statistic_id = STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST
        else: self._consumption_statistic_id, self._cost_statistic_id = STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST
        self._consumption_statistic_name, self._cost_statistic_name, self._unit, self._currency, self._processed_data_hash, self._utc_tz, self._last_daily_override_date = f"Genesis {fuel_type} Consumption Daily", f"Genesis {fuel_type} Cost Daily", "kWh", "NZD", None, ZoneInfo("UTC"), None

    @property
    def native_value(self) -> str:
        if self.coordinator.data and (api_data := self.coordinator.data.get(self._data_key)) and api_data.get("usage"): return "ok"
        return "no_data" if self.coordinator.last_update_success else "error"

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success: self.async_write_ha_state(); return
        if (api_data := self.coordinator.data.get(self._data_key)) and (raw_usage_list := api_data.get('usage')):
            now_local = dt_util.now(); today_local = now_local.date(); force_daily_overwrite = False
            auto_correction_enabled = self.coordinator.config_entry.options.get(CONF_ENABLE_AUTO_CORRECTION, False)
            if auto_correction_enabled and now_local.hour >= DAILY_OVERWRITE_HOUR and (self._last_daily_override_date is None or self._last_daily_override_date < today_local):
                force_daily_overwrite, self._last_daily_override_date = True, today_local
            current_hash = (len(raw_usage_list), raw_usage_list[0].get('startDate'), raw_usage_list[-1].get('startDate'))
            if self._processed_data_hash != current_hash or force_daily_overwrite:
                if force_daily_overwrite: LOGGER.info(f"[{self._fuel_type}] Triggering scheduled daily statistic overwrite.")
                else: LOGGER.info(f"[{self._fuel_type}] New data detected, triggering standard statistic append.")
                self.hass.async_create_task(self.async_process_statistics_data(list(raw_usage_list), force_overwrite=force_daily_overwrite))
                self._processed_data_hash = current_hash
        self.async_write_ha_state()

    async def async_process_statistics_data(self, usage_data: list, force_overwrite: bool = False, start_date: date | None = None):
        if not usage_data: return
        try: sorted_usage_data = sorted(usage_data, key=lambda x: x['startDate'])
        except (KeyError, TypeError): return
        LOGGER.info(f"  Processing {len(usage_data)} entries for {self._fuel_type} (Force Overwrite: {force_overwrite})")
        async def _process_one_statistic(statistic_id: str, stat_name: str, unit: str, value_key: str):
            running_sum, last_ts = 0.0, 0
            if force_overwrite:
                start_of_window = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc) if start_date else dt_util.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3)
                last_stats_before_window = await get_instance(self.hass).async_add_executor_job(statistics_during_period, self.hass, start_of_window - timedelta(days=1), start_of_window, {statistic_id}, "hour", None, {"sum"})
                if statistic_id in last_stats_before_window and last_stats_before_window[statistic_id]:
                    last_stat = last_stats_before_window[statistic_id][-1]; running_sum, last_ts = float(last_stat.get('sum', 0.0)), last_stat.get('start', 0)
            else:
                last_stat_list = await get_instance(self.hass).async_add_executor_job(get_last_statistics, self.hass, 1, statistic_id, True, {"sum"})
                if last_stat_list and statistic_id in last_stat_list:
                    last_stat = last_stat_list[statistic_id][0]; running_sum, last_ts = float(last_stat.get('sum', 0.0)), last_stat.get('start', 0)
            stats_to_add = []
            for entry in sorted_usage_data:
                try: val, start_dt_utc = float(entry[value_key]), datetime.fromisoformat(entry['startDate']).astimezone(self._utc_tz)
                except (KeyError, ValueError, TypeError): continue
                if start_dt_utc.timestamp() > last_ts:
                    running_sum += val; stats_to_add.append(StatisticData(start=start_dt_utc, state=round(val, 2), sum=round(running_sum, 2)))
            if stats_to_add:
                mode_str = "Overwrite" if force_overwrite else "Append"
                LOGGER.info(f"  Importing {len(stats_to_add)} '{stat_name}' statistics (Mode: {mode_str}).")
                meta = StatisticMetaData(has_mean=False, has_sum=True, name=stat_name, source=DOMAIN, statistic_id=statistic_id, unit_of_measurement=unit)
                async_add_external_statistics(self.hass, meta, stats_to_add)
            else: LOGGER.info(f"  No new data to import for '{stat_name}'.")
        await _process_one_statistic(self._consumption_statistic_id, self._consumption_statistic_name, self._unit, 'kw')
        await _process_one_statistic(self._cost_statistic_id, self._cost_statistic_name, self._currency, 'costNZD')

class GenerationMixSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name, _attr_native_unit_of_measurement, _attr_icon, _attr_state_class = True, "%", "mdi:leaf", SensorStateClass.MEASUREMENT
    def __init__(self, coordinator):
        super().__init__(coordinator); self.entity_description = SensorEntityDescription(key=SENSOR_KEY_GENERATION_MIX, name="Grid Generation Eco-Friendly")
        self._attr_device_info, self._attr_unique_id, self._nz_tz = coordinator.device_info, f"{coordinator.config_entry.entry_id}_{self.entity_description.key}", ZoneInfo('Pacific/Auckland')

    @property
    def native_value(self):
        # 1. Try real-time generation mix (new website)
        rt_mix = self.coordinator.data.get(DATA_API_GENERATION_MIX_REALTIME)
        if rt_mix and isinstance(rt_mix, dict):
            eco_pct = rt_mix.get("generationSourcesEcoFriendlyPercentage")
            if eco_pct is not None:
                return float(eco_pct)

        # 2. Fallback to hourly generation mix forecast
        if not (gen_mix := self.coordinator.data.get(DATA_API_GENERATION_MIX)): return None
        now_nz = dt_util.now(self._nz_tz); today, hour = now_nz.strftime('%Y-%m-%d'), now_nz.hour
        for day in gen_mix:
            if day.get("Day") == today:
                for h in day.get("HourlyBreakdown", []):
                    if h.get("Hour") == hour: return float(h.get("EcoFriendlyPercentage"))
        return None

    @property
    def extra_state_attributes(self):
        attrs = {}
        if rt := self.coordinator.data.get(DATA_API_GENERATION_MIX_REALTIME):
            attrs["realtime"] = rt
        if fc := self.coordinator.data.get(DATA_API_GENERATION_MIX):
            attrs["forecast"] = fc
        return attrs

class GenesisEVPlanSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name, _attr_attribution = True, "Data from latest full day"
    def __init__(self, coordinator, desc):
        super().__init__(coordinator); self.entity_description, self._attr_device_info, self._attr_unique_id = desc, coordinator.device_info, f"{coordinator.config_entry.entry_id}_{desc.key}"
    @property
    def available(self): return super().available and self.coordinator.data.get(DATA_API_EV_PLAN_USAGE) is not None
    @property
    def _latest_day_data(self):
        ev_data = self.coordinator.data.get(DATA_API_EV_PLAN_USAGE); return ev_data[-1] if ev_data and isinstance(ev_data, list) else None
    @property
    def extra_state_attributes(self):
        if (data := self._latest_day_data) and (rd := data.get("date")):
            try: return {"reading_date": datetime.fromisoformat(rd).strftime("%A, %d %B %Y")}
            except (ValueError, TypeError): return {"reading_date": rd}
        return None

class EVDayUsageSensor(GenesisEVPlanSensor):
    _attr_native_unit_of_measurement, _attr_state_class = "kWh", SensorStateClass.MEASUREMENT
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_DAY_USAGE, name="EV Plan Day Usage"))
    @property
    def native_value(self): return self._latest_day_data.get("kWhDay") if self._latest_day_data else None

class EVDayCostSensor(GenesisEVPlanSensor):
    _attr_device_class, _attr_native_unit_of_measurement, _attr_state_class = SensorDeviceClass.MONETARY, "NZD", SensorStateClass.TOTAL
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_DAY_COST, name="EV Plan Day Cost"))
    @property
    def native_value(self):
        try: return float(self._latest_day_data.get("usageCostDay"))
        except (ValueError, TypeError): return None

class EVNightUsageSensor(GenesisEVPlanSensor):
    _attr_native_unit_of_measurement, _attr_state_class = "kWh", SensorStateClass.MEASUREMENT
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_NIGHT_USAGE, name="EV Plan Night Usage"))
    @property
    def native_value(self): return self._latest_day_data.get("kWhNight") if self._latest_day_data else None

class EVNightCostSensor(GenesisEVPlanSensor):
    _attr_device_class, _attr_native_unit_of_measurement, _attr_state_class = SensorDeviceClass.MONETARY, "NZD", SensorStateClass.TOTAL
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_NIGHT_COST, name="EV Plan Night Cost"))
    @property
    def native_value(self):
        try: return float(self._latest_day_data.get("usageCostNight"))
        except (ValueError, TypeError): return None

class EVTotalSavingsSensor(GenesisEVPlanSensor):
    _attr_device_class, _attr_native_unit_of_measurement, _attr_state_class, _attr_icon = SensorDeviceClass.MONETARY, "NZD", SensorStateClass.TOTAL, "mdi:piggy-bank-outline"
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_TOTAL_SAVINGS, name="EV Plan Savings"))
    @property
    def native_value(self):
        if not (d := self._latest_day_data): return None
        try: return round(float(d.get("costWithDayRate")) - float(d.get("usageCostNight")), 2)
        except (ValueError, TypeError, KeyError): return None
    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes or {}
        if h := self.coordinator.data.get(DATA_API_EV_PLAN_USAGE): attrs["history"] = h
        if ins := self.coordinator.data.get(DATA_API_EV_INSIGHTS): attrs["insights"] = ins
        return attrs

class ForecastSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name, _attr_attribution = True, "Forecast data from Genesis Energy"
    def __init__(self, coordinator, desc):
        super().__init__(coordinator); self.entity_description, self._attr_device_info, self._attr_unique_id = desc, coordinator.device_info, f"{coordinator.config_entry.entry_id}_{desc.key}"

    @property
    def available(self):
        f = self.coordinator.data.get(DATA_API_ELECTRICITY_FORECAST)
        if not f: return False
        if "IcpForecasts" in f and f["IcpForecasts"]: return True
        if "Forecast" in f or "forecast" in f: return True
        return False

    @property
    def _today_forecast_data(self):
        f = self.coordinator.data.get(DATA_API_ELECTRICITY_FORECAST)
        if not f: return None
        if "IcpForecasts" in f and f["IcpForecasts"] and "Forecast" in f["IcpForecasts"][0]:
            return f["IcpForecasts"][0]["Forecast"][0]
        if "Forecast" in f and isinstance(f["Forecast"], list) and f["Forecast"]:
            return f["Forecast"][0]
        return None

class ForecastUsageSensor(ForecastSensor):
    _attr_native_unit_of_measurement, _attr_state_class, _attr_icon = "kWh", SensorStateClass.MEASUREMENT, "mdi:chart-line"
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_FORECAST_USAGE, name="Today's Forecast Usage"))
    @property
    def native_value(self):
        t = self._today_forecast_data
        if not t: return None
        return t.get("PredictionInkWh") or t.get("predictionInkWh") or t.get("predictionKwh")

class ForecastCostSensor(ForecastSensor):
    _attr_native_unit_of_measurement, _attr_state_class, _attr_icon = "NZD", SensorStateClass.MEASUREMENT, "mdi:currency-usd"
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_FORECAST_COST, name="Today's Forecast Cost"))
    @property
    def native_value(self):
        t = self._today_forecast_data
        if not t: return None
        return t.get("PredictionCost") or t.get("predictionCost")

class UsageBreakdownSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_device_class, _attr_native_unit_of_measurement, _attr_state_class, _attr_has_entity_name = SensorDeviceClass.ENERGY, "kWh", SensorStateClass.TOTAL, True
    def __init__(self, coordinator, cat, key):
        super().__init__(coordinator); self._category_name, self.entity_description = cat, SensorEntityDescription(key=key, name=f"Usage Breakdown - {cat}")
        self._attr_device_info, self._attr_unique_id = coordinator.device_info, f"{coordinator.config_entry.entry_id}_{key}"

    @property
    def _latest_breakdown_period(self):
        b = self.coordinator.data.get(DATA_API_USAGE_BREAKDOWN)
        return b["electricity"]["breakdowns"][0] if b and "electricity" in b and b["electricity"].get("breakdowns") else None

    @property
    def _category_data(self):
        if b := self._latest_breakdown_period:
            for c in b.get("categories", []):
                if c.get("name") == self._category_name: return c
        return None

    @property
    def native_value(self): return self._category_data.get("kWh", {}).get("value") if self._category_data else None

class GenesisBillSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name, _attr_native_unit_of_measurement, _attr_device_class, _attr_icon = True, "NZD", SensorDeviceClass.MONETARY, "mdi:cash"
    def __init__(self, coordinator, desc):
        super().__init__(coordinator); self.entity_description, self._attr_device_info, self._attr_unique_id = desc, coordinator.device_info, f"{coordinator.config_entry.entry_id}_{desc.key}"
    @property
    def available(self):
        return super().available and (
            self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK) is not None or 
            self.coordinator.data.get(DATA_API_WIDGET_BILLS_V2) is not None
        )

    def _get_sidekick_data(self):
        if s := self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK): return s
        if v2 := self.coordinator.data.get(DATA_API_WIDGET_BILLS_V2):
            return v2.get("billEstimated", {})
        return {}

class ElectricityUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_ELEC_USED, name="Genesis Bill - Electricity Used", state_class=SensorStateClass.TOTAL))
    @property
    def native_value(self):
        s_data = self._get_sidekick_data()
        for s in s_data.get('supplyTypesArea', {}).get('supplyTypes', []):
            if s.get('type') in ['electricity', 'Electricity']:
                try: return float(s.get('value'))
                except (ValueError, TypeError): return None
        return 0.0

class GasUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_GAS_USED, name="Genesis Bill - Gas Used", state_class=SensorStateClass.TOTAL))
    @property
    def native_value(self):
        s_data = self._get_sidekick_data()
        for s in s_data.get('supplyTypesArea', {}).get('supplyTypes', []):
            if s.get('type') in ['naturalGas', 'natural_gas', 'Gas', 'gas']:
                try: return float(s.get('value'))
                except (ValueError, TypeError): return None
        return 0.0

class TotalUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_TOTAL_USED, name="Genesis Bill - Total Used", state_class=SensorStateClass.TOTAL))
    @property
    def native_value(self):
        try: return float(self._get_sidekick_data().get('titleArea', {}).get('value'))
        except (ValueError, TypeError): return None

class EstimatedTotalSensor(GenesisBillSensor):
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_TOTAL, name="Genesis Bill - Estimated Total"))
    @property
    def native_value(self):
        t = self._get_sidekick_data().get('billArea', {}).get('title')
        try: return float(t.split('$')[1]) if t and '$' in t else None
        except (ValueError, IndexError): return None

class EstimatedFutureUseSensor(GenesisBillSensor):
    def __init__(self, coordinator): super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_FUTURE, name="Genesis Bill - Estimated Future Use"))
    @property
    def native_value(self):
        s = self._get_sidekick_data()
        ev, uv = 0.0, 0.0
        try: ev = float(s.get('billArea', {}).get('title').split('$')[1])
        except (ValueError, IndexError): pass
        try: uv = float(s.get('titleArea', {}).get('value'))
        except (ValueError, TypeError): pass
        return round(max(0.0, ev - uv), 2)

class PowerShoutEligibilitySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator):
        super().__init__(coordinator); self._attr_device_info, self.entity_description = coordinator.device_info, SensorEntityDescription(key=SENSOR_KEY_POWERSHOUT_ELIGIBLE, name="Power Shout Eligible", icon="mdi:lightning-bolt-outline")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self):
        p = self.coordinator.data.get(DATA_API_POWERSHOUT_INFO)
        return isinstance(p.get("eligibleBillingAccounts"), list) and len(p["eligibleBillingAccounts"]) > 0 if p else None

class PowerShoutBalanceSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator):
        super().__init__(coordinator); self._attr_device_info, self.entity_description = coordinator.device_info, SensorEntityDescription(key=SENSOR_KEY_POWERSHOUT_BALANCE, name="Power Shout Balance", native_unit_of_measurement="hr", icon="mdi:timer-sand", state_class=SensorStateClass.MEASUREMENT)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self):
        try: return float(self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE, {}).get("balance"))
        except (ValueError, TypeError): return None
    @property
    def extra_state_attributes(self):
        attrs = {}
        if not self.coordinator.data: return None
        if o := self.coordinator.data.get(DATA_API_POWERSHOUT_OFFERS, {}): attrs["active_offers_count"], attrs["active_offers"] = len(o.get("activeOffers", [])), o.get("activeOffers", [])
        if e := self.coordinator.data.get(DATA_API_POWERSHOUT_EXPIRING):
            if m := e.get("expiringHoursMessage"): 
                t_title = m.get("title"); substrings = m.get("titleSubstrings")
                if t_title and substrings: attrs["expiring_hours_message"] = t_title.replace("{{0}}", substrings[0].get("text"))
                elif t_title: attrs["expiring_hours_message"] = t_title
            if t_tip := e.get("messageTooltip"): attrs["expiring_hours_tooltip"] = t_tip.get("description")
        if b_data := self.coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS, {}):
            b_list = b_data.get("bookings", []); attrs["bookings"] = b_list
            u = sorted([x for x in b_list if datetime.fromisoformat(x["startDateTime"]).replace(tzinfo=timezone.utc) > dt_util.utcnow()], key=lambda x: x["startDateTime"])
            if u: attrs["next_booking_start"] = u[0]["startDateTime"]
        return attrs

class GenesisEnergyAccountSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator):
        super().__init__(coordinator); self._attr_device_info, self.entity_description = coordinator.device_info, SensorEntityDescription(key=SENSOR_KEY_ACCOUNT_DETAILS, name="Account Details", icon="mdi:account-details")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self) -> str: return dt_util.utcnow().isoformat() if self.coordinator.last_update_success else "error"
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.coordinator.data: return None
        k = [DATA_API_BILLING_PLANS, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS, DATA_API_WIDGET_BILLS_V2, DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER, DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT, DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST, DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION]
        attrs = {}
        for key in k:
            attr_name = key.replace("api_", ""); data = self.coordinator.data.get(key)
            if data is None: continue
            if isinstance(data, (dict, list)):
                dumped = safe_json_dumps(data)
                attrs[attr_name] = dumped
            else: attrs[attr_name] = data
        return attrs
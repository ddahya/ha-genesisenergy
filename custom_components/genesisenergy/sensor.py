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
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)

from .const import (
    DOMAIN, LOGGER, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE, DATA_API_POWERSHOUT_INFO,
    DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS, DATA_API_POWERSHOUT_OFFERS,
    DATA_API_POWERSHOUT_EXPIRING, DATA_API_POWERSHOUT_RECOMMENDED_HOURS,
    DATA_API_BILLING_PLANS, DATA_API_BILLING_SUMMARY, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS,
    STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST,
    STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST, SENSOR_KEY_POWERSHOUT_ELIGIBLE,
    SENSOR_KEY_POWERSHOUT_BALANCE, SENSOR_KEY_ACCOUNT_DETAILS,
    DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_BILLS_V2, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST,
    DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
    SENSOR_KEY_BILL_ELEC_USED, SENSOR_KEY_BILL_GAS_USED, SENSOR_KEY_BILL_TOTAL_USED,
    SENSOR_KEY_BILL_ESTIMATED_TOTAL, SENSOR_KEY_BILL_ESTIMATED_FUTURE,
    SENSOR_KEY_BILL_BALANCE, SENSOR_KEY_BILL_OVERDUE, SENSOR_KEY_BILL_DUE_DATE, SENSOR_KEY_BILL_DUE_DAYS,
    DATA_API_GENERATION_MIX, DATA_API_GENERATION_MIX_REALTIME, SENSOR_KEY_GENERATION_MIX,
    DATA_API_EV_PLAN_USAGE,
    SENSOR_KEY_EV_DAY_USAGE, SENSOR_KEY_EV_DAY_COST, SENSOR_KEY_EV_NIGHT_USAGE,
    SENSOR_KEY_EV_NIGHT_COST, SENSOR_KEY_EV_TOTAL_SAVINGS,
    DATA_API_ELECTRICITY_FORECAST, SENSOR_KEY_FORECAST_USAGE, SENSOR_KEY_FORECAST_COST,
    DATA_API_LPG_DETAILS, SENSOR_KEY_LPG_DETAILS,
    CONF_ENABLE_AUTO_CORRECTION, DAILY_OVERWRITE_HOUR
)
from .coordinator import GenesisEnergyDataUpdateCoordinator

def safe_json_dumps(data: Any) -> str:
    def default_serializer(o):
        return str(o)
    return json.dumps(data, indent=2, default=default_serializer)

def _slug(text: str) -> str:
    """Lowercase a label into an underscore slug for use in entity keys."""
    return "".join(c if c.isalnum() else "_" for c in str(text).lower()).strip("_")

def _parse_genesis_date(value: Any) -> date | None:
    """Parse Genesis date formats into a date object."""
    if not value:
        return None
    val_str = str(value).strip()
    try:
        return datetime.fromisoformat(val_str.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        pass
    for fmt in ("%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val_str, fmt).date()
        except (ValueError, TypeError):
            pass
    return None

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[SensorEntity] = []
    
    has_electricity, has_gas = False, False
    billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
    
    # 1. DYNAMIC PRICE & PLAN SENSORS (Restores original GenesisPriceSensor unique_ids)
    if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
        for site in billing_plans_data["billingAccountSites"]:
            if not isinstance(site.get("supplyPoints"), list):
                continue
            for sp in site["supplyPoints"]:
                if not isinstance(sp, dict) or not sp.get("id"):
                    continue
                supply_type = sp.get("supplyType") or "supply"
                supply_display = sp.get("supplyTypeDisplay") or supply_type.capitalize()
                sp_id = sp["id"]

                if supply_type == "electricity":
                    has_electricity = True
                elif supply_type in ["naturalGas", "gas"]:
                    has_gas = True

                # Plan Name & Term End sensors
                entities.append(GenesisPlanSensor(coordinator, sp_id, supply_type, supply_display))

                plan_term = sp.get("planTerm") or {}
                if not plan_term.get("hide") and plan_term.get("endDate"):
                    entities.append(GenesisPlanTermEndSensor(coordinator, sp_id, supply_type, supply_display))

                # Exact Original GenesisPriceSensor: Restores original Unique ID and Name
                for tariff in sp.get("tariffs", []):
                    if not isinstance(tariff, dict) or not tariff.get("name"):
                        continue
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

                # Discount sensors
                for discount in sp.get("appliedDiscounts", []):
                    if not isinstance(discount, dict) or not discount.get("name"):
                        continue
                    entities.append(GenesisDiscountSensor(coordinator, sp_id, supply_type, supply_display, discount["name"]))

    if not has_electricity and coordinator.data.get(DATA_API_ELECTRICITY_USAGE):
        has_electricity = True

    # 2. ELECTRICITY STATISTICS & ECO
    if has_electricity:
        elec_sensor = GenesisEnergyStatisticsSensor(coordinator, "Electricity")
        entities.append(elec_sensor)
        coordinator.statistics_sensors.append(elec_sensor)
        
        if coordinator.data.get(DATA_API_GENERATION_MIX_REALTIME) or coordinator.data.get(DATA_API_GENERATION_MIX):
            entities.append(GenerationMixSensor(coordinator))
            
        if coordinator.data.get(DATA_API_ELECTRICITY_FORECAST):
            entities.extend([ForecastUsageSensor(coordinator), ForecastCostSensor(coordinator)])

    # 3. GAS STATISTICS
    if has_gas or coordinator.data.get(DATA_API_GAS_USAGE):
        gas_sensor = GenesisEnergyStatisticsSensor(coordinator, "Gas")
        entities.append(gas_sensor)
        coordinator.statistics_sensors.append(gas_sensor)

    # 4. EV PLAN SENSORS
    if coordinator.data.get(DATA_API_EV_PLAN_USAGE):
        LOGGER.info("EV Plan data found. Adding EV plan sensors. ✅")
        entities.extend([
            EVDayUsageSensor(coordinator), EVDayCostSensor(coordinator),
            EVNightUsageSensor(coordinator), EVNightCostSensor(coordinator),
            EVTotalSavingsSensor(coordinator)
        ])

    # 5. CORE POWER SHOUT & ACCOUNT SENSORS
    entities.extend([
        PowerShoutEligibilitySensor(coordinator),
        PowerShoutBalanceSensor(coordinator),
        GenesisEnergyAccountSensor(coordinator)
    ])
    
    # 6. ESTIMATED BILLING SENSORS (SIDEKICK / BILLS V2)
    if coordinator.data.get(DATA_API_WIDGET_SIDEKICK) or coordinator.data.get(DATA_API_WIDGET_BILLS_V2):
        entities.extend([TotalUsedSensor(coordinator), EstimatedTotalSensor(coordinator), EstimatedFutureUseSensor(coordinator)])
        if has_electricity:
            entities.append(ElectricityUsedSensor(coordinator))
        if has_gas:
            entities.append(GasUsedSensor(coordinator))

    # 7. LIVE BILL SUMMARY SENSORS (from /billing/summary)
    if coordinator.data.get(DATA_API_BILLING_SUMMARY):
        LOGGER.info("Live billing summary data found. Adding live bill balance & due date sensors. ✅")
        entities.extend([
            BillBalanceSensor(coordinator),
            BillOverdueSensor(coordinator),
            BillDueDateSensor(coordinator),
            BillDueDaysSensor(coordinator),
        ])
    
    # 8. LPG CYLINDERS
    if coordinator.data.get(DATA_API_LPG_DETAILS):
        entities.append(LPGDetailsSensor(coordinator))
    
    async_add_entities(entities)


# ── Original Genesis Price Sensor (Preserves original entity IDs) ──────────

class GenesisPriceSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, supply_type, tariff_name, unit, unique_id):
        super().__init__(coordinator)
        self._supply_type = supply_type
        self._tariff_name = tariff_name
        self._unit = unit
        self._attr_name = f"{supply_type.capitalize()} {tariff_name}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{unique_id}"
        self._attr_device_info = coordinator.device_info
        self._attr_suggested_display_precision = 4
        if self._unit == "kWh":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = "NZD/kWh"
            self._attr_icon = "mdi:currency-usd"
        elif self._unit == "day":
            self._attr_native_unit_of_measurement = "NZD/day"
            self._attr_icon = "mdi:cash-check"

    @property
    def native_value(self) -> float | None:
        plans = self.coordinator.data.get(DATA_API_BILLING_PLANS) or {}
        if isinstance(plans, dict):
            for site in plans.get("billingAccountSites", []):
                for supply in site.get("supplyPoints", []):
                    if supply.get("supplyType") == self._supply_type:
                        for tariff in supply.get("tariffs", []):
                            if tariff.get("name") == self._tariff_name:
                                try:
                                    return float(tariff.get("value", 0))
                                except (ValueError, TypeError):
                                    return None
        return None


# ── Plan & Discount Sensors ────────────────────────────────────────────────

class GenesisPlanBaseSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, supply_point_id: str, key: str, name: str, icon: str | None = None):
        super().__init__(coordinator)
        self._sp_id = supply_point_id
        self.entity_description = SensorEntityDescription(key=key, name=name, icon=icon)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"

    def _find(self) -> tuple[dict | None, dict | None]:
        data = self.coordinator.data.get(DATA_API_BILLING_PLANS) if self.coordinator.data else None
        if not data:
            return None, None
        for site in data.get("billingAccountSites", []):
            if not isinstance(site, dict):
                continue
            for sp in site.get("supplyPoints", []) or []:
                if isinstance(sp, dict) and sp.get("id") == self._sp_id:
                    return site, sp
        return None, None

    @property
    def _supply_point(self) -> dict | None:
        return self._find()[1]

    @property
    def available(self) -> bool:
        return super().available and self._supply_point is not None


class GenesisPlanSensor(GenesisPlanBaseSensor):
    _attr_icon = "mdi:file-document-outline"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, sp_id: str, supply_type: str, supply_display: str):
        super().__init__(coordinator, sp_id, f"plan_{supply_type}", f"{supply_display} Plan")

    @property
    def native_value(self) -> str | None:
        if not (sp := self._supply_point):
            return None
        plan, profile = sp.get("plan"), sp.get("planProfile")
        if plan and profile:
            return f"{plan} ({profile})"
        return plan or sp.get("planDisplay")

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        site, sp = self._find()
        if not sp:
            return None
        term = sp.get("planTerm") or {}
        return {
            "address": site.get("address") if site else None,
            "supply_type": sp.get("supplyTypeDisplay"),
            "plan_profile": sp.get("planProfile"),
            "plan_display": sp.get("planDisplay"),
            "term_type": term.get("type"),
            "term_end_date": term.get("endDate"),
        }


class GenesisPlanTermEndSensor(GenesisPlanBaseSensor):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-end"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, sp_id: str, supply_type: str, supply_display: str):
        super().__init__(coordinator, sp_id, f"plan_term_end_{supply_type}", f"{supply_display} Plan Term End")

    @property
    def native_value(self) -> date | None:
        if not (sp := self._supply_point):
            return None
        return _parse_genesis_date((sp.get("planTerm") or {}).get("endDate"))


class GenesisDiscountSensor(GenesisPlanBaseSensor):
    _attr_icon = "mdi:sale"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, sp_id: str, supply_type: str, supply_display: str, discount_name: str):
        key = f"discount_{supply_type}_{_slug(discount_name)}"
        super().__init__(coordinator, sp_id, key, f"{supply_display} {discount_name} Discount")
        self._discount_name = discount_name

    @property
    def native_value(self) -> float | None:
        if not (sp := self._supply_point):
            return None
        for discount in sp.get("appliedDiscounts", []):
            if isinstance(discount, dict) and discount.get("name") == self._discount_name:
                try:
                    return float(discount.get("value", 0))
                except (ValueError, TypeError):
                    return None
        return None


# ── Live Bill Summary Sensors ──────────────────────────────────────────────

class GenesisBillSummarySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, key: str, name: str, icon: str | None = None):
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(key=key, name=name, icon=icon)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"

    @property
    def _summary(self) -> dict | None:
        data = self.coordinator.data.get(DATA_API_BILLING_SUMMARY) if self.coordinator.data else None
        return data if isinstance(data, dict) else None

    @property
    def available(self) -> bool:
        return super().available and self._summary is not None


class BillBalanceSensor(GenesisBillSummarySensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SENSOR_KEY_BILL_BALANCE, "Bill Balance")

    @property
    def native_value(self) -> float | None:
        if summary := self._summary:
            try:
                return float(summary.get("balance", 0))
            except (ValueError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if summary := self._summary:
            return {
                "amount_total": summary.get("amountTotal"),
                "last_payment_date": summary.get("lastPaymentDate"),
                "last_payment_method": summary.get("lastPaymentMethod"),
            }
        return None


class BillOverdueSensor(GenesisBillSummarySensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_icon = "mdi:cash-clock"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SENSOR_KEY_BILL_OVERDUE, "Bill Amount Overdue")

    @property
    def native_value(self) -> float | None:
        if summary := self._summary:
            try:
                return float(summary.get("amountOverdue", 0))
            except (ValueError, TypeError):
                return None
        return None


class BillDueDateSensor(GenesisBillSummarySensor):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SENSOR_KEY_BILL_DUE_DATE, "Bill Due Date")

    @property
    def native_value(self) -> date | None:
        if summary := self._summary:
            return _parse_genesis_date(summary.get("dueDate"))
        return None


class BillDueDaysSensor(GenesisBillSummarySensor):
    _attr_native_unit_of_measurement = "d"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SENSOR_KEY_BILL_DUE_DAYS, "Bill Due In")

    @property
    def native_value(self) -> int | None:
        if summary := self._summary:
            try:
                return int(summary.get("dueDays", 0))
            except (ValueError, TypeError):
                return None
        return None


# ── Statistics Updater ─────────────────────────────────────────────────────

class GenesisEnergyStatisticsSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, fuel_type: str):
        super().__init__(coordinator)
        self._fuel_type = fuel_type
        self._data_key = DATA_API_ELECTRICITY_USAGE if fuel_type == "Electricity" else DATA_API_GAS_USAGE
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(
            key=f"{fuel_type.lower()}_statistics_updater",
            name=f"{fuel_type.capitalize()} Statistics Updater",
            icon="mdi:chart-line" if self._fuel_type == "Electricity" else "mdi:chart-bell-curve-cumulative"
        )
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        if self._fuel_type == "Electricity":
            self._consumption_statistic_id = STATISTIC_ID_ELECTRICITY_CONSUMPTION
            self._cost_statistic_id = STATISTIC_ID_ELECTRICITY_COST
        else:
            self._consumption_statistic_id = STATISTIC_ID_GAS_CONSUMPTION
            self._cost_statistic_id = STATISTIC_ID_GAS_COST
        self._consumption_statistic_name = f"Genesis {fuel_type} Consumption Daily"
        self._cost_statistic_name = f"Genesis {fuel_type} Cost Daily"
        self._unit = "kWh"
        self._currency = "NZD"
        self._processed_data_hash = None
        self._utc_tz = ZoneInfo("UTC")
        self._last_daily_override_date: date | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @property
    def native_value(self) -> str:
        if self.coordinator.data and (api_data := self.coordinator.data.get(self._data_key)) and api_data.get("usage"):
            return "ok"
        return "no_data" if self.coordinator.last_update_success else "error"

    @property
    def _latest_reading(self) -> datetime | None:
        if not self.coordinator.data:
            return None
        api_data = self.coordinator.data.get(self._data_key)
        entries = api_data.get("usage") if isinstance(api_data, dict) else None
        if not isinstance(entries, list):
            return None
        latest: datetime | None = None
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("startDate"):
                continue
            try:
                parsed = datetime.fromisoformat(str(entry["startDate"]))
            except (TypeError, ValueError):
                continue
            if latest is None or parsed > latest:
                latest = parsed
        return latest

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        latest = self._latest_reading
        if latest is None:
            return {"latest_reading": None, "days_behind": None}
        days_behind = (dt_util.now().date() - latest.astimezone(self._utc_tz).date()).days
        return {
            "latest_reading": latest.isoformat(),
            "days_behind": max(0, days_behind),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success:
            self.async_write_ha_state()
            return
        if (api_data := self.coordinator.data.get(self._data_key)) and (raw_usage_list := api_data.get('usage')):
            now_local = dt_util.now()
            today_local = now_local.date()
            force_daily_overwrite = False
            auto_correction_enabled = self.coordinator.config_entry.options.get(CONF_ENABLE_AUTO_CORRECTION, False)
            if auto_correction_enabled and now_local.hour >= DAILY_OVERWRITE_HOUR and (self._last_daily_override_date is None or self._last_daily_override_date < today_local):
                force_daily_overwrite, self._last_daily_override_date = True, today_local
            
            total_sum = round(sum(float(x.get('kw', 0)) for x in raw_usage_list if isinstance(x, dict)), 2)
            current_hash = (len(raw_usage_list), raw_usage_list[0].get('startDate'), raw_usage_list[-1].get('startDate'), total_sum)
            
            if self._processed_data_hash != current_hash or force_daily_overwrite:
                if force_daily_overwrite:
                    LOGGER.info("[%s] Triggering scheduled daily statistic overwrite.", self._fuel_type)
                else:
                    LOGGER.info("[%s] New data detected, triggering statistic processing.", self._fuel_type)
                self.hass.async_create_task(self.async_process_statistics_data(list(raw_usage_list), force_overwrite=force_daily_overwrite))
                self._processed_data_hash = current_hash
        self.async_write_ha_state()

    async def async_process_statistics_data(self, usage_data: list, force_overwrite: bool = False, start_date: date | None = None):
        if not usage_data:
            return
        try:
            sorted_usage_data = sorted(usage_data, key=lambda x: x['startDate'])
        except (KeyError, TypeError):
            return
        
        LOGGER.info("  Processing %d entries for %s (Force Overwrite: %s)", len(usage_data), self._fuel_type, force_overwrite)

        async def _process_one_statistic(statistic_id: str, stat_name: str, unit: str, value_key: str):
            running_sum = 0.0
            last_ts = 0
            
            try:
                first_entry_dt = datetime.fromisoformat(sorted_usage_data[0]['startDate']).astimezone(self._utc_tz)
            except (KeyError, ValueError, TypeError, IndexError):
                first_entry_dt = dt_util.utcnow()

            prev_stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                datetime.fromtimestamp(0, tz=timezone.utc),
                first_entry_dt,
                {statistic_id},
                "hour",
                None,
                {"sum"}
            )
            
            if statistic_id in prev_stats and prev_stats[statistic_id]:
                last_stat = prev_stats[statistic_id][-1]
                running_sum = float(last_stat.get('sum', 0.0))
                last_ts = int(last_stat.get('start', 0))
                LOGGER.debug("[%s] Found baseline sum: %.2f at ts %d", self._fuel_type, running_sum, last_ts)

            stats_to_add = []
            for entry in sorted_usage_data:
                try:
                    val = float(entry[value_key])
                    start_dt_utc = datetime.fromisoformat(entry['startDate']).astimezone(self._utc_tz)
                    start_ts = int(start_dt_utc.timestamp())
                except (KeyError, ValueError, TypeError):
                    continue

                if force_overwrite or start_ts > last_ts:
                    running_sum += val
                    stats_to_add.append(StatisticData(
                        start=start_dt_utc,
                        state=round(val, 2),
                        sum=round(running_sum, 2)
                    ))
                    last_ts = start_ts

            if stats_to_add:
                mode_str = "Overwrite" if force_overwrite else "Append"
                LOGGER.info("  Importing %d '%s' statistics (Mode: %s, Final Sum: %.2f).", len(stats_to_add), stat_name, mode_str, running_sum)
                meta = StatisticMetaData(
                    has_mean=False,
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=stat_name,
                    source=DOMAIN,
                    statistic_id=statistic_id,
                    unit_of_measurement=unit,
                    unit_class=None,
                )
                async_add_external_statistics(self.hass, meta, stats_to_add)

        await _process_one_statistic(self._consumption_statistic_id, self._consumption_statistic_name, self._unit, 'kw')
        await _process_one_statistic(self._cost_statistic_id, self._cost_statistic_name, self._currency, 'costNZD')


# ── Generation Mix & Forecast ──────────────────────────────────────────────

class GenerationMixSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:leaf"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(key=SENSOR_KEY_GENERATION_MIX, name="Grid Generation Eco-Friendly")
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        self._nz_tz = ZoneInfo('Pacific/Auckland')

    @property
    def native_value(self) -> float | None:
        rt_mix = self.coordinator.data.get(DATA_API_GENERATION_MIX_REALTIME)
        if rt_mix and isinstance(rt_mix, dict):
            eco_pct = rt_mix.get("generationSourcesEcoFriendlyPercentage")
            if eco_pct is not None:
                return float(eco_pct)

        if not (gen_mix := self.coordinator.data.get(DATA_API_GENERATION_MIX)):
            return None
        now_nz = dt_util.now(self._nz_tz)
        today, hour = now_nz.strftime('%Y-%m-%d'), now_nz.hour
        for day in gen_mix:
            if day.get("Day") == today:
                for h in day.get("HourlyBreakdown", []):
                    if h.get("Hour") == hour:
                        return float(h.get("EcoFriendlyPercentage"))
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = {}
        if rt := self.coordinator.data.get(DATA_API_GENERATION_MIX_REALTIME):
            attrs["realtime"] = rt
        if fc := self.coordinator.data.get(DATA_API_GENERATION_MIX):
            attrs["forecast"] = fc
        return attrs


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
        f = self.coordinator.data.get(DATA_API_ELECTRICITY_FORECAST)
        if not f or not isinstance(f, dict):
            return False
        if "IcpForecasts" in f and f["IcpForecasts"]:
            return True
        return bool("Forecast" in f or "forecast" in f)

    @property
    def _today_forecast_data(self) -> dict | None:
        f = self.coordinator.data.get(DATA_API_ELECTRICITY_FORECAST)
        if not f or not isinstance(f, dict):
            return None
        if "IcpForecasts" in f and f["IcpForecasts"] and isinstance(f["IcpForecasts"], list):
            first_icp = f["IcpForecasts"][0]
            if isinstance(first_icp, dict) and "Forecast" in first_icp and isinstance(first_icp["Forecast"], list) and first_icp["Forecast"]:
                return first_icp["Forecast"][0]
        if "Forecast" in f and isinstance(f["Forecast"], list) and f["Forecast"]:
            return f["Forecast"][0]
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        t = self._today_forecast_data
        if not t or not isinstance(t, dict):
            return None
        attrs = {
            "prediction_low_kwh": t.get("PredictionLowInkWh") or t.get("predictionLowInkWh") or t.get("predictionLowKwh"),
            "prediction_high_kwh": t.get("PredictionHighInkWh") or t.get("predictionHighInkWh") or t.get("predictionHighKwh"),
            "prediction_low_cost": t.get("PredictionLowCost") or t.get("predictionLowCost"),
            "prediction_high_cost": t.get("PredictionHighCost") or t.get("predictionHighCost"),
        }
        f = self.coordinator.data.get(DATA_API_ELECTRICITY_FORECAST)
        if f and isinstance(f, dict):
            if "IcpForecasts" in f and f["IcpForecasts"] and isinstance(f["IcpForecasts"], list):
                attrs["daily_forecast"] = f["IcpForecasts"][0].get("Forecast")
            elif "Forecast" in f:
                attrs["daily_forecast"] = f.get("Forecast")
        return attrs


class ForecastUsageSensor(ForecastSensor):
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_FORECAST_USAGE, name="Today's Forecast Usage"))

    @property
    def native_value(self) -> float | None:
        t = self._today_forecast_data
        if not t or not isinstance(t, dict):
            return None
        return t.get("PredictionInkWh") or t.get("predictionInkWh") or t.get("predictionKwh")


class ForecastCostSensor(ForecastSensor):
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-usd"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_FORECAST_COST, name="Today's Forecast Cost"))

    @property
    def native_value(self) -> float | None:
        t = self._today_forecast_data
        if not t or not isinstance(t, dict):
            return None
        return t.get("PredictionCost") or t.get("predictionCost")


# ── EV Plan Sensors ────────────────────────────────────────────────────────

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
        return ev_data[-1] if ev_data and isinstance(ev_data, list) else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if (data := self._latest_day_data) and (rd := data.get("date")):
            try:
                return {"reading_date": datetime.fromisoformat(rd).strftime("%A, %d %B %Y")}
            except (ValueError, TypeError):
                return {"reading_date": rd}
        return None


class EVDayUsageSensor(GenesisEVPlanSensor):
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_DAY_USAGE, name="EV Plan Day Usage"))

    @property
    def native_value(self) -> float | None:
        return self._latest_day_data.get("kWhDay") if self._latest_day_data else None


class EVDayCostSensor(GenesisEVPlanSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_DAY_COST, name="EV Plan Day Cost"))

    @property
    def native_value(self) -> float | None:
        try:
            return float(self._latest_day_data.get("usageCostDay"))
        except (ValueError, TypeError):
            return None


class EVNightUsageSensor(GenesisEVPlanSensor):
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_NIGHT_USAGE, name="EV Plan Night Usage"))

    @property
    def native_value(self) -> float | None:
        return self._latest_day_data.get("kWhNight") if self._latest_day_data else None


class EVNightCostSensor(GenesisEVPlanSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_NIGHT_COST, name="EV Plan Night Cost"))

    @property
    def native_value(self) -> float | None:
        try:
            return float(self._latest_day_data.get("usageCostNight"))
        except (ValueError, TypeError):
            return None


class EVTotalSavingsSensor(GenesisEVPlanSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "NZD"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:piggy-bank-outline"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_EV_TOTAL_SAVINGS, name="EV Plan Savings"))

    @property
    def native_value(self) -> float | None:
        if not (d := self._latest_day_data):
            return None
        try:
            return round(float(d.get("costWithDayRate")) - float(d.get("usageCostNight")), 2)
        except (ValueError, TypeError, KeyError):
            return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = super().extra_state_attributes or {}
        if h := self.coordinator.data.get(DATA_API_EV_PLAN_USAGE):
            attrs["history"] = h
        return attrs


# ── Core Power Shout & Account Sensors ─────────────────────────────────────

class PowerShoutEligibilitySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(
            key=SENSOR_KEY_POWERSHOUT_ELIGIBLE,
            name="Power Shout Eligible",
            icon="mdi:lightning-bolt-outline"
        )
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"

    @property
    def native_value(self) -> bool | None:
        p = self.coordinator.data.get(DATA_API_POWERSHOUT_INFO)
        if not p or not isinstance(p, dict):
            return None
        eligible = p.get("eligibleBillingAccounts")
        return isinstance(eligible, list) and len(eligible) > 0


class PowerShoutBalanceSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(
            key=SENSOR_KEY_POWERSHOUT_BALANCE,
            name="Power Shout Balance",
            native_unit_of_measurement="hr",
            icon="mdi:timer-sand",
            state_class=SensorStateClass.MEASUREMENT
        )
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"

    @property
    def native_value(self) -> float | None:
        bal = self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE)
        if not bal or not isinstance(bal, dict):
            return None
        try:
            return float(bal.get("balance"))
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = {}
        if not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return None
        if o := self.coordinator.data.get(DATA_API_POWERSHOUT_OFFERS):
            if isinstance(o, dict):
                attrs["active_offers_count"] = len(o.get("activeOffers", []))
                attrs["active_offers"] = o.get("activeOffers", [])

        if e := self.coordinator.data.get(DATA_API_POWERSHOUT_EXPIRING):
            if isinstance(e, dict):
                if m := e.get("expiringHoursMessage"):
                    t_title = str(m.get("title", "")).strip()
                    substrings = m.get("titleSubstrings") or []
                    for idx, sub in enumerate(substrings):
                        if isinstance(sub, dict):
                            t_title = t_title.replace(f"{{{{{idx}}}}}", str(sub.get("text", "")))
                        elif isinstance(sub, str):
                            t_title = t_title.replace(f"{{{{{idx}}}}}", str(sub))
                    if t_title:
                        attrs["expiring_hours_message"] = t_title
                if t_tip := e.get("messageTooltip"):
                    desc = t_tip.get("description") if isinstance(t_tip, dict) else str(t_tip)
                    if desc and desc.strip():
                        attrs["expiring_hours_tooltip"] = desc.strip()
                if exp_list := e.get("expiringHours"):
                    attrs["expiring_hours_list"] = exp_list

        if b_data := self.coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS):
            if isinstance(b_data, dict):
                b_list = b_data.get("bookings", [])
                attrs["bookings"] = b_list
                u = sorted(
                    [x for x in b_list if isinstance(x, dict) and x.get("startDateTime") and datetime.fromisoformat(x["startDateTime"]).replace(tzinfo=timezone.utc) > dt_util.utcnow()],
                    key=lambda x: x["startDateTime"]
                )
                if u:
                    attrs["next_booking_start"] = u[0]["startDateTime"]

        if rec := self.coordinator.data.get(DATA_API_POWERSHOUT_RECOMMENDED_HOURS):
            if isinstance(rec, dict):
                rec_list = rec.get("recommendedHours", [])
                attrs["recommended_hours_count"] = len(rec_list)
                attrs["recommended_hours"] = rec_list
                if rec_list:
                    attrs["top_recommended_hour"] = rec_list[0]

        return attrs


class GenesisEnergyAccountSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(
            key=SENSOR_KEY_ACCOUNT_DETAILS,
            name="Account Details",
            icon="mdi:account-details"
        )
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"

    @property
    def native_value(self) -> str:
        return dt_util.utcnow().isoformat() if self.coordinator.last_update_success else "error"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return None
        k = [
            DATA_API_BILLING_PLANS, DATA_API_BILLING_SUMMARY, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS,
            DATA_API_WIDGET_BILLS_V2, DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
            DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT, DATA_API_WIDGET_ECO_TRACKER,
            DATA_API_WIDGET_DASHBOARD_LIST, DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
            DATA_API_POWERSHOUT_RECOMMENDED_HOURS
        ]
        attrs = {}
        for key in k:
            attr_name = key.replace("api_", "")
            data = self.coordinator.data.get(key)
            if data is None:
                continue
            if isinstance(data, (dict, list)):
                dumped = safe_json_dumps(data)
                attrs[attr_name] = dumped
            else:
                attrs[attr_name] = data
        return attrs


# ── Estimated Bill Sensors (Sidekick / Bills V2) ───────────────────────────

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
        if not super().available or not self.coordinator.data:
            return False
        return bool(self._get_sidekick_data())

    def _get_sidekick_data(self) -> dict:
        if not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return {}
        if (s := self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK)) and isinstance(s, dict):
            return s
        if (v2 := self.coordinator.data.get(DATA_API_WIDGET_BILLS_V2)) and isinstance(v2, dict):
            if (est := v2.get("billEstimated")) and isinstance(est, dict):
                return est
        return {}


class ElectricityUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_ELEC_USED, name="Genesis Bill - Electricity Used", state_class=SensorStateClass.TOTAL))

    @property
    def native_value(self) -> float | None:
        s_data = self._get_sidekick_data()
        supply_types = (s_data.get('supplyTypesArea') or {}).get('supplyTypes') or []
        for s in supply_types:
            if isinstance(s, dict) and s.get('type') in ['electricity', 'Electricity']:
                try:
                    return float(s.get('value'))
                except (ValueError, TypeError):
                    return None
        return 0.0


class GasUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_GAS_USED, name="Genesis Bill - Gas Used", state_class=SensorStateClass.TOTAL))

    @property
    def native_value(self) -> float | None:
        s_data = self._get_sidekick_data()
        supply_types = (s_data.get('supplyTypesArea') or {}).get('supplyTypes') or []
        for s in supply_types:
            if isinstance(s, dict) and s.get('type') in ['naturalGas', 'natural_gas', 'Gas', 'gas']:
                try:
                    return float(s.get('value'))
                except (ValueError, TypeError):
                    return None
        return 0.0


class TotalUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_TOTAL_USED, name="Genesis Bill - Total Used", state_class=SensorStateClass.TOTAL))

    @property
    def native_value(self) -> float | None:
        s_data = self._get_sidekick_data()
        val = (s_data.get('titleArea') or {}).get('value')
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        return None


class EstimatedTotalSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_TOTAL, name="Genesis Bill - Estimated Total"))

    @property
    def native_value(self) -> float | None:
        s_data = self._get_sidekick_data()
        t = (s_data.get('billArea') or {}).get('title')
        if t and '$' in t:
            try:
                return float(t.split('$')[1])
            except (ValueError, IndexError):
                return None
        return None


class EstimatedFutureUseSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator, SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_FUTURE, name="Genesis Bill - Estimated Future Use"))

    @property
    def native_value(self) -> float | None:
        s = self._get_sidekick_data()
        ev, uv = 0.0, 0.0
        t = (s.get('billArea') or {}).get('title')
        if t and '$' in t:
            try:
                ev = float(t.split('$')[1])
            except (ValueError, IndexError):
                pass
        val = (s.get('titleArea') or {}).get('value')
        if val is not None:
            try:
                uv = float(val)
            except (ValueError, TypeError):
                pass
        return round(max(0.0, ev - uv), 2)


# ── LPG Details Sensor ─────────────────────────────────────────────────────

class LPGDetailsSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:gas-cylinder"

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(key=SENSOR_KEY_LPG_DETAILS, name="LPG Details")
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{SENSOR_KEY_LPG_DETAILS}"

    @property
    def native_value(self) -> str:
        return dt_util.utcnow().isoformat() if self.coordinator.last_update_success else "error"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.coordinator.data or (data := self.coordinator.data.get(DATA_API_LPG_DETAILS)) is None:
            return None
        return {"data": safe_json_dumps(data)} if isinstance(data, (dict, list)) else {"data": data}
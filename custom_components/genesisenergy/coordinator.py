# custom_components/genesisenergy/coordinator.py
from datetime import datetime, timedelta, timezone
import asyncio
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.recorder import get_instance
from homeassistant.util import dt as dt_util


from .api import GenesisEnergyApi
from .exceptions import CannotConnect, InvalidAuth, ApiError
from .const import (
    DOMAIN, LOGGER, DEFAULT_SCAN_INTERVAL_HOURS, CONF_EMAIL, CONF_PASSWORD,
    DEVICE_MANUFACTURER, DEVICE_MODEL, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE,
    DATA_API_POWERSHOUT_INFO, DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS,
    DATA_API_POWERSHOUT_OFFERS, DATA_API_POWERSHOUT_EXPIRING, DATA_API_BILLING_PLANS,
    DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS, DATA_API_AGGREGATED_ELEC_BILL,
    ATTR_FUEL_TYPE, DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST,
    DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
    DATA_API_GENERATION_MIX, DATA_API_EV_PLAN_USAGE, DATA_API_ELECTRICITY_FORECAST,
    DATA_API_USAGE_BREAKDOWN, SENSOR_KEY_LPG_DETAILS, DATA_API_LPG_DETAILS
)

if TYPE_CHECKING:
    from .sensor import GenesisEnergyStatisticsSensor


class GenesisEnergyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, any]]):
    config_entry: ConfigEntry; api: GenesisEnergyApi; device_info: DeviceInfo
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry; self.api = GenesisEnergyApi(email=entry.data[CONF_EMAIL], password=entry.data[CONF_PASSWORD])
        device_name = self.config_entry.title
        self.device_info = DeviceInfo(identifiers={(DOMAIN, self.config_entry.entry_id)}, name=device_name, manufacturer=DEVICE_MANUFACTURER, model=f"{DEVICE_MODEL} (Polls every {DEFAULT_SCAN_INTERVAL_HOURS}h)", configuration_url="https://myaccount.genesisenergy.co.nz/")
        self.statistics_sensors: list["GenesisEnergyStatisticsSensor"] = []
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS))
    
    async def _async_update_data(self) -> dict[str, any]:
        try:
            return await self._async_fetch_all_data()
        except (InvalidAuth, CannotConnect, ApiError) as err: raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err: raise UpdateFailed(f"Unexpected error updating data: {err}") from err

    async def _async_fetch_all_data(self) -> dict[str, any]:
        """Fetch all data from the API in parallel."""
        days_for_regular_fetch = 4
        
        api_calls = {
            DATA_API_BILLING_PLANS: self.api.get_billing_plans(),
            DATA_API_ELECTRICITY_USAGE: self.api.get_energy_data(days_for_regular_fetch),
            DATA_API_EV_PLAN_USAGE: self.api.get_ev_plan_usage(),
            DATA_API_GAS_USAGE: self.api.get_gas_data(days_for_regular_fetch),
            DATA_API_POWERSHOUT_INFO: self.api.get_powershout_info(),
            DATA_API_POWERSHOUT_BALANCE: self.api.get_powershout_balance(),
            DATA_API_POWERSHOUT_BOOKINGS: self.api.get_powershout_bookings(),
            DATA_API_POWERSHOUT_OFFERS: self.api.get_powershout_offers(),
            DATA_API_POWERSHOUT_EXPIRING: self.api.get_powershout_expiring_hours(),
            DATA_API_WIDGET_HERO: self.api.get_widget_hero_info(),
            DATA_API_WIDGET_BILLS: self.api.get_widget_bill_summary(),
            DATA_API_WIDGET_PROPERTY_LIST: self.api.get_widget_property_list(),
            DATA_API_WIDGET_PROPERTY_SWITCHER: self.api.get_widget_property_switcher(),
            DATA_API_WIDGET_SIDEKICK: self.api.get_widget_sidekick(),
            DATA_API_WIDGET_DASHBOARD_POWERSHOUT: self.api.get_widget_dashboard_powershout(),
            DATA_API_WIDGET_ECO_TRACKER: self.api.get_widget_eco_tracker(),
            DATA_API_WIDGET_DASHBOARD_LIST: self.api.get_widget_dashboard_list(),
            DATA_API_WIDGET_ACTION_TILE_LIST: self.api.get_widget_action_tile_list(),
            DATA_API_NEXT_BEST_ACTION: self.api.get_next_best_action(),
            DATA_API_GENERATION_MIX: self.api.get_generation_mix(),
            DATA_API_ELECTRICITY_FORECAST: self.api.get_electricity_forecast(),
            DATA_API_USAGE_BREAKDOWN: self.api.get_usage_breakdown(),
        }
        
        results = await asyncio.gather(*api_calls.values(), return_exceptions=True)
        
        fetched_data = {}
        for key, result in zip(api_calls.keys(), results):
            if isinstance(result, Exception):
                LOGGER.info("Could not fetch data for %s. This may be expected. Error: %s", key, result)
                fetched_data[key] = None
            else:
                fetched_data[key] = result

        lpg_details = {}
        try:
            order_status = await self.api.get_lpg_order_status()
            if order_status and isinstance(order_status.get("billingAccountSites"), list):
                lpg_supply_points = [sp for site in order_status.get("billingAccountSites", []) for sp in site.get("supplyPoints", []) if sp.get("supplyAgreementId")]
                sa_ids = [sp["supplyAgreementId"] for sp in lpg_supply_points]
                
                if sa_ids:
                    history_results, summary_results = await asyncio.gather(
                        asyncio.gather(*[self.api.get_lpg_delivery_history(sa_id) for sa_id in sa_ids], return_exceptions=True),
                        asyncio.gather(*[self.api.get_lpg_delivery_summary(sa_id) for sa_id in sa_ids], return_exceptions=True)
                    )
                    histories_by_sa_id = {sa_id: res for sa_id, res in zip(sa_ids, history_results) if not isinstance(res, Exception)}
                    summaries_by_sa_id = {sa_id: res for sa_id, res in zip(sa_ids, summary_results) if not isinstance(res, Exception)}

                    for sp_data in lpg_supply_points:
                        sp_id = sp_data["id"]
                        sa_id = sp_data["supplyAgreementId"]
                        lpg_details[sp_id] = {
                            "order_status": sp_data,
                            "delivery_history": histories_by_sa_id.get(sa_id),
                            "delivery_summary": summaries_by_sa_id.get(sa_id)
                        }

        except Exception as err:
            if "supplyAgreementIds" in str(err):
                LOGGER.debug("Skipping LPG fetch — account has no LPG supply agreements.")
            else:
                LOGGER.warning("An error occurred during LPG data fetching: %s", err)

        fetched_data[DATA_API_LPG_DETAILS] = lpg_details
        if lpg_details:
            LOGGER.debug("Final processed LPG details payload: %s", lpg_details)
        else:
            LOGGER.debug("No LPG details to process (likely no LPG on account).")


        return fetched_data

    async def async_backfill_statistics_data(self, days_to_fetch: int, fuel_type: str, force_overwrite: bool = False) -> None:
        """
        Service to backfill historical statistics, intelligently fetching only missing days.
        """
        from .sensor import GenesisEnergyStatisticsSensor
        LOGGER.info(f"Starting historical backfill for '{fuel_type}' for the last {days_to_fetch} days...")
        
        process_elec, process_gas = "electricity" in [fuel_type, "both"], "gas" in [fuel_type, "both"]

        elec_sensor: GenesisEnergyStatisticsSensor | None = None
        gas_sensor: GenesisEnergyStatisticsSensor | None = None
        for sensor in self.statistics_sensors:
            if sensor._fuel_type == "Electricity":
                elec_sensor = sensor
            elif sensor._fuel_type == "Gas":
                gas_sensor = sensor
        
        LOGGER.info(f"Coordinator statistics_sensors currently: {self.statistics_sensors}")
        LOGGER.info(f"Detected Elec Sensor: {elec_sensor is not None}, Gas Sensor: {gas_sensor is not None}")

        async def _backfill_fuel(sensor: GenesisEnergyStatisticsSensor, is_elec: bool):
            """Core logic to find missing days and fetch data for a single fuel type."""
            fuel_name = "Electricity" if is_elec else "Gas"
            LOGGER.info(f"{fuel_name} backfill starting...")

            today = dt_util.now().date()
            start_date = today - timedelta(days=days_to_fetch - 1)
            all_desired_dates = {start_date + timedelta(days=x) for x in range(days_to_fetch)}
            
            dates_to_fetch = []
            
            if force_overwrite:
                LOGGER.debug(f"[{fuel_name}] Force overwrite is enabled. Will fetch for all days in the period.")
                dates_to_fetch = sorted(list(all_desired_dates))
            else:
                start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                existing_stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass, start_datetime, None, {sensor._consumption_statistic_id},
                    "day", None, {"sum"},
                )
                existing_dates = set()
                if sensor._consumption_statistic_id in existing_stats:
                    for stat in existing_stats[sensor._consumption_statistic_id]:
                        stat_date = datetime.fromtimestamp(stat['start'], tz=timezone.utc).date()
                        existing_dates.add(stat_date)

                LOGGER.info(f"[{fuel_name}] Found {len(existing_dates)} days with existing statistics in the last {days_to_fetch} days.")
                dates_to_fetch = sorted(list(all_desired_dates - existing_dates))

            if today in dates_to_fetch:
                LOGGER.debug(f"[{fuel_name}] Removing today ({today}) from the fetch list as its data is not yet final.")
                dates_to_fetch.remove(today)

            if not dates_to_fetch:
                LOGGER.info(f"[{fuel_name}] No missing past days found to backfill.")
                return

            all_fetched_data = []
            api_call = self.api.get_energy_data_for_period if is_elec else self.api.get_gas_data_for_period
            
            chunk_size = 4
            date_chunks = [dates_to_fetch[i:i + chunk_size] for i in range(0, len(dates_to_fetch), chunk_size)]

            for chunk in date_chunks:
                chunk_start_date = chunk[0].strftime("%Y-%m-%d")
                chunk_end_date = chunk[-1].strftime("%Y-%m-%d")
                LOGGER.info(f"  Fetching {fuel_name} chunk: {chunk_start_date} to {chunk_end_date}")
                try:
                    res = await api_call(chunk_start_date, chunk_end_date)
                    if res and 'usage' in res:
                        all_fetched_data.extend(res['usage'])
                    await asyncio.sleep(1) 
                except Exception as e:
                    LOGGER.error(f"Error fetching backfill chunk for {chunk_start_date} to {chunk_end_date}. Skipping this chunk. Error: {e}")

            if all_fetched_data:
                await sensor.async_process_statistics_data(all_fetched_data, force_overwrite, start_date=start_date)
            else:
                LOGGER.warning(f"[{fuel_name}] Attempted to fetch data but received no data from the API.")

        if process_elec and elec_sensor:
            await _backfill_fuel(elec_sensor, is_elec=True)
        if process_gas and gas_sensor:
            await _backfill_fuel(gas_sensor, is_elec=False)

        LOGGER.info(f"Historical backfill complete for '{fuel_type}' ✅")
# custom_components/genesisenergy/coordinator.py
from datetime import datetime, timedelta, timezone
import asyncio
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

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

class GenesisEnergyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, any]]):
    config_entry: ConfigEntry; api: GenesisEnergyApi; device_info: DeviceInfo
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry; self.api = GenesisEnergyApi(email=entry.data[CONF_EMAIL], password=entry.data[CONF_PASSWORD])
        device_name = self.config_entry.title
        self.device_info = DeviceInfo(identifiers={(DOMAIN, self.config_entry.entry_id)}, name=device_name, manufacturer=DEVICE_MANUFACTURER, model=f"{DEVICE_MODEL} (Polls every {DEFAULT_SCAN_INTERVAL_HOURS}h)", configuration_url="https://myaccount.genesisenergy.co.nz/")
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

    async def async_backfill_statistics_data(self, days_to_fetch: int, fuel_type: str) -> None:
        from .sensor import GenesisEnergyStatisticsSensor
        LOGGER.info(f"Starting historical backfill service for '{fuel_type}' for {days_to_fetch} days.")
        process_elec, process_gas = fuel_type in ["electricity", "both"], fuel_type in ["gas", "both"]
        elec_sensor: GenesisEnergyStatisticsSensor | None = None
        gas_sensor: GenesisEnergyStatisticsSensor | None = None
        registry = er.async_get(self.hass)
        for entity_id, entry in registry.entities.items():
            if entry.config_entry_id == self.config_entry.entry_id and "statistics_updater" in entry.unique_id:
                entity = self.hass.data.get("sensor", {}).get_entity(entity_id)
                if isinstance(entity, GenesisEnergyStatisticsSensor):
                    if entity._fuel_type == "Electricity": elec_sensor = entity
                    elif entity._fuel_type == "Gas": gas_sensor = entity
        
        async def _backfill_fuel(sensor: GenesisEnergyStatisticsSensor, is_elec: bool):
            all_data, chunk_days, chunk_delay = [], 4, 2
            today = datetime.now(timezone.utc).date()
            for i in range(0, days_to_fetch, chunk_days):
                end_date = today - timedelta(days=i)
                start_date = end_date - timedelta(days=chunk_days - 1)
                
                LOGGER.info(f"  Fetching {'Elec' if is_elec else 'Gas'} chunk: {start_date:%Y-%m-%d} to {end_date:%Y-%m-%d}")
                
                try:
                    res = await (self.api.get_energy_data_for_period if is_elec else self.api.get_gas_data_for_period)(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
                    if res and 'usage' in res: all_data.extend(res['usage'])
                    if (i + chunk_days) < days_to_fetch: await asyncio.sleep(chunk_delay)
                except Exception as e: LOGGER.error(f"Error fetching backfill chunk: {e}")
            if all_data:
                await sensor.async_process_statistics_data(all_data)

        if process_elec and elec_sensor:
            await _backfill_fuel(elec_sensor, is_elec=True)
        if process_gas and gas_sensor:
            await _backfill_fuel(gas_sensor, is_elec=False)
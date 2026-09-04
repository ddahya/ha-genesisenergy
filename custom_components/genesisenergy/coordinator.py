# custom_components/genesisenergy/coordinator.py
from datetime import datetime, timedelta, timezone
import asyncio
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
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
    DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS_V2,
    DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_GENERATION_MIX_REALTIME, DATA_API_EV_PLAN_USAGE,
    DATA_API_ELECTRICITY_FORECAST, DATA_API_LPG_DETAILS, DAILY_OVERWRITE_HOUR
)

if TYPE_CHECKING:
    from .sensor import GenesisEnergyStatisticsSensor


class GenesisEnergyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, any]]):
    config_entry: ConfigEntry
    api: GenesisEnergyApi
    device_info: DeviceInfo

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        self.api = GenesisEnergyApi(email=entry.data[CONF_EMAIL], password=entry.data[CONF_PASSWORD])
        device_name = self.config_entry.title
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=f"{DEVICE_MODEL} (Polls every {DEFAULT_SCAN_INTERVAL_HOURS}h)",
            configuration_url="https://myaccount.genesisenergy.co.nz/"
        )
        self.statistics_sensors: list["GenesisEnergyStatisticsSensor"] = []
        
        self.has_electricity: bool = True
        self.has_gas: bool = False
        self.has_ev_plan: bool = False
        self.has_powershout: bool = True
        self.has_lpg: bool = False
        self._services_detected: bool = False

        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS))
    
    async def _async_update_data(self) -> dict[str, any]:
        try:
            return await self._async_fetch_all_data()
        except (InvalidAuth, CannotConnect, ApiError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating data: {err}") from err

    def _detect_account_services(self, plans_data: dict | None) -> None:
        """Inspect billing plans to set active service channels."""
        if not plans_data or not isinstance(plans_data, dict):
            return

        has_elec, has_gas, has_ev = False, False, False
        for site in plans_data.get("billingAccountSites", []):
            for sp in site.get("supplyPoints", []):
                stype = sp.get("supplyType")
                plan_name = str(sp.get("plan", ""))
                if stype == "electricity":
                    has_elec = True
                    if "EV" in plan_name or "ev" in plan_name:
                        has_ev = True
                elif stype in ["naturalGas", "gas"]:
                    has_gas = True

        self.has_electricity = has_elec
        self.has_gas = has_gas
        self.has_ev_plan = has_ev
        self._services_detected = True
        LOGGER.info(
            "Account services configured — Electricity: %s, Natural Gas: %s, EV Plan: %s, Power Shout: %s",
            self.has_electricity, self.has_gas, self.has_ev_plan, self.has_powershout
        )

    async def _async_fetch_all_data(self) -> dict[str, any]:
        """Fetch targeted API data with concurrency bounds to prevent 502 drops."""
        days_for_regular_fetch = 4
        semaphore = asyncio.Semaphore(8)

        async def _bounded_call(coro):
            async with semaphore:
                return await coro

        api_calls = {}

        # 1. Base Core & Plan Calls
        api_calls[DATA_API_BILLING_PLANS] = self.api.get_billing_plans()
        api_calls[DATA_API_WIDGET_BILLS_V2] = self.api.get_widget_bill_summary_v2()
        api_calls[DATA_API_GENERATION_MIX_REALTIME] = self.api.get_generation_mix_realtime()
        api_calls[DATA_API_WIDGET_HERO] = self.api.get_widget_hero_info()
        api_calls[DATA_API_WIDGET_PROPERTY_LIST] = self.api.get_widget_property_list()
        api_calls[DATA_API_WIDGET_PROPERTY_SWITCHER] = self.api.get_widget_property_switcher()

        # 2. Electricity Calls
        if self.has_electricity or not self._services_detected:
            api_calls[DATA_API_ELECTRICITY_USAGE] = self.api.get_energy_data(days_for_regular_fetch)
            api_calls[DATA_API_ELECTRICITY_FORECAST] = self.api.get_electricity_forecast()

        # 3. EV Plan Calls
        if self.has_ev_plan or not self._services_detected:
            api_calls[DATA_API_EV_PLAN_USAGE] = self.api.get_ev_plan_usage()

        # 4. Natural Gas Calls
        if self.has_gas or not self._services_detected:
            api_calls[DATA_API_GAS_USAGE] = self.api.get_gas_data(days_for_regular_fetch)

        # 5. Power Shout Calls
        if self.has_powershout or not self._services_detected:
            api_calls[DATA_API_POWERSHOUT_INFO] = self.api.get_powershout_info()
            api_calls[DATA_API_POWERSHOUT_BALANCE] = self.api.get_powershout_balance()
            api_calls[DATA_API_POWERSHOUT_OFFERS] = self.api.get_powershout_offers()
            api_calls[DATA_API_POWERSHOUT_EXPIRING] = self.api.get_powershout_expiring_hours()
            api_calls[DATA_API_POWERSHOUT_BOOKINGS] = self.api.get_powershout_bookings()
            api_calls[DATA_API_WIDGET_DASHBOARD_POWERSHOUT] = self.api.get_widget_dashboard_powershout()

        tasks = [asyncio.create_task(_bounded_call(coro)) for coro in api_calls.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        fetched_data = dict(self.data or {})

        for key, result in zip(api_calls.keys(), results):
            if isinstance(result, Exception):
                LOGGER.debug("Could not fetch data for %s: %s", key, result)
            else:
                fetched_data[key] = result

        if DATA_API_BILLING_PLANS in fetched_data:
            self._detect_account_services(fetched_data.get(DATA_API_BILLING_PLANS))

        # Backward compatibility for sidekick sensors
        bill_v2 = fetched_data.get(DATA_API_WIDGET_BILLS_V2)
        if bill_v2 and isinstance(bill_v2, dict) and bill_v2.get("billEstimated"):
            fetched_data[DATA_API_WIDGET_SIDEKICK] = bill_v2.get("billEstimated")

        # LPG handling
        if self.has_lpg or not self._services_detected:
            lpg_details = {}
            try:
                order_status = await self.api.get_lpg_order_status()
                if order_status and isinstance(order_status.get("billingAccountSites"), list):
                    lpg_supply_points = [
                        sp for site in order_status.get("billingAccountSites", [])
                        for sp in site.get("supplyPoints", [])
                        if sp.get("supplyAgreementId")
                    ]
                    sa_ids = [sp["supplyAgreementId"] for sp in lpg_supply_points]
                    
                    if sa_ids:
                        self.has_lpg = True
                        history_results, summary_results = await asyncio.gather(
                            asyncio.gather(*[self.api.get_lpg_delivery_history(sa_id) for sa_id in sa_ids], return_exceptions=True),
                            asyncio.gather(*[self.api.get_lpg_delivery_summary(sa_id) for sa_id in sa_ids], return_exceptions=True)
                        )
                        histories = {sa_id: res for sa_id, res in zip(sa_ids, history_results) if not isinstance(res, Exception)}
                        summaries = {sa_id: res for sa_id, res in zip(sa_ids, summary_results) if not isinstance(res, Exception)}

                        for sp_data in lpg_supply_points:
                            sp_id = sp_data["id"]
                            sa_id = sp_data["supplyAgreementId"]
                            lpg_details[sp_id] = {
                                "order_status": sp_data,
                                "delivery_history": histories.get(sa_id),
                                "delivery_summary": summaries.get(sa_id)
                            }
                    else:
                        self.has_lpg = False
            except Exception as err:
                if "supplyAgreementIds" in str(err):
                    self.has_lpg = False
                    LOGGER.debug("Skipping LPG fetch — account has no LPG supply agreements.")
                else:
                    LOGGER.warning("An error occurred during LPG data fetching: %s", err)

            fetched_data[DATA_API_LPG_DETAILS] = lpg_details

        return fetched_data

    async def async_backfill_statistics_data(self, days_to_fetch: int, fuel_type: str, force_overwrite: bool = False) -> None:
        """Service to backfill historical statistics."""
        LOGGER.info("Starting historical backfill for '%s' for the last %d days...", fuel_type, days_to_fetch)
        process_elec = fuel_type in ["electricity", "both"]
        process_gas = fuel_type in ["gas", "both"]

        elec_sensor = None
        gas_sensor = None
        for sensor in self.statistics_sensors:
            if sensor._fuel_type == "Electricity":
                elec_sensor = sensor
            elif sensor._fuel_type == "Gas":
                gas_sensor = sensor

        async def _backfill_fuel(sensor, is_elec: bool):
            fuel_name = "Electricity" if is_elec else "Gas"
            LOGGER.info("%s backfill starting...", fuel_name)

            today = dt_util.now().date()
            start_date = today - timedelta(days=days_to_fetch - 1)
            all_desired_dates = {start_date + timedelta(days=x) for x in range(days_to_fetch)}
            
            if force_overwrite:
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
                dates_to_fetch = sorted(list(all_desired_dates - existing_dates))

            # Exclude today
            if today in dates_to_fetch:
                dates_to_fetch.remove(today)

            # If running before 1:00 PM (13:00), also exclude yesterday as Genesis data is not yet finalized
            yesterday = today - timedelta(days=1)
            if dt_util.now().hour < DAILY_OVERWRITE_HOUR and yesterday in dates_to_fetch:
                LOGGER.debug("[%s] Removing yesterday (%s) from backfill list — data not finalized until after 1:00 PM.", fuel_name, yesterday)
                dates_to_fetch.remove(yesterday)

            if not dates_to_fetch:
                LOGGER.info("[%s] No missing past days found to backfill.", fuel_name)
                return

            all_fetched_data = []
            api_call = self.api.get_energy_data_for_period if is_elec else self.api.get_gas_data_for_period
            
            chunk_size = 4
            date_chunks = [dates_to_fetch[i:i + chunk_size] for i in range(0, len(dates_to_fetch), chunk_size)]

            for chunk in date_chunks:
                chunk_start_date = chunk[0].strftime("%Y-%m-%d")
                chunk_end_date = chunk[-1].strftime("%Y-%m-%d")
                LOGGER.info("  Fetching %s chunk: %s to %s", fuel_name, chunk_start_date, chunk_end_date)
                try:
                    res = await api_call(chunk_start_date, chunk_end_date)
                    if res and 'usage' in res:
                        all_fetched_data.extend(res['usage'])
                    await asyncio.sleep(0.5) 
                except Exception as e:
                    LOGGER.error("Error fetching backfill chunk for %s to %s: %s", chunk_start_date, chunk_end_date, e)

            if all_fetched_data:
                await sensor.async_process_statistics_data(all_fetched_data, force_overwrite, start_date=start_date)

        if process_elec and elec_sensor:
            await _backfill_fuel(elec_sensor, is_elec=True)
        if process_gas and gas_sensor:
            await _backfill_fuel(gas_sensor, is_elec=False)

        LOGGER.info("Historical backfill complete for '%s' ✅", fuel_type)
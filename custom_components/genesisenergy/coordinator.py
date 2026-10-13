# custom_components/genesisenergy/coordinator.py

from datetime import datetime, timedelta, timezone
import asyncio
from typing import TYPE_CHECKING, Any, Iterable
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.recorder import get_instance
from homeassistant.util import dt as dt_util

from .api import GenesisEnergyApi
from .exceptions import CannotConnect, InvalidAuth, ApiError
from .const import (
    DOMAIN, LOGGER, DEFAULT_SCAN_INTERVAL_HOURS, CONF_EMAIL, CONF_PASSWORD, CONF_REFRESH_TOKEN,
    DEVICE_MANUFACTURER, DEVICE_MODEL, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE,
    DATA_API_POWERSHOUT_INFO, DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS,
    DATA_API_POWERSHOUT_OFFERS, DATA_API_POWERSHOUT_EXPIRING, DATA_API_POWERSHOUT_RECOMMENDED_HOURS,
    DATA_API_BILLING_PLANS, DATA_API_BILLING_SUMMARY, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS_V2,
    DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_GENERATION_MIX_REALTIME, DATA_API_EV_PLAN_USAGE,
    DATA_API_ELECTRICITY_FORECAST, DATA_API_LPG_DETAILS, DAILY_OVERWRITE_HOUR,
    REDEEMED_STORE_VERSION, REDEEMED_KEEP_DAYS, USAGE_VAULT_VERSION
)

if TYPE_CHECKING:
    from .sensor import GenesisEnergyStatisticsSensor


class GenesisEnergyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: ConfigEntry
    api: GenesisEnergyApi
    device_info: DeviceInfo

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        self._current_options = dict(entry.options)
        self.usage_cache: dict[str, Any] = {}
        self._prefetched: bool = False


        self._redeemed_store: Store = Store(
            hass, REDEEMED_STORE_VERSION, f"{DOMAIN}_redeemed_hours_{entry.entry_id}"
        )
        self._redeemed_hours: set[str] | None = None

        self._vault_store: Store = Store(
            hass, USAGE_VAULT_VERSION, f"{DOMAIN}_usage_vault_{entry.entry_id}"
        )
        self._vault_data: dict[str, dict[str, Any]] | None = None

        def _on_token_updated(new_refresh_token: str):
            """Persist rotated 90-day refresh token quietly without triggering a reload."""
            new_data = dict(self.config_entry.data)
            new_data[CONF_REFRESH_TOKEN] = new_refresh_token
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            LOGGER.debug("Persisted newly rotated 90-day refresh token into config entry.")

        self.api = GenesisEnergyApi(
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            token_update_callback=_on_token_updated
        )
        
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

    async def _async_redeemed_hours(self) -> set[str]:
        """Return past hours redeemed through this integration."""
        if self._redeemed_hours is None:
            stored = await self._redeemed_store.async_load()
            hours = stored.get("hours") if isinstance(stored, dict) else None
            self._redeemed_hours = set(hours) if isinstance(hours, list) else set()
        return self._redeemed_hours

    async def async_record_redeemed(self, starts: Iterable[str]) -> None:
        """Record redeemed past hours so they leave the ranked list immediately."""
        hours = await self._async_redeemed_hours()
        added = {str(val).replace("Z", "").split(".")[0] for val in starts if val}
        if not added:
            return
        hours.update(added)
        cutoff = (dt_util.now().date() - timedelta(days=REDEEMED_KEEP_DAYS)).isoformat()
        self._redeemed_hours = {v for v in hours if v[:10] >= cutoff}
        await self._redeemed_store.async_save({"hours": sorted(list(self._redeemed_hours))})
        LOGGER.debug("Recorded %d redeemed hours to local store (total stored: %d)", len(added), len(self._redeemed_hours))

    async def _async_load_vault(self) -> dict[str, dict[str, Any]]:
        """Load the multi-year usage vault from disk."""
        if self._vault_data is None:
            stored = await self._vault_store.async_load()
            if isinstance(stored, dict):
                self._vault_data = {
                    "electricity": stored.get("electricity", {}),
                    "gas": stored.get("gas", {}),
                    "ev": stored.get("ev", {}),
                }
            else:
                self._vault_data = {"electricity": {}, "gas": {}, "ev": {}}
        return self._vault_data

    async def async_save_usage_to_vault(self, fuel: str, items: list[dict[str, Any]]) -> None:
        """Merge incoming daily usage items into the permanent vault."""
        if not items or not isinstance(items, list):
            return
        vault = await self._async_load_vault()
        fuel_key = "gas" if fuel in ["gas", "naturalGas", "natural_gas"] else ("ev" if fuel == "ev" else "electricity")
        if fuel_key not in vault:
            vault[fuel_key] = {}

        updated = False
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_date = item.get("startDate") or item.get("date")
            if not raw_date:
                continue
            day_key = str(raw_date)[:10]
            vault[fuel_key][day_key] = item
            updated = True

        if updated:
            await self._vault_store.async_save(vault)
            LOGGER.debug("Vault: Archived %d days for %s (total days stored: %d)", len(items), fuel_key, len(vault[fuel_key]))

    def get_vault_days(self, fuel: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Retrieve sorted daily records from vault between start_date and end_date."""
        if self._vault_data is None:
            return []
        fuel_key = "gas" if fuel in ["gas", "naturalGas", "natural_gas"] else ("ev" if fuel == "ev" else "electricity")
        fuel_vault = self._vault_data.get(fuel_key, {})

        start_key = str(start_date)[:10]
        end_key = str(end_date)[:10]
        matching = [
            item for day_key, item in fuel_vault.items()
            if start_key <= day_key <= end_key
        ]
        matching.sort(key=lambda x: str(x.get("startDate") or x.get("date") or ""))
        return matching
    
    def _booked_hour_starts(self, bookings_data: Any) -> set[str]:
        """Return timestamps already covered by existing bookings."""
        if not isinstance(bookings_data, dict):
            return set()
        bookings = bookings_data.get("bookings")
        if not isinstance(bookings, list):
            return set()
        starts = set()
        for b in bookings:
            if isinstance(b, dict) and b.get("startDateTime"):
                s = str(b["startDateTime"]).replace("Z", "").split(".")[0]
                starts.add(s)
                try:
                    dur = max(1, int(float(b.get("duration") or 1)))
                    dt = datetime.fromisoformat(s)
                    for offset in range(dur):
                        starts.add((dt + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%S"))
                        starts.add((dt + timedelta(hours=offset)).strftime("%Y-%m-%d %H:%M:%S"))
                except Exception:
                    pass
        return starts

    def get_loyalty_account_id(self) -> str | None:
        """Extract the loyalty account ID required by Genesis for booking operations."""
        ps_info = self.data.get(DATA_API_POWERSHOUT_INFO) if self.data else None
        if ps_info and isinstance(ps_info, dict):
            return ps_info.get("loyaltyAccountId")
        return None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._async_load_vault()
            data = await self._async_fetch_all_data()
            self.hass.async_create_task(self.async_prefetch_current_year_usage())
            return data
        except (InvalidAuth, CannotConnect, ApiError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating data: {err}") from err

    async def async_prefetch_current_year_usage(self) -> None:
        """Background task to pre-fetch current year monthly & current month daily data for instant card display."""
        now = dt_util.now()
        year = now.year
        month = now.month
        
        m_start = f"{year}-01-01"
        m_end = f"{year}-12-31"

        d_start = f"{year}-{month:02d}-01"
        d_end = now.strftime("%Y-%m-%d")

        LOGGER.debug("Starting background pre-fetch of current year usage data...")
        await asyncio.sleep(2)

        tasks = [
            ("elec_monthly", self.api.get_energy_data_for_period, m_start, m_end, "MONTHLY"),
            ("elec_daily", self.api.get_energy_data_for_period, d_start, d_end, "DAILY"),
        ]

        if self.has_gas:
            tasks.append(("gas_monthly", self.api.get_gas_data_for_period, m_start, m_end, "MONTHLY"))
            tasks.append(("gas_daily", self.api.get_gas_data_for_period, d_start, d_end, "DAILY"))

        for key, coro, *args in tasks:
            try:
                res = await coro(*args)
                if res and isinstance(res, dict) and "usage" in res:
                    fuel = "gas" if "gas" in key else "electricity"
                    gran = "MONTHLY" if "monthly" in key else "DAILY"
                    cache_key = f"{fuel}_{gran}_{args[0]}_{args[1]}"
                    usage_list = res.get("usage", [])
                    self.usage_cache[cache_key] = usage_list
                    self.usage_cache[f"{fuel}_{gran}_current"] = usage_list
                    if gran == "DAILY" and usage_list:
                        self.hass.async_create_task(self.async_save_usage_to_vault(fuel, usage_list))
                    LOGGER.debug("Pre-fetched and cached %s data (%d items)", key, len(usage_list))
                
                await asyncio.sleep(0.4)
            except Exception as e:
                LOGGER.debug("Background pre-fetch skipped for %s: %s", key, e)

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

    async def _async_fetch_all_data(self) -> dict[str, Any]:
        """Fetch targeted API data with concurrency bounds to prevent 502 drops."""
        days_for_regular_fetch = 4
        semaphore = asyncio.Semaphore(8)

        async def _fetch_task(key, coro_fn, *args, **kwargs):
            async with semaphore:
                try:
                    return key, await coro_fn(*args, **kwargs)
                except Exception as err:
                    LOGGER.debug("Could not fetch data for %s: %s", key, err)
                    return key, None

        tasks = []

        # 1. Base Core, Summary & Plan Calls
        tasks.append(_fetch_task(DATA_API_BILLING_PLANS, self.api.get_billing_plans))
        tasks.append(_fetch_task(DATA_API_BILLING_SUMMARY, self.api.get_billing_summary))
        tasks.append(_fetch_task(DATA_API_WIDGET_BILLS_V2, self.api.get_widget_bill_summary_v2))
        tasks.append(_fetch_task(DATA_API_GENERATION_MIX_REALTIME, self.api.get_generation_mix_realtime))
        tasks.append(_fetch_task(DATA_API_WIDGET_HERO, self.api.get_widget_hero_info))
        tasks.append(_fetch_task(DATA_API_WIDGET_PROPERTY_LIST, self.api.get_widget_property_list))
        tasks.append(_fetch_task(DATA_API_WIDGET_PROPERTY_SWITCHER, self.api.get_widget_property_switcher))

        # 2. Electricity Calls
        if self.has_electricity or not self._services_detected:
            tasks.append(_fetch_task(DATA_API_ELECTRICITY_USAGE, self.api.get_energy_data, days_for_regular_fetch))
            tasks.append(_fetch_task(DATA_API_ELECTRICITY_FORECAST, self.api.get_electricity_forecast))

        # 3. EV Plan Calls
        if self.has_ev_plan or not self._services_detected:
            tasks.append(_fetch_task(DATA_API_EV_PLAN_USAGE, self.api.get_ev_plan_usage))

        # 4. Natural Gas Calls
        if self.has_gas or not self._services_detected:
            tasks.append(_fetch_task(DATA_API_GAS_USAGE, self.api.get_gas_data, days_for_regular_fetch))

        # 5. Power Shout Calls
        if self.has_powershout or not self._services_detected:
            tasks.append(_fetch_task(DATA_API_POWERSHOUT_INFO, self.api.get_powershout_info))
            tasks.append(_fetch_task(DATA_API_POWERSHOUT_BALANCE, self.api.get_powershout_balance))
            tasks.append(_fetch_task(DATA_API_POWERSHOUT_OFFERS, self.api.get_powershout_offers))
            tasks.append(_fetch_task(DATA_API_POWERSHOUT_EXPIRING, self.api.get_powershout_expiring_hours))
            tasks.append(_fetch_task(DATA_API_POWERSHOUT_BOOKINGS, self.api.get_powershout_bookings))
            tasks.append(_fetch_task(DATA_API_WIDGET_DASHBOARD_POWERSHOUT, self.api.get_widget_dashboard_powershout))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        fetched_data = dict(self.data or {})

        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                key, val = result
                if val is not None:
                    fetched_data[key] = val

        if DATA_API_BILLING_PLANS in fetched_data:
            self._detect_account_services(fetched_data.get(DATA_API_BILLING_PLANS))

        if DATA_API_EV_PLAN_USAGE in fetched_data:
            ev_items = fetched_data[DATA_API_EV_PLAN_USAGE]
            if isinstance(ev_items, list) and ev_items:
                self.hass.async_create_task(self.async_save_usage_to_vault("ev", ev_items))

        bill_v2 = fetched_data.get(DATA_API_WIDGET_BILLS_V2)
        if bill_v2 and isinstance(bill_v2, dict) and bill_v2.get("billEstimated"):
            fetched_data[DATA_API_WIDGET_SIDEKICK] = bill_v2.get("billEstimated")

        # 6. Fetch & Filter Top Recommended Past Power Shout Hours
        ps_info = fetched_data.get(DATA_API_POWERSHOUT_INFO)
        if ps_info and isinstance(ps_info, dict):
            loyalty_id = ps_info.get("loyaltyAccountId")
            eligible_accounts = ps_info.get("eligibleBillingAccounts", [])
            
            selected_account_id = None
            selected_sp_id = None
            selected_sa_id = None
            
            for acc in eligible_accounts:
                acc_id = acc.get("id")
                for site in acc.get("billingAccountSites", []):
                    if site.get("isSelectedSite") is True:
                        sps = site.get("supplyPoints", [])
                        if sps:
                            selected_account_id = acc_id
                            selected_sp_id = sps[0].get("id")
                            selected_sa_id = sps[0].get("supplyAgreementId")
                            break
                if selected_sp_id:
                    break

            if not selected_sp_id and eligible_accounts:
                try:
                    selected_account_id = eligible_accounts[0].get("id")
                    first_sp = eligible_accounts[0]["billingAccountSites"][0]["supplyPoints"][0]
                    selected_sp_id = first_sp.get("id")
                    selected_sa_id = first_sp.get("supplyAgreementId")
                except (IndexError, KeyError, TypeError):
                    pass

            if loyalty_id and selected_account_id and selected_sp_id and selected_sa_id:
                try:
                    rec_hours = await self.api.get_powershout_recommended_hours(
                        account_id=loyalty_id,
                        billing_account_id=selected_account_id,
                        icp_number=selected_sp_id,
                        supply_agreement_id=selected_sa_id
                    )
                    
                    if rec_hours and isinstance(rec_hours, dict) and "recommendedHours" in rec_hours:
                        redeemed = await self._async_redeemed_hours()
                        booked = self._booked_hour_starts(fetched_data.get(DATA_API_POWERSHOUT_BOOKINGS))
                        filtered = []
                        for r in rec_hours.get("recommendedHours", []):
                            dt_str = str(r.get("dateTime", "")).replace("Z", "").split(".")[0]
                            dt_space = dt_str.replace("T", " ")
                            if dt_str in redeemed or dt_space in redeemed or dt_str in booked or dt_space in booked:
                                continue
                            filtered.append(r)
                        rec_hours = dict(rec_hours)
                        rec_hours["recommendedHours"] = filtered

                    fetched_data[DATA_API_POWERSHOUT_RECOMMENDED_HOURS] = rec_hours
                except Exception as err:
                    LOGGER.debug("Could not fetch recommended Power Shout hours: %s", err)
                    fetched_data[DATA_API_POWERSHOUT_RECOMMENDED_HOURS] = None

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

            if today in dates_to_fetch:
                dates_to_fetch.remove(today)

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
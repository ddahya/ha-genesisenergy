# custom_components/genesisenergy/__init__.py

from functools import partial
from pathlib import Path
import asyncio
import voluptuous as vol
from zoneinfo import ZoneInfo
from datetime import timedelta, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.components.persistent_notification import async_create
from homeassistant.components.http import StaticPathConfig
import homeassistant.components.lovelace as lovelace_component
from homeassistant.components import websocket_api
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, PLATFORMS, LOGGER, CONF_EMAIL,
    SERVICE_ADD_POWERSHOUT_BOOKING, SERVICE_CANCEL_POWERSHOUT_BOOKING,
    ATTR_START_DATETIME, ATTR_DURATION_HOURS, ATTR_BOOKING_ID,
    DATA_API_POWERSHOUT_INFO, DATA_API_POWERSHOUT_OFFERS,
    SERVICE_BACKFILL_STATISTICS, ATTR_DAYS_TO_FETCH, ATTR_FUEL_TYPE,
    SERVICE_FORCE_UPDATE, DATA_API_BILLING_PLANS,
    SERVICE_ACCEPT_POWERSHOUT_OFFER, ATTR_OFFER_ID
)
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .exceptions import CannotConnect, InvalidAuth

_WWW_PATH_REGISTERED: bool = False
_WS_COMMAND_REGISTERED: bool = False
_CARD_FILENAME = "powershout-card.js"
ATTR_FORCE_OVERWRITE = "force_overwrite"

SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING = vol.Schema({
    vol.Required(ATTR_START_DATETIME): cv.datetime,
    vol.Required(ATTR_DURATION_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
})

SERVICE_SCHEMA_CANCEL_POWERSHOUT_BOOKING = vol.Schema({
    vol.Required(ATTR_BOOKING_ID): cv.string,
})

SERVICE_SCHEMA_ACCEPT_POWERSHOUT_OFFER = vol.Schema({
    vol.Required(ATTR_OFFER_ID): cv.string,
})

SERVICE_SCHEMA_BACKFILL_STATISTICS = vol.Schema({
    vol.Required(ATTR_DAYS_TO_FETCH): vol.All(vol.Coerce(int), vol.Range(min=1, max=730)),
    vol.Required(ATTR_FUEL_TYPE): vol.In(["electricity", "gas", "both"]),
    vol.Required(ATTR_FORCE_OVERWRITE, default=False): cv.boolean,
})

SERVICE_SCHEMA_FORCE_UPDATE = vol.Schema({
    vol.Required(ATTR_FUEL_TYPE): vol.In(["electricity", "gas", "both"]),
})

async def _async_register_lovelace_card(hass: HomeAssistant) -> None:
    """Register the Power Shout card as a Lovelace resource in storage mode."""
    www_path = Path(__file__).parent / "www"
    card_path = www_path / _CARD_FILENAME
    if not card_path.is_file():
        return

    mtime = int(card_path.stat().st_mtime)
    url = f"/{DOMAIN}/{_CARD_FILENAME}?v={mtime}"

    lovelace_data = hass.data.get(lovelace_component.DOMAIN)
    if lovelace_data is None:
        return
    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        return

    try:
        items = resources.async_items()
        for item in items:
            item_url = item.get("url", "")
            if _CARD_FILENAME in item_url:
                if item_url != url:
                    await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                    LOGGER.info("Updated Lovelace resource: %s", url)
                return
        await resources.async_create_item({"res_type": "module", "url": url})
        LOGGER.info("Auto-registered Lovelace resource: %s", url)
    except Exception as exc:
        LOGGER.debug("Could not auto-register Lovelace resource: %s", exc)

@websocket_api.websocket_command({
    vol.Required("type"): "genesisenergy/usage",
    vol.Required("fuel"): vol.In(["electricity", "gas", "ev"]),
    vol.Required("start_date"): cv.string,
    vol.Required("end_date"): cv.string,
    vol.Required("interval_type"): vol.In(["MONTHLY", "DAILY", "HOURLY"]),
})
@websocket_api.async_response
async def ws_get_usage(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Fetch on-demand usage directly from Genesis API with caching & date bounds protection."""
    domain_data = hass.data.get(DOMAIN, {})
    coordinator = None
    for item in domain_data.values():
        if isinstance(item, GenesisEnergyDataUpdateCoordinator) and hasattr(item, "api"):
            coordinator = item
            break

    if not coordinator:
        connection.send_error(msg["id"], "not_found", "Genesis Energy coordinator not found")
        return

    fuel = msg["fuel"]
    start_date = msg["start_date"]
    end_date = msg["end_date"]
    interval = msg["interval_type"]

    cache_key = f"{fuel}_{interval}_{start_date}_{end_date}"
    if cache_key in coordinator.usage_cache:
        connection.send_result(msg["id"], {"usage": coordinator.usage_cache[cache_key]})
        return

    today = dt_util.now().date()
    today_str = today.strftime("%Y-%m-%d")

    if interval == "MONTHLY":
        year = start_date[:4]
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
    else:
        if start_date > today_str:
            connection.send_result(msg["id"], {"usage": []})
            return
        if end_date > today_str:
            end_date = today_str

    try:
        if fuel == "electricity":
            data = await coordinator.api.get_energy_data_for_period(start_date, end_date, interval_type=interval)
        elif fuel == "gas":
            data = await coordinator.api.get_gas_data_for_period(start_date, end_date, interval_type=interval)
        else:
            data = await coordinator.api.get_ev_plan_usage()

        usage_list = data.get("usage", []) if isinstance(data, dict) else []
        coordinator.usage_cache[cache_key] = usage_list
        connection.send_result(msg["id"], {"usage": usage_list})
    except Exception as err:
        LOGGER.error("Error fetching Genesis usage via websocket: %s", err)
        connection.send_error(msg["id"], "api_error", str(err))

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Genesis Energy from a config entry."""
    LOGGER.info(f"Setting up Genesis Energy for entry: {entry.title}...")

    hass.data.setdefault(DOMAIN, {})
    coordinator = GenesisEnergyDataUpdateCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        LOGGER.error(f"Initial data fetch failed for {entry.title}. Retrying setup.")
        raise
    except Exception as e:
        LOGGER.error(f"Unexpected error during first refresh for {entry.title}: {e}", exc_info=True)
        raise ConfigEntryNotReady(f"Initial data fetch failed with an unexpected error: {e}") from e

    LOGGER.info("Setting up platforms...")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.info("Setting up platforms...✅")

    global _WS_COMMAND_REGISTERED
    if not _WS_COMMAND_REGISTERED:
        websocket_api.async_register_command(hass, ws_get_usage)
        _WS_COMMAND_REGISTERED = True
        LOGGER.info("Registered WebSocket command genesisenergy/usage ✅")

    global _WWW_PATH_REGISTERED
    if not _WWW_PATH_REGISTERED:
        www_path = Path(__file__).parent / "www"
        if www_path.is_dir():
            await hass.http.async_register_static_paths(
                [StaticPathConfig(f"/{DOMAIN}", str(www_path), cache_headers=False)]
            )
            LOGGER.info("Registered static path /%s → %s", DOMAIN, www_path)
        _WWW_PATH_REGISTERED = True

    @callback
    def _schedule_card_registration(_event=None) -> None:
        hass.async_create_task(_async_register_lovelace_card(hass))

    if hass.is_running:
        _schedule_card_registration()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_card_registration)

    def get_available_services(coord: GenesisEnergyDataUpdateCoordinator) -> tuple[bool, bool]:
        has_elec = getattr(coord, "has_electricity", True)
        has_gas = getattr(coord, "has_gas", False)
        for s in getattr(coord, "statistics_sensors", []):
            if getattr(s, "_fuel_type", "") == "Electricity": has_elec = True
            elif getattr(s, "_fuel_type", "") == "Gas": has_gas = True
        return has_elec, has_gas

    @callback
    async def async_add_powershout_booking_service(call: ServiceCall) -> None:
        start_dt_raw = call.data[ATTR_START_DATETIME]
        requested_duration = call.data[ATTR_DURATION_HOURS]
        base_start_dt = start_dt_raw.replace(minute=0, second=0, microsecond=0)
        
        ps_info = coordinator.data.get(DATA_API_POWERSHOUT_INFO)
        if not ps_info or not isinstance(ps_info, dict):
            LOGGER.error("Could not book Power Shout: Power Shout data is unavailable.")
            return

        supply_agreement_id, supply_point_id, loyalty_account_id = None, None, None
        try:
            loyalty_account_id = ps_info.get("loyaltyAccountId")
            supply_point_data = None
            for account in ps_info.get("eligibleBillingAccounts", []):
                for site in account.get("billingAccountSites", []):
                    if site.get("isSelectedSite") is True:
                        sps = site.get("supplyPoints", [])
                        if sps:
                            supply_point_data = sps[0]
                            break
                if supply_point_data:
                    break
            
            if not supply_point_data:
                try:
                    supply_point_data = ps_info["eligibleBillingAccounts"][0]["billingAccountSites"][0]["supplyPoints"][0]
                except (KeyError, IndexError, TypeError):
                    supply_point_data = None
            
            if supply_point_data:
                supply_agreement_id = supply_point_data.get("supplyAgreementId")
                supply_point_id = supply_point_data.get("id")
        except (KeyError, IndexError, TypeError, AttributeError):
            pass

        if not all([supply_agreement_id, supply_point_id, loyalty_account_id]):
            LOGGER.error("Could not book Power Shout: Required IDs are missing.")
            async_create(
                hass, "Could not book Power Shout: Required information is missing.",
                title="Genesis Energy Power Shout Failed", notification_id="genesis_powershout_error"
            )
            return

        successful_bookings = 0
        booked_timestamps = []
        try:
            selected_date_for_vouchers = base_start_dt.astimezone(ZoneInfo("UTC")).strftime('%Y-%m-%dT00:00:00.000Z')
            voucher_data = await coordinator.api.get_powershout_vouchers_for_date(selected_date_for_vouchers, supply_point_id)
            
            available_vouchers = []
            if voucher_data and isinstance(voucher_data.get("vouchers"), list):
                available_vouchers = voucher_data["vouchers"]
            num_existing_bookings = len(voucher_data.get("bookings", [])) if voucher_data else 0
            
            for i in range(requested_duration):
                current_hour_dt = base_start_dt + timedelta(hours=i)
                start_date_str = current_hour_dt.strftime('%Y-%m-%dT%H:%M:%S')

                voucher_index = num_existing_bookings + i
                if voucher_index >= len(available_vouchers):
                    break 

                voucher_to_use = [available_vouchers[voucher_index]]
                eco_hours = [{"hour": current_hour_dt.hour, "ecoFriendly": False}]

                success = await coordinator.api.add_powershout_booking(
                    start_date_str=start_date_str,
                    duration=1, 
                    supply_agreement_id=supply_agreement_id,
                    supply_point_id=supply_point_id,
                    loyalty_account_id=loyalty_account_id,
                    eco_hours=eco_hours,
                    vouchers=voucher_to_use,
                )

                if success:
                    successful_bookings += 1
                    booked_timestamps.append(start_date_str)
                    await asyncio.sleep(0.5) 
                else:
                    break

            if successful_bookings > 0:
                # Record to persistent local store so past redeemed hours leave the list immediately
                await coordinator.async_record_redeemed(booked_timestamps)

                time_str = base_start_dt.strftime('%-I:%M %p')
                async_create(
                    hass, f"Your {successful_bookings}-hour Power Shout starting at {time_str} has been booked.",
                    title="Genesis Energy Power Shout Booked", notification_id="genesis_powershout_success"
                )
                await coordinator.async_request_refresh()

        except Exception as e:
            LOGGER.exception("An unexpected error occurred while booking Power Shout: %s", e)
    
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING,
        async_add_powershout_booking_service,
        schema=SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING,
    )

    @callback
    async def async_cancel_powershout_booking_service(call: ServiceCall) -> None:
        """Handle cancelling a Power Shout booking using loyaltyAccountId."""
        booking_id = call.data[ATTR_BOOKING_ID]
        loyalty_acc_id = coordinator.get_loyalty_account_id()

        if not loyalty_acc_id:
            LOGGER.error("Cannot cancel booking: Loyalty account ID could not be resolved.")
            return

        try:
            await coordinator.api.delete_powershout_booking(booking_id, loyalty_acc_id)
            async_create(
                hass, "Your upcoming Power Shout booking has been cancelled.",
                title="Genesis Energy Power Shout Cancelled",
                notification_id="genesis_powershout_cancelled"
            )
            await coordinator.async_request_refresh()
        except Exception as e:
            LOGGER.exception("Failed to cancel Power Shout booking: %s", e)

    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL_POWERSHOUT_BOOKING,
        async_cancel_powershout_booking_service,
        schema=SERVICE_SCHEMA_CANCEL_POWERSHOUT_BOOKING,
    )
    
    @callback
    async def async_accept_powershout_offer_service(call: ServiceCall) -> None:
        offer_id = call.data[ATTR_OFFER_ID]
        offers_data = coordinator.data.get(DATA_API_POWERSHOUT_OFFERS)
        if not offers_data or not isinstance(offers_data.get("activeOffers"), list):
            return

        target_offer = next((o for o in offers_data["activeOffers"] if o.get("loyaltyOffer", {}).get("guid") == offer_id), None)
        if not target_offer: 
            return
            
        try:
            loyalty_account = target_offer['loyaltyAccount']
            loyalty_offer = target_offer['loyaltyOffer']

            success = await coordinator.api.accept_powershout_offer(
                loyalty_account_id=loyalty_account.get('id'),
                member_id=loyalty_account.get('memberGuid'),
                campaign_offer_id=loyalty_offer.get('guid'),
                quantity=loyalty_offer.get('amount'),
                offer_code=target_offer.get('code')
            )

            if success:
                async_create(
                    hass,
                    f"Successfully accepted '{target_offer.get('name')}' offer! {loyalty_offer.get('amount')} hours added.",
                    title="Genesis Energy Power Shout Offer",
                    notification_id="genesis_powershout_offer_success"
                )
                await coordinator.async_request_refresh()
        except Exception as e:
            LOGGER.exception(f"Error accepting Power Shout offer: {e}")

    hass.services.async_register(
        DOMAIN, SERVICE_ACCEPT_POWERSHOUT_OFFER,
        async_accept_powershout_offer_service,
        schema=SERVICE_SCHEMA_ACCEPT_POWERSHOUT_OFFER,
    )

    @callback
    async def async_backfill_statistics_service(call: ServiceCall) -> None:
        days = call.data[ATTR_DAYS_TO_FETCH]
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        force_overwrite = call.data[ATTR_FORCE_OVERWRITE]
        has_elec, has_gas = get_available_services(coordinator)
        
        process_fuel = "none"
        if requested_fuel == "electricity" and has_elec: 
            process_fuel = "electricity"
        elif requested_fuel == "gas" and has_gas: 
            process_fuel = "gas"
        elif requested_fuel == "both":
            if has_elec and has_gas: 
                process_fuel = "both"
            elif has_elec: 
                process_fuel = "electricity"
            elif has_gas: 
                process_fuel = "gas"
        
        if process_fuel != "none":
            hass.async_create_task(coordinator.async_backfill_statistics_data(days, process_fuel, force_overwrite))

    hass.services.async_register(
        DOMAIN, SERVICE_BACKFILL_STATISTICS,
        async_backfill_statistics_service,
        schema=SERVICE_SCHEMA_BACKFILL_STATISTICS,
    )

    @callback
    async def async_force_update_service(call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE,
        async_force_update_service,
        schema=SERVICE_SCHEMA_FORCE_UPDATE,
    )
    
    def _unload_services():
        hass.services.async_remove(DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING)
        hass.services.async_remove(DOMAIN, SERVICE_CANCEL_POWERSHOUT_BOOKING)
        hass.services.async_remove(DOMAIN, SERVICE_ACCEPT_POWERSHOUT_OFFER)
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_STATISTICS)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_UPDATE)
    
    entry.async_on_unload(_unload_services)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    LOGGER.info(f"Genesis Energy setup complete for {entry.data[CONF_EMAIL]} ✅")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            await hass.data[DOMAIN][entry.entry_id].api.close()
            hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator and coordinator._current_options != entry.options:
        coordinator._current_options = dict(entry.options)
        await hass.config_entries.async_reload(entry.entry_id)
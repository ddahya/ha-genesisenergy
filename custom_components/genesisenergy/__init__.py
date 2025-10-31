# custom_components/genesisenergy/__init__.py

import voluptuous as vol
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.components.persistent_notification import async_create

from .const import (
    DOMAIN, PLATFORMS, LOGGER, CONF_EMAIL,
    SERVICE_ADD_POWERSHOUT_BOOKING, ATTR_START_DATETIME, ATTR_DURATION_HOURS,
    DATA_API_POWERSHOUT_INFO, DATA_API_POWERSHOUT_OFFERS,
    SERVICE_BACKFILL_STATISTICS, ATTR_DAYS_TO_FETCH, ATTR_FUEL_TYPE,
    SERVICE_FORCE_UPDATE, DATA_API_BILLING_PLANS,
    SERVICE_ACCEPT_POWERSHOUT_OFFER, ATTR_OFFER_ID
)
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .exceptions import CannotConnect, InvalidAuth

ATTR_FORCE_OVERWRITE = "force_overwrite"

SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING = vol.Schema({
    vol.Required(ATTR_START_DATETIME): cv.datetime,
    vol.Required(ATTR_DURATION_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
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


    def get_available_services(coordinator: GenesisEnergyDataUpdateCoordinator) -> tuple[bool, bool]:
        """Checks billing plans and returns a tuple of (has_electricity, has_gas)."""
        has_electricity = False
        has_gas = False
        billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
        if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
            for site in billing_plans_data["billingAccountSites"]:
                if isinstance(site.get("supplyPoints"), list):
                    for supply_point in site["supplyPoints"]:
                        if isinstance(supply_point, dict):
                            supply_type = supply_point.get("supplyType")
                            if supply_type == "electricity":
                                has_electricity = True
                            elif supply_type == "naturalGas":
                                has_gas = True
        return has_electricity, has_gas

    @callback
    async def async_add_powershout_booking_service(call: ServiceCall) -> None:
        """Handle the service call to add a Power Shout booking."""
        start_dt_raw = call.data[ATTR_START_DATETIME]
        requested_duration = call.data[ATTR_DURATION_HOURS]

        base_start_dt = start_dt_raw.replace(minute=0, second=0, microsecond=0)
        LOGGER.info(f"Attempting to book Power Shout for {requested_duration} hour(s) starting at {base_start_dt}")

        ps_info = coordinator.data.get(DATA_API_POWERSHOUT_INFO)

        supply_agreement_id, supply_point_id, loyalty_account_id = None, None, None
        try:
            loyalty_account_id = ps_info.get("loyaltyAccountId")
            supply_point_data = ps_info["eligibleBillingAccounts"][0]["billingAccountSites"][0]["supplyPoints"][0]
            supply_agreement_id = supply_point_data.get("supplyAgreementId")
            supply_point_id = supply_point_data.get("id")
        except (KeyError, IndexError, TypeError):
            pass

        if not all([supply_agreement_id, supply_point_id, loyalty_account_id]):
            LOGGER.error("Could not book Power Shout: Missing required IDs. Please try again after the next update.")
            async_create(
                hass, "Could not book Power Shout: Required information is missing.",
                title="Genesis Energy Power Shout Failed", notification_id="genesis_powershout_error"
            )
            return

        successful_bookings = 0
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
                    LOGGER.error(f"Not enough vouchers available to book the full duration. "
                                 f"Booked {successful_bookings} hour(s) successfully.")
                    break 

                voucher_to_use = [available_vouchers[voucher_index]]
                LOGGER.debug(f"For hour {i+1}/{requested_duration}, using voucher: {voucher_to_use[0]}")

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
                    await asyncio.sleep(1) 
                else:
                    LOGGER.error(f"Failed to book hour {i+1} of {requested_duration}. Stopping.")
                    break

            if successful_bookings > 0:
                time_str = base_start_dt.strftime('%-I:%M %p')
                plural_s = "s" if successful_bookings > 1 else ""
                LOGGER.info(f"Successfully booked {successful_bookings} hour{plural_s} of Power Shout.")
                async_create(
                    hass, f"Your {successful_bookings}-hour Power Shout starting at {time_str} has been booked.",
                    title="Genesis Energy Power Shout Booked", notification_id="genesis_powershout_success"
                )
                await coordinator.async_request_refresh()
            
            if successful_bookings < requested_duration:
                 LOGGER.error("Could not complete the full booking request.")
                 if successful_bookings == 0: 
                    async_create(
                        hass, "The Power Shout booking failed. Check logs for details.",
                        title="Genesis Energy Power Shout Failed", notification_id="genesis_powershout_error"
                    )

        except (CannotConnect, InvalidAuth) as e:
            LOGGER.error(f"Failed to book Power Shout due to an API error: {e}")
        except Exception:
            LOGGER.exception("An unexpected error occurred while booking Power Shout.")
    
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING,
        async_add_powershout_booking_service,
        schema=SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING,
    )
    
    @callback
    async def async_accept_powershout_offer_service(call: ServiceCall) -> None:
        """Handle the service call to accept a Power Shout offer."""
        offer_id = call.data[ATTR_OFFER_ID]
        LOGGER.info(f"Attempting to accept Power Shout offer with ID: {offer_id}")

        offers_data = coordinator.data.get(DATA_API_POWERSHOUT_OFFERS)
        if not offers_data or not isinstance(offers_data.get("activeOffers"), list):
            LOGGER.error("Could not accept offer: Power Shout offer data is not available.")
            return

        target_offer = None
        for offer in offers_data["activeOffers"]:
            if offer.get("loyaltyOffer", {}).get("guid") == offer_id:
                target_offer = offer
                break
        
        if not target_offer:
            LOGGER.error(f"Could not find an active Power Shout offer with ID: {offer_id}")
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
                LOGGER.info(f"Successfully accepted Power Shout offer: {target_offer.get('name')}")
                async_create(
                    hass,
                    f"Successfully accepted the '{target_offer.get('name')}' offer! {loyalty_offer.get('amount')} hours have been added to your balance.",
                    title="Genesis Energy Power Shout Offer",
                    notification_id="genesis_powershout_offer_success"
                )
                await coordinator.async_request_refresh()
            else:
                LOGGER.error("Failed to accept Power Shout offer. The API call was unsuccessful.")

        except Exception as e:
            LOGGER.exception(f"An unexpected error occurred while accepting Power Shout offer: {e}")

    hass.services.async_register(
        DOMAIN, SERVICE_ACCEPT_POWERSHOUT_OFFER,
        async_accept_powershout_offer_service,
        schema=SERVICE_SCHEMA_ACCEPT_POWERSHOUT_OFFER,
    )

    @callback
    async def async_backfill_statistics_service(call: ServiceCall) -> None:
        """Handle the service call to backfill historical statistics."""
        days = call.data[ATTR_DAYS_TO_FETCH]
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        force_overwrite = call.data[ATTR_FORCE_OVERWRITE]

        has_electricity, has_gas = get_available_services(coordinator)
        
        process_fuel = "none"
        if requested_fuel == "electricity" and has_electricity:
            process_fuel = "electricity"
        elif requested_fuel == "gas" and has_gas:
            process_fuel = "gas"
        elif requested_fuel == "both":
            if has_electricity and has_gas:
                process_fuel = "both"
            elif has_electricity:
                process_fuel = "electricity"
            elif has_gas:
                process_fuel = "gas"
        
        if process_fuel == "none":
            LOGGER.warning(
                "Backfill service called for '%s', but this service is not available on your account. Aborting.❌",
                requested_fuel
            )
            return

        LOGGER.info(f"Backfill service proceeding for '{process_fuel}' for {days} days (Force Overwrite: {force_overwrite})...")
        hass.async_create_task(coordinator.async_backfill_statistics_data(days, process_fuel, force_overwrite))

    hass.services.async_register(
        DOMAIN, SERVICE_BACKFILL_STATISTICS,
        async_backfill_statistics_service,
        schema=SERVICE_SCHEMA_BACKFILL_STATISTICS,
    )

    @callback
    async def async_force_update_service(call: ServiceCall) -> None:
        """Handle the service call to force an update."""
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        LOGGER.info(f"Force update service called (for '{requested_fuel}'). Requesting a full coordinator refresh.")
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE,
        async_force_update_service,
        schema=SERVICE_SCHEMA_FORCE_UPDATE,
    )
    
    def _unload_services():
        hass.services.async_remove(DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING)
        hass.services.async_remove(DOMAIN, SERVICE_ACCEPT_POWERSHOUT_OFFER)
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_STATISTICS)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_UPDATE)
    
    entry.async_on_unload(_unload_services)
    
    LOGGER.info(f"Genesis Energy setup complete for {entry.data[CONF_EMAIL]} ✅")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            await hass.data[DOMAIN][entry.entry_id].api.close()
            hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
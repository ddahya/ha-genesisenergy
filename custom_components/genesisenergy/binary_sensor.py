# custom_components/genesisenergy/binary_sensor.py

from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    LOGGER,
    DATA_API_POWERSHOUT_OFFERS,
    DATA_API_POWERSHOUT_BALANCE,
    DATA_API_POWERSHOUT_BOOKINGS,
)
from .coordinator import GenesisEnergyDataUpdateCoordinator


def _all_bookings(coordinator: GenesisEnergyDataUpdateCoordinator) -> list[dict[str, Any]]:
    """Return all raw bookings from the coordinator data."""
    bookings_data = coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS) or {}
    bookings = bookings_data.get("bookings", []) if isinstance(bookings_data, dict) else []
    return [b for b in bookings if isinstance(b, dict)]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensor entities."""
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BinarySensorEntity] = []

    # 1. Offers Available Sensor
    if coordinator.data.get(DATA_API_POWERSHOUT_OFFERS) is not None or coordinator.data.get(DATA_API_POWERSHOUT_BALANCE) is not None:
        entities.append(PowerShoutOffersAvailableBinarySensor(coordinator))

    # 2. Bookings Tracking Sensors
    if coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS) is not None:
        entities.append(PowerShoutBookingInProgressBinarySensor(coordinator))
        entities.append(PowerShoutBookingUpcomingBinarySensor(coordinator))

    async_add_entities(entities)


class PowerShoutOffersAvailableBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that indicates if any Power Shout offers are available."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Offers Available"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_powershout_offers_available"
        self._attr_icon = "mdi:gift-outline"

    @property
    def is_on(self) -> bool:
        """Return True if there are active offers."""
        data_offers = self.coordinator.data.get(DATA_API_POWERSHOUT_OFFERS) or {}
        active_offers = data_offers.get("activeOffers", []) if isinstance(data_offers, dict) else []
        if len(active_offers) > 0:
            return True
        data_bal = self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE) or {}
        return (data_bal.get("active_offers_count") or 0) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the raw offers data."""
        data = self.coordinator.data.get(DATA_API_POWERSHOUT_OFFERS)
        return data if isinstance(data, dict) else None


class PowerShoutBookingInProgressBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON while a Power Shout session is actively running."""

    _attr_has_entity_name = True
    _POLL_INTERVAL = timedelta(minutes=2)

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Booking In Progress"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_powershout_booking_in_progress"
        self._attr_icon = "mdi:flash"
        self._bookings: list[dict[str, Any]] = _all_bookings(coordinator)

    async def async_added_to_hass(self) -> None:
        """Schedule listeners to accurately track live boundaries."""
        await super().async_added_to_hass()

        # Fast 2-minute interval to detect mid-hour booked sessions
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_refresh_bookings, self._POLL_INTERVAL
            )
        )

        # Exact :00 boundary trigger to flip OFF the instant a session ends
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_refresh_bookings, minute=0, second=0
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._bookings = _all_bookings(self.coordinator)
        super()._handle_coordinator_update()

    async def _async_refresh_bookings(self, now=None) -> None:
        """Fetch latest bookings and write state."""
        try:
            data = await self.coordinator.api.get_powershout_bookings()
            if isinstance(data, dict):
                self._bookings = [b for b in data.get("bookings", []) if isinstance(b, dict)]
        except Exception as err:
            LOGGER.debug("Could not refresh bookings for in-progress sensor: %s", err)
        self.async_write_ha_state()

    @property
    def _active_booking(self) -> dict[str, Any] | None:
        now = dt_util.utcnow()
        for b in self._bookings:
            start_raw = b.get("startDateTime")
            if not start_raw:
                continue
            try:
                start = dt_util.parse_datetime(str(start_raw))
                if start is None:
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                start_utc = start.astimezone(timezone.utc)
                duration = float(b.get("duration") or 1)
            except (ValueError, TypeError):
                continue
            if start_utc <= now < (start_utc + timedelta(hours=duration)):
                return b
        return None

    @property
    def is_on(self) -> bool:
        return self._active_booking is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        active = self._active_booking
        return {"current_booking": active} if active is not None else None


class PowerShoutBookingUpcomingBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON when future Power Shout bookings exist."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Booking Upcoming"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_powershout_booking_upcoming"
        self._attr_icon = "mdi:calendar-clock"

    def _upcoming(self) -> list[dict[str, Any]]:
        now = dt_util.utcnow()
        upcoming = []
        for b in _all_bookings(self.coordinator):
            start_raw = b.get("startDateTime")
            if not start_raw:
                continue
            try:
                start = dt_util.parse_datetime(str(start_raw))
                if start is None:
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                start_utc = start.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
            if start_utc > now:
                upcoming.append(b)
        upcoming.sort(key=lambda b: str(b.get("startDateTime", "")))
        return upcoming

    @property
    def is_on(self) -> bool:
        return len(self._upcoming()) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        upcoming = self._upcoming()
        if not upcoming:
            return None
        return {
            "upcoming_count": len(upcoming),
            "next_booking_start": upcoming[0].get("startDateTime"),
        }
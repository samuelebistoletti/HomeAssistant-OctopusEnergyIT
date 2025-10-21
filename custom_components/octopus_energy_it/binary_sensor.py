"""Binary sensors for the Octopus Energy Italy integration."""

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_local, as_utc, parse_datetime, utcnow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Energy Italy binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    # Get all account numbers from entry data or coordinator data
    account_numbers = entry.data.get("account_numbers", [])
    if not account_numbers and account_number:
        account_numbers = [account_number]

    # If still no account numbers, try to get them from coordinator data
    if not account_numbers and coordinator.data:
        account_numbers = list(coordinator.data.keys())

    _LOGGER.debug("Creating binary sensors for accounts: %s", account_numbers)

    entities = []

    # Create binary sensors for each account with devices
    for acc_num in account_numbers:
        if (
            coordinator.data
            and acc_num in coordinator.data
            and coordinator.data[acc_num].get("devices")
        ):
            entities.append(
                OctopusIntelligentDispatchingBinarySensor(acc_num, coordinator)
            )
            _LOGGER.info(
                "Added intelligent dispatching binary sensor for account %s", acc_num
            )

            # Log out the keys in coordinator data for debugging
            _LOGGER.info(
                "Available keys in coordinator for %s: %s",
                acc_num,
                list(coordinator.data[acc_num].keys()),
            )
            if "plannedDispatches" in coordinator.data[acc_num]:
                _LOGGER.info(
                    "Found %d planned dispatches in coordinator data",
                    len(coordinator.data[acc_num]["plannedDispatches"]),
                )
        else:
            _LOGGER.info(
                "Not creating intelligent dispatching sensor due to missing devices data for account %s",
                acc_num,
            )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.info("No binary sensors to add for any account")


class OctopusIntelligentDispatchingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for Octopus EV Charge Intelligent Dispatching."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the binary sensor for intelligent dispatching."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} EV Charge Intelligent Dispatching"
        self._attr_unique_id = f"octopus_{account_number}_intelligent_dispatching"
        self._attr_device_class = None
        self._attr_icon = "mdi:clock-check"
        self._attr_has_entity_name = False
        self._attributes = {}
        self._update_attributes()

    @property
    def is_on(self) -> bool:
        """
        Determine if the binary sensor is currently active.

        The sensor is 'on' (true) when at least one planned dispatch
        exists that encompasses the current time.
        """
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.debug("No valid data structure in coordinator for is_on check")
            return False

        account_data = self.coordinator.data[self._account_number]

        # Check for both camelCase and snake_case keys
        planned_dispatches = account_data.get("plannedDispatches", [])
        if not planned_dispatches:
            planned_dispatches = account_data.get("planned_dispatches", [])

        if not planned_dispatches:
            _LOGGER.debug("No planned dispatches found")
            return False

        _LOGGER.debug(
            "Checking %d planned dispatches for active status", len(planned_dispatches)
        )

        # Get current time in UTC
        now = utcnow()
        _LOGGER.debug("Current time (UTC): %s", now.isoformat())

        # Check all planned dispatches to see if one is currently active
        for dispatch in planned_dispatches:
            try:
                # Extract start and end time
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")

                if not start_str or not end_str:
                    _LOGGER.debug("Dispatch missing start or end time: %s", dispatch)
                    continue

                # Convert strings to datetime objects and ensure they are timezone-aware UTC
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))

                if not start or not end:
                    _LOGGER.debug(
                        "Failed to parse start or end time for dispatch: %s", dispatch
                    )
                    continue

                _LOGGER.debug(
                    "Checking dispatch: start=%s, end=%s, current=%s",
                    start.isoformat(),
                    end.isoformat(),
                    now.isoformat(),
                )

                # If current time is between start and end, the dispatch is active
                if start <= now <= end:
                    _LOGGER.info(
                        "Active dispatch found! From %s to %s (current: %s)",
                        start.isoformat(),
                        end.isoformat(),
                        now.isoformat(),
                    )
                    return True
                time_to_start = (
                    (start - now).total_seconds() if start > now else None
                )
                time_since_end = (now - end).total_seconds() if now > end else None

                if time_to_start is not None:
                    _LOGGER.debug(
                        "Dispatch not yet active - starts in %d seconds (%s)",
                        int(time_to_start),
                        start.isoformat(),
                    )
                elif time_since_end is not None:
                    _LOGGER.debug(
                        "Dispatch already ended - ended %d seconds ago (%s)",
                        int(time_since_end),
                        end.isoformat(),
                    )

            except (ValueError, TypeError) as e:
                _LOGGER.error("Error parsing dispatch data: %s - %s", dispatch, str(e))
                continue

        # If no active dispatch was found, the sensor is 'off'
        _LOGGER.debug("No active dispatches found, sensor is OFF")
        return False

    def _format_dispatch(self, dispatch):
        """Format a dispatch entry for display."""
        try:
            # Get start and end as strings
            start_str = dispatch.get("start")
            end_str = dispatch.get("end")

            if not start_str or not end_str:
                return None

            # Parse string to datetime and ensure timezone aware
            start = parse_datetime(start_str)
            end = parse_datetime(end_str)

            if not start or not end:
                return None

            # Create a simpler format for the attribute
            formatted = {
                "start": start_str,
                "end": end_str,
                "start_time": as_local(start).strftime("%Y-%m-%d %H:%M:%S")
                if start
                else "Unknown",
                "end_time": as_local(end).strftime("%Y-%m-%d %H:%M:%S")
                if end
                else "Unknown",
                "charge_kwh": float(dispatch.get("deltaKwh", 0)),
            }

            # Add type if available (from new flex API)
            if "type" in dispatch:
                formatted["type"] = dispatch["type"]

            # Add source and location if available
            meta = dispatch.get("meta", {})
            if meta:
                if "source" in meta:
                    formatted["source"] = meta["source"]
                if "location" in meta:
                    formatted["location"] = meta["location"]
                # Also check for type in meta for backward compatibility
                if "type" in meta and "type" not in formatted:
                    formatted["type"] = meta["type"]

            return formatted
        except (ValueError, TypeError) as e:
            _LOGGER.error("Error formatting dispatch: %s - %s", dispatch, e)
            return None

    def _process_device_preferences(self, device):
        """Process and format device preferences for display."""
        if not isinstance(device, dict):
            return {}

        preferences = device.get("preferences", {})
        if not preferences:
            return {}

        processed_prefs = {}

        # Process mode preference if available
        if "mode" in preferences:
            processed_prefs["mode"] = preferences["mode"]

        # Process schedules if available
        if "schedules" in preferences and isinstance(preferences["schedules"], list):
            schedules = []
            for schedule in preferences["schedules"]:
                if isinstance(schedule, dict):
                    formatted_schedule = {
                        "day": schedule.get("dayOfWeek", ""),
                        "time": schedule.get("time", ""),
                        "min": schedule.get("min", 0),
                        "max": schedule.get("max", 100),
                    }
                    schedules.append(formatted_schedule)

            if schedules:
                processed_prefs["schedules"] = schedules

        return processed_prefs

    def _update_attributes(self) -> None:
        """No custom attributes exposed."""
        self._attributes = {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the binary sensor."""
        return self._attributes

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        self._update_attributes()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )

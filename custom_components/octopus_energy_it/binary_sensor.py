"""Binary sensors for the Octopus Energy Italy integration."""

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import as_utc, parse_datetime, utcnow

from .const import DOMAIN
from .entity import OctopusCoordinatorEntity, resolve_account_numbers

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Energy Italy binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    account_numbers = resolve_account_numbers(entry, coordinator, account_number)
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
            _LOGGER.debug(
                "Added intelligent dispatching binary sensor for account %s", acc_num
            )
            _LOGGER.debug(
                "Available keys in coordinator for %s: %s",
                acc_num,
                list(coordinator.data[acc_num].keys()),
            )
            if "planned_dispatches" in coordinator.data[acc_num]:
                _LOGGER.debug(
                    "Found %d planned dispatches in coordinator data",
                    len(coordinator.data[acc_num]["planned_dispatches"]),
                )
        else:
            _LOGGER.info(
                "No devices data for account %s, skipping intelligent dispatch sensor",
                acc_num,
            )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.info("No binary sensors to add for any account")


class OctopusIntelligentDispatchingBinarySensor(
    OctopusCoordinatorEntity, BinarySensorEntity
):
    """Binary sensor for Octopus EV Charge Intelligent Dispatching."""

    _attr_translation_key = "ev_intelligent_dispatching"
    _attr_icon = "mdi:clock-check"

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the binary sensor for intelligent dispatching."""
        super().__init__(account_number, coordinator)
        self._attr_unique_id = f"octopus_{account_number}_intelligent_dispatching"
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

                # Convert to timezone-aware UTC datetimes
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
                time_to_start = (start - now).total_seconds() if start > now else None
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

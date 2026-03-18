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
        """Return True when a planned dispatch encompasses the current time."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            return False

        planned_dispatches = self.coordinator.data[self._account_number].get(
            "planned_dispatches", []
        )
        if not planned_dispatches:
            return False

        now = utcnow()
        for dispatch in planned_dispatches:
            try:
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")
                if not start_str or not end_str:
                    continue
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))
                if not start or not end:
                    continue
                if start <= now <= end:
                    return True
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Error parsing dispatch data: %s - %s", dispatch, str(e))
        return False

    def _update_attributes(self) -> None:
        """No custom attributes exposed."""
        self._attributes = {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        if self.coordinator.data and isinstance(self.coordinator.data, dict):
            account_data = self.coordinator.data.get(self._account_number, {})
            dispatches = account_data.get("planned_dispatches", [])
            _LOGGER.debug(
                "Coordinator update: %d planned dispatch(es) for account %s, sensor=%s",
                len(dispatches),
                self._account_number,
                "ON" if self.is_on else "OFF",
            )
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

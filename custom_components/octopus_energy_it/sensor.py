"""
This module provides integration with Octopus Energy Italy for Home Assistant.

It defines the coordinator and sensor entities to fetch and display
electricity price information.
"""

import logging
from datetime import UTC, datetime, time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_account_data(coordinator, account_number):
    """Safely retrieve account data from the coordinator."""
    data = getattr(coordinator, "data", None)
    if isinstance(data, dict):
        return data.get(account_number)
    return None


def _select_current_product(products):
    """Return the most recent product that is currently valid."""
    if not products:
        return None

    now_iso = datetime.now().isoformat()
    valid_products = []

    for product in products:
        if not isinstance(product, dict):
            continue

        valid_from = product.get("validFrom")
        valid_to = product.get("validTo")

        if not valid_from:
            continue

        if valid_from <= now_iso and (not valid_to or now_iso <= valid_to):
            valid_products.append(product)

    if not valid_products:
        return None

    valid_products.sort(key=lambda item: item.get("validFrom", ""), reverse=True)
    return valid_products[0]


def _build_sensors_for_account(account_number, coordinator, account_data):
    """Create sensor instances for the provided account data."""
    sensors = []

    if account_data.get("electricity_pod"):
        products = account_data.get("products") or []
        if products:
            _LOGGER.debug(
                "Creating electricity price sensor for account %s with %d products",
                account_number,
                len(products),
            )
            sensors.append(OctopusElectricityPriceSensor(account_number, coordinator))
            current_product = account_data.get("current_electricity_product") or _select_current_product(products)
            pricing = (current_product or {}).get("pricing") or {}
            if pricing.get("f2") is not None:
                sensors.append(OctopusElectricityPriceF2Sensor(account_number, coordinator))
            if pricing.get("f3") is not None:
                sensors.append(OctopusElectricityPriceF3Sensor(account_number, coordinator))

        sensors.append(OctopusElectricityLastReadingSensor(account_number, coordinator))
        sensors.append(OctopusElectricityLastReadingDateSensor(account_number, coordinator))

        if account_data.get("electricity_balance") is not None:
            sensors.append(OctopusElectricityBalanceSensor(account_number, coordinator))

        if account_data.get("electricity_supply_point"):
            sensors.append(OctopusElectricityMeterStatusSensor(account_number, coordinator))

        if account_data.get("electricity_annual_standing_charge") is not None:
            sensors.append(OctopusElectricityStandingChargeSensor(account_number, coordinator))

        if account_data.get("electricity_contract_start"):
            sensors.append(OctopusElectricityContractStartSensor(account_number, coordinator))

        if account_data.get("electricity_contract_end"):
            sensors.append(OctopusElectricityContractEndSensor(account_number, coordinator))

        if account_data.get("electricity_contract_days_until_expiry") is not None:
            sensors.append(OctopusElectricityContractExpiryDaysSensor(account_number, coordinator))

        if account_data.get("current_electricity_product"):
            sensors.append(OctopusElectricityProductInfoSensor(account_number, coordinator))


    if account_data.get("gas_pdr"):
        if account_data.get("gas_balance") is not None:
            sensors.append(OctopusGasBalanceSensor(account_number, coordinator))

        gas_products = account_data.get("gas_products") or []
        if gas_products:
            _LOGGER.debug(
                "Creating gas sensors for account %s with %d gas products",
                account_number,
                len(gas_products),
            )

        sensors.append(OctopusGasLastReadingSensor(account_number, coordinator))

        if account_data.get("gas_supply_point"):
            sensors.append(OctopusGasMeterStatusSensor(account_number, coordinator))

        if account_data.get("gas_price") is not None:
            sensors.append(OctopusGasPriceSensor(account_number, coordinator))

        if account_data.get("gas_contract_start"):
            sensors.append(OctopusGasContractStartSensor(account_number, coordinator))

        if account_data.get("gas_contract_end"):
            sensors.append(OctopusGasContractEndSensor(account_number, coordinator))

        if account_data.get("gas_contract_days_until_expiry") is not None:
            sensors.append(OctopusGasContractExpiryDaysSensor(account_number, coordinator))

        if account_data.get("gas_annual_standing_charge") is not None:
            sensors.append(OctopusGasStandingChargeSensor(account_number, coordinator))

        if account_data.get("current_gas_product"):
            sensors.append(OctopusGasProductInfoSensor(account_number, coordinator))


    devices = account_data.get("devices") or []
    if devices:
        _LOGGER.debug(
            "Creating device status sensor for account %s with %d devices",
            account_number,
            len(devices),
        )
        sensors.append(OctopusEVChargeStatusSensor(account_number, coordinator))
        sensors.append(OctopusEVChargeTargetSensor(account_number, coordinator))
        sensors.append(OctopusEVReadyTimeSensor(account_number, coordinator))

    if account_data.get("heat_balance", 0):
        sensors.append(OctopusHeatBalanceSensor(account_number, coordinator))

    other_ledgers = account_data.get("other_ledgers") or {}
    for ledger_type in other_ledgers:
        sensors.append(OctopusLedgerBalanceSensor(account_number, coordinator, ledger_type))

    if account_data.get("vehicle_battery_size_in_kwh") is not None:
        sensors.append(OctopusVehicleBatterySizeSensor(account_number, coordinator))

    return sensors



async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Energy Italy price sensors from a config entry."""
    # Using existing coordinator from hass.data[DOMAIN] to avoid duplicate API calls
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]
    # Wait for coordinator refresh if needed
    if coordinator.data is None:
        _LOGGER.debug("No data in coordinator, triggering refresh")
        await coordinator.async_refresh()

    # Debug log to see the complete data structure
    if coordinator.data:
        _LOGGER.debug("Coordinator data keys: %s", coordinator.data.keys())

    # Initialize entities list
    entities = []

    # Get all account numbers from entry data or coordinator data
    account_numbers = entry.data.get("account_numbers", [])
    if not account_numbers and account_number:
        account_numbers = [account_number]

    # If still no account numbers, try to get them from coordinator data
    if not account_numbers and coordinator.data:
        account_numbers = list(coordinator.data.keys())

    _LOGGER.debug("Creating sensors for accounts: %s", account_numbers)

    # Create sensors for each account
    for acc_num in account_numbers:
        account_data = _get_account_data(coordinator, acc_num)

        if account_data:
            entities.extend(
                _build_sensors_for_account(acc_num, coordinator, account_data)
            )
            continue

        if coordinator.data is None:
            _LOGGER.error("No coordinator data available")
        elif isinstance(coordinator.data, dict) and acc_num not in coordinator.data:
            _LOGGER.warning("Account %s missing from coordinator data", acc_num)
        else:
            _LOGGER.warning(
                "Unable to create sensors for account %s due to missing data",
                acc_num,
            )
    # Only add entities if we have any
    if entities:
        _LOGGER.debug(
            "Adding %d entities: %s",
            len(entities),
            [type(e).__name__ for e in entities],
        )
        async_add_entities(entities)
    else:
        _LOGGER.warning("No entities to add for any account")


class OctopusElectricityPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the base electricity unit price."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Price"
        self._attr_unique_id = f"octopus_{account_number}_electricity_price"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_has_entity_name = False

    def _pricing(self) -> dict:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return {}
        product = account_data.get("current_electricity_product") or _select_current_product(account_data.get("products") or [])
        if not product:
            return {}
        return product.get("pricing") or {}

    @staticmethod
    def _to_float(value):
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> float | None:
        return self._to_float(self._pricing().get("base"))

    @property
    def available(self) -> bool:
        return self.native_value is not None


class OctopusElectricityPriceF2Sensor(OctopusElectricityPriceSensor):
    """Sensor exposing the F2 electricity unit price."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(account_number, coordinator)
        self._attr_name = f"Octopus {account_number} Electricity Price F2"
        self._attr_unique_id = f"octopus_{account_number}_electricity_price_f2"

    @property
    def native_value(self) -> float | None:
        return self._to_float(self._pricing().get("f2"))


class OctopusElectricityPriceF3Sensor(OctopusElectricityPriceSensor):
    """Sensor exposing the F3 electricity unit price."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(account_number, coordinator)
        self._attr_name = f"Octopus {account_number} Electricity Price F3"
        self._attr_unique_id = f"octopus_{account_number}_electricity_price_f3"

    @property
    def native_value(self) -> float | None:
        return self._to_float(self._pricing().get("f3"))



class OctopusElectricityBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy electricity balance."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Balance"
        self._attr_unique_id = f"octopus_{account_number}_electricity_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("electricity_balance", 0.0)

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
        )


class OctopusGasBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy gas balance."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Balance"
        self._attr_unique_id = f"octopus_{account_number}_gas_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float | None:
        """Return the gas balance."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_balance", 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
        )




class OctopusElectricityStandingChargeSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the annual electricity standing charge."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Standing Charge"
        self._attr_unique_id = f"octopus_{account_number}_electricity_standing_charge"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @staticmethod
    def _to_float(value):
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> float | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return self._to_float(account_data.get("electricity_annual_standing_charge"))

    @property
    def native_unit_of_measurement(self) -> str | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("electricity_annual_standing_charge_units") or "€/anno"

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("electricity_annual_standing_charge") is not None
        )


class OctopusGasLastReadingSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the latest gas meter reading."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Last Reading"
        self._attr_unique_id = f"octopus_{account_number}_gas_last_reading"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_native_unit_of_measurement = "m³"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_has_entity_name = False

    def _reading(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_last_reading")

    @property
    def native_value(self) -> float | None:
        reading = self._reading()
        if not reading:
            return None
        value = reading.get("value")
        if value is None:
            return None
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = self._reading()
        if not reading:
            return {}
        return {
            "recorded_at": reading.get("readingDate"),
            "measurement_type": reading.get("readingType"),
            "measurement_source": reading.get("readingSource"),
            "unit_of_measurement": reading.get("unit"),
        }

    @property
    def available(self) -> bool:
        reading = self._reading()
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and reading is not None
        )


class OctopusElectricityLastReadingSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the latest electricity meter reading."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Last Reading"
        self._attr_unique_id = f"octopus_{account_number}_electricity_last_reading"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_has_entity_name = False

    def _reading(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("electricity_last_reading")

    @property
    def native_value(self) -> float | None:
        reading = self._reading()
        if not reading:
            return None
        value = reading.get("value")
        if value is None:
            return None
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = self._reading()
        if not reading:
            return {}
        return {
            "period_start": reading.get("start"),
            "period_end": reading.get("end"),
            "data_source": reading.get("source"),
            "unit_of_measurement": reading.get("unit"),
            "register_start_value": reading.get("start_register_value"),
            "register_end_value": reading.get("end_register_value"),
        }

    @property
    def available(self) -> bool:
        reading = self._reading()
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and reading is not None
        )


class OctopusElectricityLastReadingDateSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the date of the latest electricity meter reading."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Last Reading Date"
        self._attr_unique_id = f"octopus_{account_number}_electricity_last_reading_date"
        self._attr_has_entity_name = False

    def _reading(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("electricity_last_reading")

    @staticmethod
    def _parse_date(entry: dict | None):
        if not entry:
            return None
        timestamp = entry.get("start")
        if not timestamp:
            return None
        try:
            normalised = timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalised)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.date()
        except (ValueError, TypeError):
            try:
                return datetime.strptime(timestamp.split('T')[0], "%Y-%m-%d").date()
            except (ValueError, IndexError):
                return None

    @property
    def native_value(self):
        reading = self._reading()
        parsed = self._parse_date(reading)
        if parsed is None:
            return None
        return parsed.strftime("%d/%m/%Y")

    @property
    def available(self) -> bool:
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and self.native_value is not None
        )


class OctopusElectricityMeterStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing electricity supply point status metadata."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Meter Status"
        self._attr_unique_id = f"octopus_{account_number}_electricity_meter_status"
        self._attr_has_entity_name = False

    def _supply_point(self) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None, {}
        supply_point = account_data.get("electricity_supply_point") or {}
        if not isinstance(supply_point, dict):
            supply_point = {}
        return account_data, supply_point

    @property
    def native_value(self) -> str | None:
        account_data, supply_point = self._supply_point()
        if not account_data:
            return None
        return account_data.get("electricity_supply_status") or supply_point.get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        account_data, supply_point = self._supply_point()
        if not account_data:
            return {}
        return {
            "account_number": self._account_number,
            "pod": account_data.get("electricity_pod"),
            "supply_point_id": account_data.get("electricity_supply_point_id"),
            "enrollment_status": account_data.get("electricity_enrolment_status")
            or supply_point.get("enrolmentStatus"),
            "enrollment_started_at": account_data.get("electricity_enrolment_start")
            or supply_point.get("enrolmentStartDate"),
            "supply_started_at": account_data.get("electricity_supply_start")
            or supply_point.get("supplyStartDate"),
            "is_smart_meter": account_data.get("electricity_is_smart_meter")
            if account_data.get("electricity_is_smart_meter") is not None
            else supply_point.get("isSmartMeter"),
            "cancellation_reason": account_data.get("electricity_cancellation_reason")
            or supply_point.get("cancellationReason"),
        }

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and (
                account_data.get("electricity_supply_status") is not None
                or account_data.get("electricity_supply_point") is not None
            )
        )


class OctopusHeatBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy heat balance."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the heat balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Heat Balance"
        self._attr_unique_id = f"octopus_{account_number}_heat_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float | None:
        """Return the heat balance."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("heat_balance", 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
        )


class OctopusElectricityContractStartSensor(CoordinatorEntity, SensorEntity):
    """Sensor for electricity contract start date."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Contract Start"
        self._attr_unique_id = f"octopus_{account_number}_electricity_contract_start"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @property
    def native_value(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        contract_start = account_data.get("electricity_contract_start")
        if not contract_start:
            return None
        try:
            normalised = contract_start.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalised)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.date().strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            try:
                return datetime.strptime(contract_start.split('T')[0], "%Y-%m-%d").strftime("%d/%m/%Y")
            except (TypeError, ValueError, IndexError):
                return None

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("electricity_contract_start") is not None
        )


class OctopusElectricityContractEndSensor(CoordinatorEntity, SensorEntity):
    """Sensor for electricity contract end date."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Contract End"
        self._attr_unique_id = f"octopus_{account_number}_electricity_contract_end"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @property
    def native_value(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        contract_end = account_data.get("electricity_contract_end")
        if not contract_end:
            return None
        try:
            normalised = contract_end.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalised)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.date().strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            try:
                return datetime.strptime(contract_end.split('T')[0], "%Y-%m-%d").strftime("%d/%m/%Y")
            except (TypeError, ValueError, IndexError):
                return None

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("electricity_contract_end") is not None
        )


class OctopusElectricityContractExpiryDaysSensor(CoordinatorEntity, SensorEntity):
    """Sensor for days until electricity contract expiry."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Contract Days Until Expiry"
        self._attr_unique_id = f"octopus_{account_number}_electricity_contract_expiry_days"
        self._attr_native_unit_of_measurement = "days"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> int | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("electricity_contract_days_until_expiry")

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("electricity_contract_days_until_expiry") is not None
        )


class OctopusElectricityProductInfoSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing descriptive information about the active electricity product."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Product"
        self._attr_unique_id = f"octopus_{account_number}_electricity_product"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    def _account_data(self):
        return _get_account_data(self.coordinator, self._account_number)

    def _current_product(self):
        account_data = self._account_data()
        if not account_data:
            return None
        return account_data.get("current_electricity_product")

    def _agreements(self):
        account_data = self._account_data()
        if not account_data:
            return []
        return account_data.get("electricity_agreements") or []

    @property
    def native_value(self) -> str | None:
        product = self._current_product()
        if not product:
            return None
        return product.get("displayName") or product.get("name") or product.get("code")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        product = self._current_product()
        if not product:
            return {"account_number": self._account_number}
        pricing = product.get("pricing") or {}
        return {
            "account_number": self._account_number,
            "product_code": product.get("code"),
            "product_type": product.get("productType"),
            "product_description": product.get("description"),
            "agreement_id": product.get("agreementId"),
            "valid_from": product.get("validFrom"),
            "valid_to": product.get("validTo"),
            "is_time_of_use": product.get("isTimeOfUse"),
            "terms_url": product.get("termsAndConditionsUrl"),
            "price_base": pricing.get("base"),
            "price_f2": pricing.get("f2"),
            "price_f3": pricing.get("f3"),
            "price_unit": pricing.get("units"),
            "standing_charge_annual": pricing.get("annualStandingCharge"),
            "standing_charge_units": pricing.get("annualStandingChargeUnits"),
            "linked_agreements": self._agreements(),
        }

    @property
    def available(self) -> bool:
        return self._current_product() is not None


class OctopusLedgerBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy generic ledger balance."""

    def __init__(self, account_number, coordinator, ledger_type) -> None:
        """Initialize the ledger balance sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._ledger_type = ledger_type
        ledger_name = ledger_type.replace("_LEDGER", "").replace("_", " ").title()
        self._attr_name = f"Octopus {account_number} {ledger_name} Balance"
        self._attr_unique_id = f"octopus_{account_number}_{ledger_type.lower()}_balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float | None:
        """Return the ledger balance."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        other_ledgers = account_data.get("other_ledgers", {})
        return other_ledgers.get(self._ledger_type, 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
        )



class OctopusGasMeterStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing gas supply point status metadata."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Meter Status"
        self._attr_unique_id = f"octopus_{account_number}_gas_meter_status"
        self._attr_has_entity_name = False

    def _supply_point(self) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None, {}
        supply_point = account_data.get("gas_supply_point") or {}
        if not isinstance(supply_point, dict):
            supply_point = {}
        return account_data, supply_point

    @property
    def native_value(self) -> str | None:
        account_data, supply_point = self._supply_point()
        if not account_data:
            return None
        return account_data.get("gas_supply_status") or supply_point.get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        account_data, supply_point = self._supply_point()
        if not account_data:
            return {}
        return {
            "account_number": self._account_number,
            "pdr": account_data.get("gas_pdr"),
            "enrollment_status": account_data.get("gas_enrolment_status")
            or supply_point.get("enrolmentStatus"),
            "enrollment_started_at": account_data.get("gas_enrolment_start")
            or supply_point.get("enrolmentStartDate"),
            "supply_started_at": account_data.get("gas_supply_start")
            or supply_point.get("supplyStartDate"),
            "is_smart_meter": account_data.get("gas_is_smart_meter")
            if account_data.get("gas_is_smart_meter") is not None
            else supply_point.get("isSmartMeter"),
            "cancellation_reason": account_data.get("gas_cancellation_reason")
            or supply_point.get("cancellationReason"),
        }

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and (
                account_data.get("gas_supply_status") is not None
                or account_data.get("gas_supply_point") is not None
            )
        )


class OctopusGasPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy gas price."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas price sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Price"
        self._attr_unique_id = f"octopus_{account_number}_gas_price"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/m³"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> float | None:
        """Return the gas price."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_price")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_price") is not None
        )



class OctopusGasContractStartSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy gas contract start date."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas contract start sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Contract Start"
        self._attr_unique_id = f"octopus_{account_number}_gas_contract_start"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @property
    def native_value(self):
        """Return the gas contract start date."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None

        contract_start = account_data.get("gas_contract_start")
        if not contract_start:
            return None
        try:
            normalised = contract_start.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalised)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.date().strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            try:
                return datetime.strptime(contract_start.split('T')[0], "%Y-%m-%d").strftime("%d/%m/%Y")
            except (TypeError, ValueError, IndexError):
                return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_contract_start") is not None
        )


class OctopusGasContractEndSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy gas contract end date."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas contract end sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Contract End"
        self._attr_unique_id = f"octopus_{account_number}_gas_contract_end"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @property
    def native_value(self):
        """Return the gas contract end date."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None

        contract_end = account_data.get("gas_contract_end")
        if not contract_end:
            return None
        try:
            normalised = contract_end.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalised)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.date().strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            try:
                return datetime.strptime(contract_end.split('T')[0], "%Y-%m-%d").strftime("%d/%m/%Y")
            except (TypeError, ValueError, IndexError):
                return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_contract_end") is not None
        )


class OctopusGasContractExpiryDaysSensor(CoordinatorEntity, SensorEntity):
    """Sensor for days until Octopus Energy Italy gas contract expiry."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas contract expiry days sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Contract Days Until Expiry"
        self._attr_unique_id = f"octopus_{account_number}_gas_contract_expiry_days"
        self._attr_native_unit_of_measurement = "days"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> int | None:
        """Return the days until gas contract expiry."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_contract_days_until_expiry")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_contract_days_until_expiry") is not None
        )


class OctopusGasProductInfoSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing descriptive information about the active gas product."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Product"
        self._attr_unique_id = f"octopus_{account_number}_gas_product"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    def _account_data(self):
        return _get_account_data(self.coordinator, self._account_number)

    def _current_product(self):
        account_data = self._account_data()
        if not account_data:
            return None
        return account_data.get("current_gas_product")

    def _agreements(self):
        account_data = self._account_data()
        if not account_data:
            return []
        return account_data.get("gas_agreements") or []

    @property
    def native_value(self) -> str | None:
        product = self._current_product()
        if not product:
            return None
        return product.get("displayName") or product.get("name") or product.get("code")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        product = self._current_product()
        if not product:
            return {"account_number": self._account_number}
        pricing = product.get("pricing") or {}
        return {
            "account_number": self._account_number,
            "product_code": product.get("code"),
            "product_type": product.get("productType"),
            "product_description": product.get("description"),
            "agreement_id": product.get("agreementId"),
            "valid_from": product.get("validFrom"),
            "valid_to": product.get("validTo"),
            "terms_url": product.get("termsAndConditionsUrl"),
            "price_base": pricing.get("base"),
            "price_unit": pricing.get("units"),
            "standing_charge_annual": pricing.get("annualStandingCharge"),
            "standing_charge_units": pricing.get("annualStandingChargeUnits"),
            "linked_agreements": self._agreements(),
        }

    @property
    def available(self) -> bool:
        return self._current_product() is not None


class OctopusGasStandingChargeSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the annual gas standing charge."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Standing Charge"
        self._attr_unique_id = f"octopus_{account_number}_gas_standing_charge"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @staticmethod
    def _to_float(value):
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> float | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return self._to_float(account_data.get("gas_annual_standing_charge"))

    @property
    def native_unit_of_measurement(self) -> str | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_annual_standing_charge_units") or "€/anno"

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_annual_standing_charge") is not None
        )





class OctopusEVChargeStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy device status."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the device status sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} EV Charge Status"
        self._attr_unique_id = f"octopus_{account_number}_ev_charge_status"
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> str | None:
        """Return the current device status."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None

        devices = account_data.get("devices", [])
        if not devices:
            return None

        device = devices[0]
        status = device.get("status", {})
        return status.get("currentState", "Unknown")

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "account_number": self._account_number,
            "device_id": None,
            "device_name": None,
            "device_model": None,
            "device_provider": None,
            "battery_capacity_kwh": None,
            "status_current_state": "Unknown",
            "status_connection_state": None,
            "status_is_suspended": False,
            "preferences_mode": None,
            "preferences_unit": None,
            "preferences_target_type": None,
            "allow_grid_export": None,
            "schedules": None,
            "target_day_of_week": None,
            "target_time": None,
            "target_percentage": None,
            "boost_active": False,
            "boost_available": False,
            "last_synced_at": datetime.now().isoformat(),
        }

        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            self._attributes = default_attributes
            return

        devices = account_data.get("devices", [])
        if not devices:
            self._attributes = default_attributes
            return

        device = devices[0]
        preferences = device.get("preferences") or {}
        schedules = preferences.get("schedules") or []
        schedule = schedules[0] if schedules else None

        status = device.get("status", {})
        current_state = status.get("currentState", "")
        current = status.get("current", "")
        is_suspended = status.get("isSuspended", False)
        is_live = current == "LIVE"
        has_smart_control = "SMART_CONTROL_CAPABLE" in current_state
        has_boost_state = "BOOST" in current_state.upper()
        has_boost_charging = "BOOST_CHARGING" in current_state.upper()

        boost_charge_active = "BOOST" in current_state.upper()
        boost_charge_available = (
            is_live
            and (has_smart_control or has_boost_state or has_boost_charging)
            and not is_suspended
        )

        self._attributes = {
            "account_number": self._account_number,
            "device_id": device.get("id"),
            "device_name": device.get("name"),
            "device_model": device.get("vehicleVariant", {}).get("model"),
            "device_provider": device.get("provider"),
            "battery_capacity_kwh": device.get("vehicleVariant", {}).get(
                "batterySize"
            ),
            "status_current_state": current_state,
            "status_connection_state": current,
            "status_is_suspended": is_suspended,
            "preferences_mode": preferences.get("mode"),
            "preferences_unit": preferences.get("unit"),
            "preferences_target_type": preferences.get("targetType"),
            "allow_grid_export": preferences.get("gridExport"),
            "schedules": preferences.get("schedules"),
            "target_day_of_week": schedule.get("dayOfWeek") if schedule else None,
            "target_time": schedule.get("time") if schedule else None,
            "target_percentage": schedule.get("max") if schedule else None,
            "boost_active": boost_charge_active,
            "boost_available": boost_charge_available,
            "last_synced_at": datetime.now().isoformat(),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the sensor."""
        return self._attributes

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        self._update_attributes()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("devices")
        )

class OctopusEVChargeTargetSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the configured smart charging target."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} EV Charge Target"
        self._attr_unique_id = f"octopus_{account_number}_ev_charge_target"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    def _first_device(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None, None
        devices = account_data.get("devices") or []
        if not devices:
            return account_data, None
        return account_data, devices[0]

    @property
    def native_value(self) -> float | None:
        account_data, device = self._first_device()
        if not device:
            return None
        preferences = device.get("preferences") or {}
        schedules = preferences.get("schedules") or []
        for schedule in schedules:
            if schedule.get("max") is not None:
                try:
                    return float(schedule.get("max"))
                except (TypeError, ValueError):
                    continue
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {}

    @property
    def available(self) -> bool:
        account_data, device = self._first_device()
        if not device:
            return False
        preferences = device.get("preferences") or {}
        schedules = preferences.get("schedules") or []
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and any(schedule.get("max") is not None for schedule in schedules)
        )



class OctopusEVReadyTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the preferred completion time from SmartFlex schedules."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} EV Ready Time"
        self._attr_unique_id = f"octopus_{account_number}_ev_ready_time"
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    def _first_schedule(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None, None, None
        devices = account_data.get("devices") or []
        if not devices:
            return account_data, None, None
        device = devices[0]
        schedules = (device.get("preferences") or {}).get("schedules") or []
        if not schedules:
            return account_data, device, None
        return account_data, device, schedules[0]

    @property
    def native_value(self) -> str | None:
        account_data, device, schedule = self._first_schedule()
        if not schedule:
            return None
        return schedule.get("time")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {}

    @property
    def available(self) -> bool:
        _, _, schedule = self._first_schedule()
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and schedule is not None
        )


class OctopusVehicleBatterySizeSensor(CoordinatorEntity, SensorEntity):
    """Sensor reporting detected vehicle battery capacity."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Vehicle Battery Size"
        self._attr_unique_id = f"octopus_{account_number}_vehicle_battery_size"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = True

    @property
    def native_value(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("vehicle_battery_size_in_kwh")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        account_data = _get_account_data(self.coordinator, self._account_number)
        attributes: dict[str, Any] = {"account_number": self._account_number}
        if not account_data:
            return attributes

        devices = account_data.get("devices") or []
        for device in devices:
            variant = device.get("vehicleVariant") or {}
            if variant.get("batterySize") is not None:
                attributes.update(
                    {
                        "device_id": device.get("id"),
                        "device_name": device.get("name"),
                        "vehicle_model": variant.get("model"),
                        "device_provider": device.get("provider"),
                    }
                )
                break

        return attributes

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("vehicle_battery_size_in_kwh") is not None
        )




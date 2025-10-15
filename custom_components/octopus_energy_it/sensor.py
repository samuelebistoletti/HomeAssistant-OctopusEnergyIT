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

        if account_data.get("electricity_balance") is not None:
            sensors.append(OctopusElectricityBalanceSensor(account_number, coordinator))

        if account_data.get("electricity_supply_point"):
            sensors.append(OctopusElectricitySupplyStatusSensor(account_number, coordinator))

    if account_data.get("gas_pdr"):
        if account_data.get("gas_balance") is not None:
            sensors.append(OctopusGasBalanceSensor(account_number, coordinator))

        gas_products = account_data.get("gas_products") or []
        if gas_products:
            _LOGGER.debug(
                "Creating gas tariff sensor for account %s with %d gas products",
                account_number,
                len(gas_products),
            )
            sensors.append(OctopusGasTariffSensor(account_number, coordinator))

        sensors.append(OctopusGasPdrSensor(account_number, coordinator))
        sensors.append(OctopusGasSupplyPointSensor(account_number, coordinator))

        if account_data.get("gas_supply_point"):
            sensors.append(OctopusGasSupplyStatusSensor(account_number, coordinator))

        if account_data.get("gas_price") is not None:
            sensors.append(OctopusGasPriceSensor(account_number, coordinator))

        if account_data.get("gas_contract_start"):
            sensors.append(OctopusGasContractStartSensor(account_number, coordinator))

        if account_data.get("gas_contract_end"):
            sensors.append(OctopusGasContractEndSensor(account_number, coordinator))

        if account_data.get("gas_contract_days_until_expiry") is not None:
            sensors.append(OctopusGasContractExpiryDaysSensor(account_number, coordinator))

    devices = account_data.get("devices") or []
    if devices:
        _LOGGER.debug(
            "Creating device status sensor for account %s with %d devices",
            account_number,
            len(devices),
        )
        sensors.append(OctopusDeviceStatusSensor(account_number, coordinator))

    if account_data.get("heat_balance", 0):
        sensors.append(OctopusHeatBalanceSensor(account_number, coordinator))

    other_ledgers = account_data.get("other_ledgers") or {}
    for ledger_type in other_ledgers:
        sensors.append(OctopusLedgerBalanceSensor(account_number, coordinator, ledger_type))

    dispatch_fields = [
        ("current_start", "Current Dispatch Start", "dispatch_current_start"),
        ("current_end", "Current Dispatch End", "dispatch_current_end"),
        ("next_start", "Next Dispatch Start", "dispatch_next_start"),
        ("next_end", "Next Dispatch End", "dispatch_next_end"),
    ]

    for field, name_suffix, unique_suffix in dispatch_fields:
        if account_data.get(field) is not None:
            sensors.append(
                OctopusDispatchWindowSensor(
                    account_number, coordinator, field, name_suffix, unique_suffix
                )
            )

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
    """Sensor for Octopus Energy Italy electricity price."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the electricity price sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Price"
        self._attr_unique_id = f"octopus_{account_number}_electricity_price"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    def _parse_time(self, time_str: str) -> time:
        """Parse time string in HH:MM:SS format to time object."""
        try:
            hour, minute, second = map(int, time_str.split(":"))
            return time(hour=hour, minute=minute, second=second)
        except (ValueError, AttributeError):
            _LOGGER.error(f"Invalid time format: {time_str}")
            return None

    def _is_time_between(
        self, current_time: time, time_from: time, time_to: time
    ) -> bool:
        """Check if current_time is between time_from and time_to."""
        # Handle special case where time_to is 00:00:00 (midnight)
        if time_to.hour == 0 and time_to.minute == 0 and time_to.second == 0:
            # If time_from is also midnight, the slot is active all day
            if time_from.hour == 0 and time_from.minute == 0 and time_from.second == 0:
                return True
            # Otherwise, the slot is active from time_from until midnight, or from midnight until time_from
            return current_time >= time_from or current_time < time_to
        # Normal case: check if time is between start and end
        if time_from <= time_to:
            return time_from <= current_time < time_to
        # Handle case where range crosses midnight
        return time_from <= current_time or current_time < time_to

    def _convert_cents_to_eur(self, value) -> float | None:
        """Convert a cent value to EUR, handling malformed inputs."""
        if value is None:
            return None
        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return None

    def _determine_time_of_use_band(self, current_dt: datetime) -> str:
        """Approximate the Italian F1/F2/F3 band for the current time."""
        day = current_dt.weekday()  # Monday = 0, Sunday = 6
        minutes = current_dt.hour * 60 + current_dt.minute

        if day < 5:  # Monday to Friday
            if 480 <= minutes < 1140:  # 08:00-19:00
                return "F1"
            if 420 <= minutes < 480 or 1140 <= minutes < 1380:  # 07:00-08:00, 19:00-23:00
                return "F2"
            return "F3"

        if day == 5:  # Saturday
            if 420 <= minutes < 1380:  # 07:00-23:00
                return "F2"
            return "F3"

        return "F3"  # Sunday and holidays fallback

    def _get_active_timeslot_rate(self, product):
        """Determine the active rate for the supplied product."""
        if not product:
            return None

        pricing = product.get("pricing") or {}

        if product.get("type") != "TimeOfUse":
            base_rate = pricing.get("base")
            if base_rate is not None:
                return base_rate
            return self._convert_cents_to_eur(product.get("grossRate"))

        band = self._determine_time_of_use_band(datetime.now())
        if band == "F1":
            rate = pricing.get("base")
        elif band == "F2":
            rate = pricing.get("f2") or pricing.get("base")
        else:  # F3
            rate = pricing.get("f3") or pricing.get("f2") or pricing.get("base")

        if rate is not None:
            return rate

        return self._convert_cents_to_eur(product.get("grossRate"))

    def _get_current_forecast_rate(self, product):
        """Get the current rate from unitRateForecast for dynamic pricing."""
        if not product:
            return None

        unit_rate_forecast = product.get("unitRateForecast", [])
        if not unit_rate_forecast:
            return None

        now = datetime.now(UTC)

        for forecast_entry in unit_rate_forecast:
            valid_from_str = forecast_entry.get("validFrom")
            valid_to_str = forecast_entry.get("validTo")

            if not valid_from_str or not valid_to_str:
                continue

            try:
                valid_from = datetime.fromisoformat(valid_from_str.replace("Z", "+00:00"))
                valid_to = datetime.fromisoformat(valid_to_str.replace("Z", "+00:00"))

                if valid_from <= now < valid_to:
                    unit_rate_info = forecast_entry.get("unitRateInformation", {})

                    typename = unit_rate_info.get("__typename")
                    if typename == "TimeOfUseProductUnitRateInformation":
                        rates = unit_rate_info.get("rates", [])
                        if rates:
                            rate_cents = rates[0].get("latestGrossUnitRateCentsPerKwh")
                            rate_eur = self._convert_cents_to_eur(rate_cents)
                            if rate_eur is not None:
                                _LOGGER.debug(
                                    "Found forecast rate: %.4f EUR/kWh for period %s - %s",
                                    rate_eur,
                                    valid_from_str,
                                    valid_to_str,
                                )
                                return rate_eur

                    if typename == "SimpleProductUnitRateInformation":
                        rate_cents = unit_rate_info.get("latestGrossUnitRateCentsPerKwh")
                        rate_eur = self._convert_cents_to_eur(rate_cents)
                        if rate_eur is not None:
                            _LOGGER.debug(
                                "Found forecast rate: %.4f EUR/kWh for period %s - %s",
                                rate_eur,
                                valid_from_str,
                                valid_to_str,
                            )
                            return rate_eur

            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Error parsing forecast entry: %s - %s", forecast_entry, str(e)
                )
                continue

        _LOGGER.debug(
            "No current forecast rate found for current time %s", now.isoformat()
        )
        return None

    @property
    def native_value(self) -> float | None:
        """Return the current electricity price."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            _LOGGER.warning("No valid coordinator data found for price sensor")
            return None

        products = account_data.get("products") or []
        if not products:
            _LOGGER.warning("No products found in coordinator data")
            return None

        current_product = _select_current_product(products)
        if not current_product:
            _LOGGER.warning("No valid product found for current date")
            return None

        product_code = current_product.get("code", "Unknown")
        product_type = current_product.get("type", "Unknown")
        pricing = current_product.get("pricing") or {}

        _LOGGER.debug(
            "Using product: %s, type: %s, valid from: %s",
            product_code,
            product_type,
            current_product.get("validFrom", "Unknown"),
        )

        if current_product.get("isTimeOfUse", False):
            forecast_rate = self._get_current_forecast_rate(current_product)
            if forecast_rate is not None:
                _LOGGER.debug(
                    "Dynamic forecast price: %.4f EUR/kWh for product %s",
                    forecast_rate,
                    product_code,
                )
                return forecast_rate

            active_rate = self._get_active_timeslot_rate(current_product)
            if active_rate is not None:
                _LOGGER.debug(
                    "Calculated time-of-use price: %.4f EUR/kWh for product %s",
                    active_rate,
                    product_code,
                )
                return active_rate

        base_rate = pricing.get("base")
        if base_rate is not None:
            _LOGGER.debug(
                "Base rate price: %.4f EUR/kWh for product %s",
                base_rate,
                product_code,
            )
            return base_rate

        fallback_rate = self._convert_cents_to_eur(current_product.get("grossRate"))
        if fallback_rate is not None:
            _LOGGER.debug(
                "Fallback gross rate: %.4f EUR/kWh for product %s",
                fallback_rate,
                product_code,
            )
            return fallback_rate

        _LOGGER.warning(
            "Failed to determine rate for product %s despite being current",
            product_code,
        )
        return None

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "code": "Unknown",
            "name": "Unknown",
            "description": "Unknown",
            "type": "Unknown",
            "valid_from": "Unknown",
            "valid_to": "Unknown",
            "electricity_pod": "Unknown",
            "electricity_supply_point_id": "Unknown",
            "account_number": self._account_number,
        }

        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            self._attributes = default_attributes
            return

        current_product = _select_current_product(account_data.get("products") or [])
        if not current_product:
            self._attributes = default_attributes
            return

        product_attributes = {
            "code": current_product.get("code", "Unknown"),
            "name": current_product.get("name", "Unknown"),
            "description": current_product.get("description", "Unknown"),
            "type": current_product.get("type", "Unknown"),
            "valid_from": current_product.get("validFrom", "Unknown"),
            "valid_to": current_product.get("validTo", "Unknown"),
            "electricity_pod": account_data.get("electricity_pod", "Unknown"),
            "electricity_supply_point_id": account_data.get("electricity_supply_point_id", "Unknown"),
            "account_number": self._account_number,
            "active_tariff_type": current_product.get("type", "Unknown"),
        }

        if current_product.get("type") == "TimeOfUse" and current_product.get("timeslots"):
            current_time = datetime.now().time()
            active_timeslot = None
            timeslots_data = []

            for timeslot in current_product.get("timeslots", []):
                timeslot_data = {
                    "name": timeslot.get("name", "Unknown"),
                    "rate": timeslot.get("rate", "0"),
                    "activation_rules": [],
                }

                for rule in timeslot.get("activation_rules", []):
                    from_time = rule.get("from_time", "00:00:00")
                    to_time = rule.get("to_time", "00:00:00")
                    timeslot_data["activation_rules"].append(
                        {"from_time": from_time, "to_time": to_time}
                    )

                    from_time_obj = self._parse_time(from_time)
                    to_time_obj = self._parse_time(to_time)
                    if (
                        from_time_obj
                        and to_time_obj
                        and self._is_time_between(current_time, from_time_obj, to_time_obj)
                    ):
                        active_timeslot = timeslot.get("name", "Unknown")
                        product_attributes["active_timeslot"] = active_timeslot
                        product_attributes["active_timeslot_rate"] = (
                            float(timeslot.get("rate", "0")) / 100.0
                        )
                        product_attributes["active_timeslot_from"] = from_time
                        product_attributes["active_timeslot_to"] = to_time

                timeslots_data.append(timeslot_data)

            product_attributes["timeslots"] = timeslots_data

        if account_data.get("electricity_balance") is not None:
            product_attributes["electricity_balance"] = (
                f"{account_data['electricity_balance']:.2f} €"
            )

        if current_product.get("isTimeOfUse", False):
            uk_rates = self._format_uk_rates(current_product)
            product_attributes["rates"] = uk_rates
            product_attributes["rates_count"] = len(uk_rates)
            product_attributes["unit_rate_forecast"] = current_product.get(
                "unitRateForecast", []
            )

        pricing = current_product.get("pricing") or {}
        if pricing:
            product_attributes["pricing_base"] = pricing.get("base")
            product_attributes["pricing_f2"] = pricing.get("f2")
            product_attributes["pricing_f3"] = pricing.get("f3")
            product_attributes["pricing_units"] = pricing.get("units")
            product_attributes["annual_standing_charge"] = pricing.get(
                "annualStandingCharge"
            )

        self._attributes = product_attributes

    def _format_uk_rates(self, product):
        """Format unitRateForecast data into UK-style rates attribute."""
        if not product:
            return []

        unit_rate_forecast = product.get("unitRateForecast", [])
        if not unit_rate_forecast:
            return []

        all_rates = []

        for forecast_entry in unit_rate_forecast:
            valid_from_str = forecast_entry.get("validFrom")
            valid_to_str = forecast_entry.get("validTo")

            if not valid_from_str or not valid_to_str:
                continue

            try:
                unit_rate_info = forecast_entry.get("unitRateInformation", {})
                price_eur_kwh = None

                if unit_rate_info.get("__typename") == "SimpleProductUnitRateInformation":
                    rate_cents = unit_rate_info.get("latestGrossUnitRateCentsPerKwh")
                    price_eur_kwh = self._convert_cents_to_eur(rate_cents)

                elif unit_rate_info.get("__typename") == "TimeOfUseProductUnitRateInformation":
                    rates = unit_rate_info.get("rates", [])
                    if rates:
                        rate_cents = rates[0].get("latestGrossUnitRateCentsPerKwh")
                        price_eur_kwh = self._convert_cents_to_eur(rate_cents)

                if price_eur_kwh is not None:
                    all_rates.append(
                        {
                            "start": valid_from_str,
                            "end": valid_to_str,
                            "value_inc_vat": round(price_eur_kwh, 4),
                        }
                    )

            except (ValueError, TypeError) as e:
                _LOGGER.debug("Error processing forecast entry: %s", e)
                continue

        all_rates.sort(key=lambda x: x["start"])
        _LOGGER.debug("Formatted %d rates for UK compatibility", len(all_rates))
        return all_rates

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


class OctopusElectricityBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy electricity balance."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the electricity balance sensor."""
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
        """Return the electricity balance."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("electricity_balance", 0.0)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
        )

class OctopusElectricitySupplyStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing electricity supply point status metadata."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Supply Status"
        self._attr_unique_id = f"octopus_{account_number}_electricity_supply_status"
        self._attr_has_entity_name = False

    def _supply_point(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None, None
        return account_data, account_data.get("electricity_supply_point") or {}

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
            "enrolment_status": account_data.get("electricity_enrolment_status")
            or supply_point.get("enrolmentStatus"),
            "supply_start": account_data.get("electricity_supply_start")
            or supply_point.get("supplyStartDate"),
            "is_smart_meter": account_data.get("electricity_is_smart_meter")
            if account_data.get("electricity_is_smart_meter") is not None
            else supply_point.get("isSmartMeter"),
            "cancellation_reason": account_data.get("electricity_cancellation_reason")
            or supply_point.get("cancellationReason"),
            "pod": account_data.get("electricity_pod"),
            "supply_point_id": account_data.get("electricity_supply_point_id"),
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


class OctopusGasTariffSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy gas tariff."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the gas tariff sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Tariff"
        self._attr_unique_id = f"octopus_{account_number}_gas_tariff"
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> str | None:
        """Return the current gas tariff code."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            _LOGGER.warning("No valid coordinator data found for gas tariff sensor")
            return None

        current_product = _select_current_product(account_data.get("gas_products") or [])
        if not current_product:
            _LOGGER.warning("No valid gas product found for current date")
            return None

        return current_product.get("code", "Unknown")

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        default_attributes = {
            "code": "Unknown",
            "name": "Unknown",
            "description": "Unknown",
            "type": "Unknown",
            "valid_from": "Unknown",
            "valid_to": "Unknown",
            "account_number": self._account_number,
        }

        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            self._attributes = default_attributes
            return

        current_product = _select_current_product(account_data.get("gas_products") or [])
        if not current_product:
            self._attributes = default_attributes
            return

        product_attributes = {
            "code": current_product.get("code", "Unknown"),
            "name": current_product.get("name", "Unknown"),
            "description": current_product.get("description", "Unknown"),
            "type": current_product.get("type", "Unknown"),
            "valid_from": current_product.get("validFrom", "Unknown"),
            "valid_to": current_product.get("validTo", "Unknown"),
            "account_number": self._account_number,
        }

        if account_data.get("gas_balance") is not None:
            product_attributes["gas_balance"] = f"{account_data['gas_balance']:.2f} €"

        pricing = current_product.get("pricing") or {}
        if pricing:
            product_attributes["pricing_base"] = pricing.get("base")
            product_attributes["pricing_units"] = pricing.get("units")
            product_attributes["annual_standing_charge"] = pricing.get(
                "annualStandingCharge"
            )

        self._attributes = product_attributes

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
        )




class OctopusGasPdrSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the gas PDR (supply point reference)."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas PDR"
        self._attr_unique_id = f"octopus_{account_number}_gas_pdr"
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> str | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_pdr")

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_pdr") is not None
        )


class OctopusGasSupplyPointSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing the internal gas supply point identifier."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Supply Point ID"
        self._attr_unique_id = f"octopus_{account_number}_gas_supply_point_id"
        self._attr_has_entity_name = False

    @property
    def native_value(self) -> str | None:
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get("gas_supply_point_id")

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get("gas_supply_point_id") is not None
        )

class OctopusGasSupplyStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing gas supply point status metadata."""

    def __init__(self, account_number, coordinator) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Gas Supply Status"
        self._attr_unique_id = f"octopus_{account_number}_gas_supply_status"
        self._attr_has_entity_name = False

    def _supply_point(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None, None
        return account_data, account_data.get("gas_supply_point") or {}

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
            "enrolment_status": account_data.get("gas_enrolment_status")
            or supply_point.get("enrolmentStatus"),
            "supply_start": account_data.get("gas_supply_start")
            or supply_point.get("supplyStartDate"),
            "is_smart_meter": account_data.get("gas_is_smart_meter")
            if account_data.get("gas_is_smart_meter") is not None
            else supply_point.get("isSmartMeter"),
            "cancellation_reason": account_data.get("gas_cancellation_reason")
            or supply_point.get("cancellationReason"),
            "pdr": account_data.get("gas_pdr"),
            "supply_point_id": account_data.get("gas_supply_point_id"),
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
        self._attr_native_unit_of_measurement = "€/kWh"
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
        self._attr_device_class = SensorDeviceClass.DATE
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        """Return the gas contract start date."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None

        contract_start = account_data.get("gas_contract_start")

        if contract_start:
            try:
                from datetime import datetime

                parsed_date = datetime.fromisoformat(
                    contract_start.replace("Z", "+00:00")
                )
                return parsed_date.date()
            except (ValueError, TypeError):
                return None

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
        self._attr_device_class = SensorDeviceClass.DATE
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        """Return the gas contract end date."""
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None

        contract_end = account_data.get("gas_contract_end")

        if contract_end:
            try:
                # Parse ISO date and return date object for DATE device class
                from datetime import datetime

                parsed_date = datetime.fromisoformat(
                    contract_end.replace("Z", "+00:00")
                )
                return parsed_date.date()
            except (ValueError, TypeError):
                return None

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
        self._attr_state_class = SensorStateClass.MEASUREMENT
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

class OctopusDispatchWindowSensor(CoordinatorEntity, SensorEntity):
    """Timestamp sensor for current and upcoming dispatch windows."""

    def __init__(self, account_number, coordinator, field_name, name_suffix, unique_suffix) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._field_name = field_name
        self._attr_name = f"Octopus {account_number} {name_suffix}"
        self._attr_unique_id = f"octopus_{account_number}_{unique_suffix}"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_has_entity_name = False
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        account_data = _get_account_data(self.coordinator, self._account_number)
        if not account_data:
            return None
        return account_data.get(self._field_name)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"account_number": self._account_number, "window_key": self._field_name}

    @property
    def available(self) -> bool:
        account_data = _get_account_data(self.coordinator, self._account_number)
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and account_data is not None
            and account_data.get(self._field_name) is not None
        )




class OctopusDeviceStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Energy Italy device status."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the device status sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Device Status"
        self._attr_unique_id = f"octopus_{account_number}_device_status"
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
            "device_id": "Unknown",
            "device_name": "Unknown",
            "device_model": "Unknown",
            "device_provider": "Unknown",
            "account_number": self._account_number,
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

        self._attributes = {
            "device_id": device.get("id", "Unknown"),
            "device_name": device.get("name", "Unknown"),
            "device_model": device.get("vehicleVariant", {}).get("model", "Unknown"),
            "device_provider": device.get("provider", "Unknown"),
            "battery_size": device.get("vehicleVariant", {}).get(
                "batterySize", "Unknown"
            ),
            "is_suspended": device.get("status", {}).get("isSuspended", False),
            "account_number": self._account_number,
            "last_updated": datetime.now().isoformat(),
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
        self._attr_entity_registry_enabled_default = False

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
                        "model": variant.get("model"),
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




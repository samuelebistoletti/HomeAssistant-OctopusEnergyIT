"""
Octopus Energy Italy Integration.

This module provides integration with the Octopus Energy Italy API for Home Assistant.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import as_utc, parse_datetime, utcnow

from .const import CONF_EMAIL, CONF_PASSWORD, DEBUG_ENABLED, DOMAIN, UPDATE_INTERVAL
from .octopus_energy_it import OctopusEnergyIT

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

API_URL = "https://api.octopus.energy/v1/graphql/"

# Service schemas
SERVICE_SET_DEVICE_PREFERENCES = "set_device_preferences"
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_DEVICE_ID = "device_id"
ATTR_TARGET_PERCENTAGE = "target_percentage"
ATTR_TARGET_TIME = "target_time"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Octopus Energy Italy from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    # Initialize API
    api = OctopusEnergyIT(email, password)

    # Log in only once and reuse the token through the global token manager
    if not await api.login():
        _LOGGER.error("Failed to authenticate with Octopus Energy Italy API")
        return False

    # Ensure DOMAIN is initialized in hass.data
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # Enhanced multi-account support with all ledgers
    account_numbers = entry.data.get("account_numbers", [])
    if not account_numbers:
        # Backward compatibility: try single account_number
        single_account = entry.data.get("account_number")
        if single_account:
            account_numbers = [single_account]
        else:
            _LOGGER.debug("No account numbers found in entry data, fetching from API")
            accounts = await api.fetch_accounts()
            if not accounts:
                _LOGGER.error("No accounts found for the provided credentials")
                return False

            # Store all accounts, not just the first one with electricity ledger
            account_numbers = [acc["number"] for acc in accounts]
            _LOGGER.info("Found %d accounts: %s", len(account_numbers), account_numbers)

            # Update config entry with all account numbers
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "account_numbers": account_numbers}
            )

    # For backward compatibility, set primary account_number to first account
    primary_account_number = account_numbers[0] if account_numbers else None
    if not entry.data.get("account_number"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "account_number": primary_account_number}
        )

    # Create data update coordinator with improved error handling and retry logic
    async def async_update_data():
        """Fetch data from API with improved error handling for all accounts."""
        current_time = datetime.now()

        # Add throttling to prevent too frequent API calls
        # Store last successful API call time on the function object
        if not hasattr(async_update_data, "last_api_call"):
            async_update_data.last_api_call = datetime.now() - timedelta(
                minutes=UPDATE_INTERVAL
            )

        # Calculate time since last API call
        time_since_last_call = (
            current_time - async_update_data.last_api_call
        ).total_seconds()
        min_interval = (
            UPDATE_INTERVAL * 60 * 0.9
        )  # 90% of the update interval in seconds

        # Get simplified caller information instead of full stack trace
        caller_info = "Unknown caller"
        if DEBUG_ENABLED:
            # Get the caller's frame (2 frames up from current)
            try:
                frame = inspect.currentframe()
                if frame:
                    frame = (
                        frame.f_back.f_back
                    )  # Go up two frames to find the actual caller
                    if frame:
                        # Extract useful caller information
                        caller_module = frame.f_globals.get(
                            "__name__", "unknown_module"
                        )
                        caller_function = frame.f_code.co_name
                        caller_line = frame.f_lineno
                        caller_info = f"{caller_module}.{caller_function}:{caller_line}"
                    del frame  # Clean up reference to avoid memory issues
            except Exception:
                caller_info = "Error getting caller info"

        _LOGGER.debug(
            "Coordinator update called at %s (Update interval: %s minutes, Time since last API call: %.1f seconds, Caller: %s)",
            current_time.strftime("%H:%M:%S"),
            UPDATE_INTERVAL,
            time_since_last_call,
            caller_info,
        )

        # If called too soon after last API call, return cached data
        if (
            time_since_last_call < min_interval
            and hasattr(coordinator, "data")
            and coordinator.data
        ):
            _LOGGER.debug(
                "Throttling API call - returning cached data from %s",
                async_update_data.last_api_call.strftime("%H:%M:%S"),
            )
            return coordinator.data

        try:
            # Let the API class handle token validation
            _LOGGER.debug(
                "Fetching data from API at %s", current_time.strftime("%H:%M:%S")
            )

            # Fetch data for all accounts
            all_accounts_data = {}
            for account_num in account_numbers:
                try:
                    # Fetch all data in one call to minimize API requests
                    account_data = await api.fetch_all_data(account_num)
                    if account_data:
                        # Process the raw API data into a more usable format
                        processed_account_data = await process_api_data(
                            account_data, account_num, api
                        )
                        all_accounts_data.update(processed_account_data)
                    else:
                        _LOGGER.warning(
                            "Failed to fetch data for account %s", account_num
                        )
                except Exception as e:
                    _LOGGER.error(
                        "Error fetching data for account %s: %s", account_num, e
                    )
                    continue

            # Update last API call timestamp only on successful calls
            if all_accounts_data:
                async_update_data.last_api_call = datetime.now()

            if not all_accounts_data:
                _LOGGER.error(
                    "Failed to fetch data from API for any account, returning last known data"
                )
                return coordinator.data if hasattr(coordinator, "data") else {}

            _LOGGER.debug(
                "Successfully fetched data from API at %s for %d accounts",
                datetime.now().strftime("%H:%M:%S"),
                len(all_accounts_data),
            )
            return all_accounts_data

        except Exception as e:
            _LOGGER.exception("Unexpected error during data update: %s", e)
            # Return previous data if available, empty dict otherwise
            return coordinator.data if hasattr(coordinator, "data") else {}

    async def process_api_data(data, account_number, api):
        """Process raw API response into structured data."""
        if not data:
            return {}

        # Initialize the data structure
        result_data = {
            account_number: {
                "account_number": account_number,
                "account": {},
                "electricity_balance": 0,
                "planned_dispatches": [],
                "plannedDispatches": [],
                "completed_dispatches": [],
                "completedDispatches": [],
                "property_ids": [],
                "properties": [],
                "devices": [],
                "devices_raw": [],
                "products": [],
                "products_raw": [],
                "gas_products": [],
                "vehicle_battery_size_in_kwh": None,
                "current_start": None,
                "current_end": None,
                "next_start": None,
                "next_end": None,
                "ledgers": [],
                "malo_number": None,
                "melo_number": None,
                "meter": None,
                "gas_malo_number": None,
                "gas_melo_number": None,
                "gas_meter": None,
                "raw_response": {},
            }
        }

        # Extract account data - this should be available even if device-related endpoints fail
        account_data = data.get("account", {})

        # Log what data we have - safely handle None values
        _LOGGER.debug(
            "Processing API data - fields available: %s",
            list(data.keys()) if data else [],
        )
        result_data[account_number]["raw_response"] = data or {}

        # Only try to access account_data keys if it's not None and is a dictionary
        if account_data and isinstance(account_data, dict):
            result_data[account_number]["account"] = account_data
            result_data[account_number]["properties"] = account_data.get("properties", [])
            _LOGGER.debug("Account data fields: %s", list(account_data.keys()))
        else:
            _LOGGER.warning("Account data is missing or invalid: %s", account_data)
            # Return the basic structure with default values
            return result_data

        # Extract ALL ledger data (not just electricity)
        ledgers = account_data.get("ledgers", [])
        result_data[account_number]["ledgers"] = ledgers

        # Initialize all ledger balances
        electricity_balance_eur = 0
        gas_balance_eur = 0
        heat_balance_eur = 0
        other_ledgers = {}

        # Process all available ledgers
        for ledger in ledgers:
            ledger_type = ledger.get("ledgerType")
            balance_cents = ledger.get("balance", 0)
            balance_eur = balance_cents / 100

            if ledger_type == "ELECTRICITY_LEDGER":
                electricity_balance_eur = balance_eur
            elif ledger_type == "GAS_LEDGER":
                gas_balance_eur = balance_eur
            elif ledger_type == "HEAT_LEDGER":
                heat_balance_eur = balance_eur
            else:
                # Store any other ledger types we might encounter
                other_ledgers[ledger_type] = balance_eur
                _LOGGER.debug(
                    "Found additional ledger type: %s with balance: %.2f EUR",
                    ledger_type,
                    balance_eur,
                )

        # Store all ledger balances in result
        result_data[account_number]["electricity_balance"] = electricity_balance_eur
        result_data[account_number]["gas_balance"] = gas_balance_eur
        result_data[account_number]["heat_balance"] = heat_balance_eur
        result_data[account_number]["other_ledgers"] = other_ledgers

        _LOGGER.debug(
            "Processed %d ledgers for account %s: electricity=%.2f, gas=%.2f, heat=%.2f, other=%d",
            len(ledgers),
            account_number,
            electricity_balance_eur,
            gas_balance_eur,
            heat_balance_eur,
            len(other_ledgers),
        )

        # Extract supply point identifiers for electricity and gas
        first_electricity_supply_point = next(
            (
                supply_point
                for prop in account_data.get("properties", [])
                for supply_point in prop.get("electricitySupplyPoints", [])
            ),
            None,
        )

        electricity_pod = None
        electricity_supply_id = None
        if first_electricity_supply_point:
            electricity_pod = first_electricity_supply_point.get("pod")
            electricity_supply_id = first_electricity_supply_point.get("id")

        result_data[account_number]["malo_number"] = electricity_pod
        result_data[account_number]["melo_number"] = electricity_supply_id

        # Meter identifiers are not currently exposed through the public schema
        meter = None
        result_data[account_number]["meter"] = meter

        first_gas_supply_point = next(
            (
                supply_point
                for prop in account_data.get("properties", [])
                for supply_point in prop.get("gasSupplyPoints", [])
            ),
            None,
        )

        gas_pdr = None
        gas_supply_id = None
        if first_gas_supply_point:
            gas_pdr = first_gas_supply_point.get("pdr")
            gas_supply_id = first_gas_supply_point.get("id")

        result_data[account_number]["gas_malo_number"] = gas_pdr
        result_data[account_number]["gas_melo_number"] = gas_supply_id
        gas_meter = None
        result_data[account_number]["gas_meter"] = gas_meter

        # Extract property IDs
        property_ids = [
            prop.get("id") for prop in account_data.get("properties", [])
        ]
        result_data[account_number]["property_ids"] = property_ids


        # Handle device-related data if it exists (may be missing with KT-CT-4301 error)
        devices = data.get("devices", [])
        result_data[account_number]["devices"] = devices
        result_data[account_number]["devices_raw"] = devices

        # Extract vehicle battery size if available
        vehicle_battery_size = None
        for device in devices:
            if device.get("vehicleVariant") and device["vehicleVariant"].get(
                "batterySize"
            ):
                try:
                    vehicle_battery_size = float(
                        device["vehicleVariant"]["batterySize"]
                    )
                    break
                except (ValueError, TypeError):
                    pass
        result_data[account_number]["vehicle_battery_size_in_kwh"] = (
            vehicle_battery_size
        )

        # Handle dispatch data if it exists
        planned_dispatches = data.get("plannedDispatches", [])
        if planned_dispatches is None:  # Handle explicit None value (from API error)
            planned_dispatches = []
        result_data[account_number]["planned_dispatches"] = planned_dispatches
        result_data[account_number]["plannedDispatches"] = planned_dispatches

        completed_dispatches = data.get("completedDispatches", [])
        if completed_dispatches is None:  # Handle explicit None value (from API error)
            completed_dispatches = []
        result_data[account_number]["completed_dispatches"] = completed_dispatches
        result_data[account_number]["completedDispatches"] = completed_dispatches

        # Calculate current and next dispatches
        now = utcnow()  # Use timezone-aware UTC now
        current_start = None
        current_end = None
        next_start = None
        next_end = None

        for dispatch in sorted(planned_dispatches, key=lambda x: x.get("start", "")):
            try:
                # Convert string to timezone-aware datetime objects
                start_str = dispatch.get("start")
                end_str = dispatch.get("end")

                if not start_str or not end_str:
                    continue

                # Parse string to datetime and ensure it's UTC timezone-aware
                start = as_utc(parse_datetime(start_str))
                end = as_utc(parse_datetime(end_str))

                if start <= now <= end:
                    current_start = start
                    current_end = end
                elif now < start and not next_start:
                    next_start = start
                    next_end = end
            except (ValueError, TypeError) as e:
                _LOGGER.error("Error parsing dispatch dates: %s - %s", dispatch, str(e))

        result_data[account_number]["current_start"] = current_start
        result_data[account_number]["current_end"] = current_end
        result_data[account_number]["next_start"] = next_start
        result_data[account_number]["next_end"] = next_end

        def select_current_product(products_list):
            """Pick the most recent product that is currently valid."""
            if not products_list:
                return None

            now_iso = datetime.now().isoformat()
            valid_products = []

            for product in products_list:
                valid_from = product.get("validFrom")
                valid_to = product.get("validTo")

                if not valid_from:
                    continue

                if valid_from <= now_iso and (not valid_to or now_iso <= valid_to):
                    valid_products.append(product)

            if not valid_products:
                return None

            valid_products.sort(key=lambda p: p.get("validFrom", ""), reverse=True)
            return valid_products[0]

        # Electricity products
        products = data.get("products") or []
        if products:
            _LOGGER.debug(
                "Found %d electricity products for account %s", len(products), account_number
            )
        else:
            _LOGGER.warning(
                "No electricity products returned for account %s; registering fallback tariff",
                account_number,
            )
            products = [
                {
                    "code": "FALLBACK_ELECTRICITY",
                    "description": "Fallback electricity tariff",
                    "name": "Fallback Electricity Tariff",
                    "displayName": "Fallback Electricity Tariff",
                    "validFrom": None,
                    "validTo": None,
                    "agreementId": None,
                    "productType": None,
                    "isTimeOfUse": False,
                    "type": "Simple",
                    "timeslots": [],
                    "termsAndConditionsUrl": None,
                    "pricing": {
                        "base": 0.30,
                        "f2": None,
                        "f3": None,
                        "units": "EUR/kWh",
                        "annualStandingCharge": None,
                        "annualStandingChargeUnits": None,
                    },
                    "params": {},
                    "rawPrices": {},
                    "supplyPoint": {},
                    "unitRateForecast": [],
                    "grossRate": "30",
                }
            ]

        result_data[account_number]["products"] = products
        # Preserve the products list as is for consumers expecting camelCase keys
        result_data[account_number]["products_raw"] = products

        # Gas products
        gas_products = data.get("gas_products") or []
        if gas_products:
            _LOGGER.debug(
                "Found %d gas products for account %s", len(gas_products), account_number
            )
        else:
            _LOGGER.debug("No gas products found for account %s", account_number)

        result_data[account_number]["gas_products"] = gas_products

        # Gas pricing and contract metadata
        gas_price = None
        gas_contract_start = None
        gas_contract_end = None
        gas_contract_days_until_expiry = None

        current_gas_product = select_current_product(gas_products)
        if current_gas_product:
            base_rate = (
                current_gas_product.get("pricing", {}).get("base")
                if isinstance(current_gas_product.get("pricing"), dict)
                else None
            )
            if base_rate is not None:
                gas_price = base_rate
            else:
                gross_rate_str = current_gas_product.get("grossRate")
                if gross_rate_str is not None:
                    try:
                        gas_price = float(gross_rate_str) / 100.0
                    except (ValueError, TypeError):
                        gas_price = None

            gas_contract_start = current_gas_product.get("validFrom")
            gas_contract_end = current_gas_product.get("validTo")

            if gas_contract_end:
                try:
                    end_date = datetime.fromisoformat(
                        gas_contract_end.replace("Z", "+00:00")
                    )
                    now_date = datetime.now(end_date.tzinfo)
                    days_diff = (end_date - now_date).days
                    gas_contract_days_until_expiry = max(0, days_diff)
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("Error calculating gas contract expiry days: %s", e)

        result_data[account_number]["gas_price"] = gas_price
        result_data[account_number]["gas_contract_start"] = gas_contract_start
        result_data[account_number]["gas_contract_end"] = gas_contract_end
        result_data[account_number]["gas_contract_days_until_expiry"] = (
            gas_contract_days_until_expiry
        )

        # Gas meter smart reading capability
        gas_meter_smart_reading = None
        if gas_meter and isinstance(gas_meter, dict):
            gas_meter_smart_reading = gas_meter.get("shouldReceiveSmartMeterData", None)

        result_data[account_number]["gas_meter_smart_reading"] = gas_meter_smart_reading

        # Fetch latest gas meter reading if gas meter exists
        gas_latest_reading = None
        if gas_meter and gas_meter.get("id"):
            try:
                gas_meter_id = gas_meter.get("id")
                _LOGGER.debug(
                    "Attempting to fetch gas meter reading for account %s, meter %s",
                    account_number,
                    gas_meter_id,
                )
                gas_latest_reading = await api.fetch_gas_meter_reading(
                    account_number, gas_meter_id
                )

                if gas_latest_reading:
                    _LOGGER.debug(
                        "Successfully fetched gas meter reading: %s %s at %s",
                        gas_latest_reading.get("value"),
                        gas_latest_reading.get("units"),
                        gas_latest_reading.get("intervalEnd"),
                    )
                else:
                    _LOGGER.debug(
                        "No gas meter reading returned for meter %s", gas_meter_id
                    )

            except Exception as e:
                _LOGGER.warning(
                    "Failed to fetch gas meter reading for account %s, meter %s: %s",
                    account_number,
                    gas_meter_id,
                    str(e),
                )

        result_data[account_number]["gas_latest_reading"] = gas_latest_reading

        # Fetch latest electricity meter reading if electricity meter exists
        electricity_latest_reading = None
        if meter and meter.get("id"):
            try:
                electricity_meter_id = meter.get("id")
                _LOGGER.debug(
                    "Attempting to fetch electricity meter reading for account %s, meter %s",
                    account_number,
                    electricity_meter_id,
                )
                electricity_latest_reading = await api.fetch_electricity_meter_reading(
                    account_number, electricity_meter_id
                )

                if electricity_latest_reading:
                    _LOGGER.debug(
                        "Successfully fetched electricity meter reading: %s at %s",
                        electricity_latest_reading.get("value"),
                        electricity_latest_reading.get("readAt"),
                    )
                else:
                    _LOGGER.debug(
                        "No electricity meter reading returned for meter %s",
                        electricity_meter_id,
                    )

            except Exception as e:
                _LOGGER.warning(
                    "Failed to fetch electricity meter reading for account %s, meter %s: %s",
                    account_number,
                    electricity_meter_id,
                    str(e),
                )

        result_data[account_number]["electricity_latest_reading"] = (
            electricity_latest_reading
        )

        return result_data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{primary_account_number}",
        update_method=async_update_data,
        update_interval=timedelta(minutes=UPDATE_INTERVAL),
    )

    # Initial data refresh - only once to prevent duplicate API calls
    await coordinator.async_config_entry_first_refresh()

    # Log the account data after update to help diagnose attribute issues
    if coordinator.data and primary_account_number in coordinator.data:
        _LOGGER.info(
            "Account %s data keys: %s",
            primary_account_number,
            list(coordinator.data[primary_account_number].keys()),
        )
        if "plannedDispatches" in coordinator.data[primary_account_number]:
            _LOGGER.info(
                "Found %d planned dispatches",
                len(coordinator.data[primary_account_number]["plannedDispatches"]),
            )
            _LOGGER.info(
                "First planned dispatch: %s",
                coordinator.data[primary_account_number]["plannedDispatches"][0]
                if coordinator.data[primary_account_number]["plannedDispatches"]
                else "None",
            )

    # Store API, account number and coordinator in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "account_number": primary_account_number,
        "account_numbers": account_numbers,
        "coordinator": coordinator,
    }

    # Forward setup to platforms - no need to wait for another refresh
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # Register services
    async def handle_set_device_preferences(call: ServiceCall):
        """Handle the set_device_preferences service call."""
        device_id = call.data.get(ATTR_DEVICE_ID)
        target_percentage = call.data.get(ATTR_TARGET_PERCENTAGE)
        target_time = call.data.get(ATTR_TARGET_TIME)

        if not device_id:
            _LOGGER.error("Device ID is required for set_device_preferences")
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Device ID is required",
                translation_domain=DOMAIN,
            )

        # Validate percentage (20-100% in 5% steps)
        if not 20 <= target_percentage <= 100:
            _LOGGER.error(
                f"Invalid target percentage: {target_percentage}. Must be between 20 and 100"
            )
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid target percentage: {target_percentage}. Must be between 20 and 100",
                translation_domain=DOMAIN,
            )

        if target_percentage % 5 != 0:
            _LOGGER.error(
                f"Invalid target percentage: {target_percentage}. Must be in 5% steps"
            )
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid target percentage: {target_percentage}. Must be in 5% steps",
                translation_domain=DOMAIN,
            )

        # Validate time format
        try:
            api._format_time_to_hh_mm(target_time)
        except ValueError as time_error:
            _LOGGER.error("Time validation error: %s", time_error)
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid time format: {time_error!s}",
                translation_domain=DOMAIN,
            )

        _LOGGER.debug(
            "Service call set_device_preferences with device_id=%s, target_percentage=%s, target_time=%s",
            device_id,
            target_percentage,
            target_time,
        )

        try:
            success = await api.set_device_preferences(
                device_id,
                target_percentage,
                target_time,
            )

            if success:
                _LOGGER.info("Successfully set device preferences")
                return {"success": True}
            _LOGGER.error("Failed to set device preferences")
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                "Failed to set device preferences. Check the log for details.",
                translation_domain=DOMAIN,
            )
        except ValueError as e:
            _LOGGER.error("Validation error: %s", e)
            from homeassistant.exceptions import ServiceValidationError

            raise ServiceValidationError(
                f"Invalid parameters: {e}",
                translation_domain=DOMAIN,
            )
        except Exception as e:
            _LOGGER.exception("Unexpected error setting device preferences: %s", e)
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(f"Error setting device preferences: {e}")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEVICE_PREFERENCES,
        handle_set_device_preferences,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    # update entry replacing data with new options
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, **config_entry.options}
    )
    await hass.config_entries.async_reload(config_entry.entry_id)

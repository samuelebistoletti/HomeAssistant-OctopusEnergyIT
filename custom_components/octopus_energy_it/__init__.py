"""
Octopus Energy Italy Integration.

This module provides integration with the Octopus Energy Italy API for Home Assistant.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN, UPDATE_INTERVAL
from .data_processor import process_api_data
from .octopus_energy_it import OctopusEnergyIT
from .tariff_scraper import fetch_public_tariffs

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]

PUBLIC_PRODUCTS_UPDATE_INTERVAL = timedelta(hours=1)
PUBLIC_PRODUCTS_RETRY_DELAY = 5 * 60  # seconds — used with async_call_later

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
    session = async_get_clientsession(hass)

    # Initialize API
    api = OctopusEnergyIT(email, password)

    # Log in only once and reuse the token through the global token manager
    if not await api.login():
        _LOGGER.error("Failed to authenticate with Octopus Energy Italy API")
        return False

    # Ensure DOMAIN is initialized in hass.data
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    domain_data = hass.data[DOMAIN]

    public_products_coordinator = domain_data.get("public_products_coordinator")

    async def async_update_public_products():
        def _cancel_retry():
            unsub = domain_data.pop("public_products_retry_unsub", None)
            if unsub is not None:
                unsub()

        def _schedule_retry():
            _cancel_retry()

            @callback
            def _do_retry(_now):
                domain_data.pop("public_products_retry_unsub", None)
                coordinator = domain_data.get("public_products_coordinator")
                if coordinator is not None:
                    hass.async_create_task(coordinator.async_request_refresh())

            domain_data["public_products_retry_unsub"] = hass.async_call_later(
                PUBLIC_PRODUCTS_RETRY_DELAY, _do_retry
            )
            _LOGGER.debug(
                "Scheduled public tariffs retry in %ds", PUBLIC_PRODUCTS_RETRY_DELAY
            )

        products = await fetch_public_tariffs(session)
        if products is None:
            _schedule_retry()
            cached = domain_data.get("public_products_cache")
            if cached:
                _LOGGER.warning(
                    "Public tariffs unavailable - using cached data, retrying in %ds",
                    PUBLIC_PRODUCTS_RETRY_DELAY,
                )
                return cached
            raise UpdateFailed("Public tariffs unavailable and no cached data")
        _cancel_retry()
        domain_data["public_products_cache"] = products
        return products

    if public_products_coordinator is None:
        public_products_coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_public_products",
            update_method=async_update_public_products,
            update_interval=PUBLIC_PRODUCTS_UPDATE_INTERVAL,
        )
        await public_products_coordinator.async_config_entry_first_refresh()
        domain_data["public_products_coordinator"] = public_products_coordinator
    elif public_products_coordinator.data is None:
        await public_products_coordinator.async_request_refresh()

    # Multi-account support
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

            account_numbers = [acc["number"] for acc in accounts]
            _LOGGER.info("Found %d accounts: %s", len(account_numbers), account_numbers)

            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "account_numbers": account_numbers}
            )

    # For backward compatibility, set primary account_number to first account
    primary_account_number = account_numbers[0] if account_numbers else None
    if not entry.data.get("account_number"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "account_number": primary_account_number}
        )

    async def async_update_data():
        """Fetch data from API for all accounts."""
        _LOGGER.debug(
            "Coordinator update triggered at %s",
            utcnow().strftime("%H:%M:%S"),
        )

        try:
            all_accounts_data = {}
            if public_products_coordinator.data is None:
                await public_products_coordinator.async_request_refresh()
            available_products = public_products_coordinator.data or {}
            for account_num in account_numbers:
                try:
                    account_data = await api.fetch_all_data(account_num)
                    if account_data:
                        processed = await process_api_data(
                            account_data, account_num, api, available_products
                        )
                        all_accounts_data.update(processed)
                    else:
                        _LOGGER.warning(
                            "Failed to fetch data for account %s", account_num
                        )
                except Exception as e:
                    _LOGGER.error(
                        "Error fetching data for account %s: %s", account_num, e
                    )
                    continue

            if not all_accounts_data:
                raise UpdateFailed("Failed to fetch data for any account")

            _LOGGER.debug(
                "Successfully fetched data for %d accounts", len(all_accounts_data)
            )
            return all_accounts_data

        except UpdateFailed:
            raise
        except Exception as e:
            raise UpdateFailed(f"Unexpected error during data update: {e}") from e

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{primary_account_number}",
        update_method=async_update_data,
        update_interval=timedelta(minutes=UPDATE_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    if coordinator.data and primary_account_number in coordinator.data:
        _LOGGER.debug(
            "Account %s data keys: %s",
            primary_account_number,
            list(coordinator.data[primary_account_number].keys()),
        )
        if "planned_dispatches" in coordinator.data[primary_account_number]:
            _LOGGER.debug(
                "Found %d planned dispatches",
                len(coordinator.data[primary_account_number]["planned_dispatches"]),
            )
            _LOGGER.debug(
                "First planned dispatch: %s",
                coordinator.data[primary_account_number]["planned_dispatches"][0]
                if coordinator.data[primary_account_number]["planned_dispatches"]
                else "None",
            )

    public_device_identifier = domain_data.setdefault(
        "public_device_identifier", "octopus_public_tariffs"
    )
    public_owner = domain_data.setdefault("public_owner", entry.entry_id)

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "account_number": primary_account_number,
        "account_numbers": account_numbers,
        "coordinator": coordinator,
        "public_device_id": public_device_identifier,
        "owns_public_products": public_owner == entry.entry_id,
        "public_products_coordinator": public_products_coordinator,
    }

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
            msg = "Device ID is required"
            raise ServiceValidationError(msg)

        if target_percentage is None:
            msg = "target_percentage is required"
            raise ServiceValidationError(msg)

        original_target_percentage = target_percentage
        target_percentage = int(round(target_percentage))
        target_percentage = max(10, min(100, target_percentage))
        if original_target_percentage != target_percentage:
            _LOGGER.debug(
                "Adjusted target percentage from %s to %s for service call",
                original_target_percentage,
                target_percentage,
            )

        try:
            api.format_time_to_hh_mm(target_time)
        except ValueError as time_error:
            _LOGGER.error("Time validation error: %s", time_error)
            raise ServiceValidationError(
                f"Invalid time format: {time_error!s}",
                translation_domain=DOMAIN,
            )

        _LOGGER.debug(
            "Service set_device_preferences: device=%s, pct=%s, time=%s",
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
                formatted_time = api.format_time_to_hh_mm(target_time)
                for acc_data in coordinator.data.values():
                    for device in acc_data.get("devices", []):
                        if device.get("id") == device_id:
                            preferences = device.setdefault("preferences", {})
                            schedules = preferences.setdefault("schedules", [])
                            if schedules:
                                schedules[0]["max"] = target_percentage
                                schedules[0]["time"] = f"{formatted_time}:00"
                            break
                    else:
                        continue
                    break
                await coordinator.async_request_refresh()
                return {"success": True}
            _LOGGER.error("Failed to set device preferences")
            raise ServiceValidationError(
                "Failed to set device preferences. Check the log for details.",
                translation_domain=DOMAIN,
            )
        except (ServiceValidationError, HomeAssistantError):
            raise
        except ValueError as e:
            _LOGGER.error("Validation error: %s", e)
            raise ServiceValidationError(
                f"Invalid parameters: {e}",
                translation_domain=DOMAIN,
            )
        except Exception as e:
            _LOGGER.exception("Unexpected error setting device preferences: %s", e)
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
        domain_data = hass.data[DOMAIN]
        domain_data.pop(entry.entry_id, None)
        remaining_entries = [
            key
            for key, value in domain_data.items()
            if isinstance(value, dict) and "coordinator" in value
        ]
        if domain_data.get("public_owner") == entry.entry_id:
            if remaining_entries:
                domain_data["public_owner"] = remaining_entries[0]
            else:
                domain_data.pop("public_owner", None)
        if not remaining_entries:
            unsub = domain_data.pop("public_products_retry_unsub", None)
            if unsub is not None:
                unsub()
            domain_data.pop("public_products_coordinator", None)
            domain_data.pop("public_products_cache", None)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, **config_entry.options}
    )
    await hass.config_entries.async_reload(config_entry.entry_id)

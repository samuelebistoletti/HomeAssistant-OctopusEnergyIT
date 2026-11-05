"""Octopus Energy Italy integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import (
    PUBLIC_DEVICE_IDENTIFIER,
    OctopusEnergyITConfigEntry,
    OctopusEnergyITDataUpdateCoordinator,
    OctopusEnergyITRuntimeData,
    async_get_public_products_coordinator,
    async_release_public_products,
)
from .octopus_energy_it import (
    OctopusEnergyIT,
    OctopusEnergyITAuthError,
    OctopusEnergyITConnectionError,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service actions once, independently of config entries."""
    async_setup_services(hass)
    return True


async def _async_account_numbers(
    hass: HomeAssistant, entry: OctopusEnergyITConfigEntry, api: OctopusEnergyIT
) -> list[str]:
    """Return the account numbers of the entry, discovering them if needed."""
    account_numbers = list(entry.data.get("account_numbers") or [])
    if not account_numbers and entry.data.get("account_number"):
        account_numbers = [entry.data["account_number"]]
    if account_numbers:
        return account_numbers

    accounts = await api.fetch_accounts()
    if not accounts:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="no_accounts"
        )
    account_numbers = [account["number"] for account in accounts]
    _LOGGER.info("Found %d accounts: %s", len(account_numbers), account_numbers)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "account_numbers": account_numbers,
            "account_number": account_numbers[0],
        },
    )
    return account_numbers


async def async_setup_entry(
    hass: HomeAssistant, entry: OctopusEnergyITConfigEntry
) -> bool:
    """Set up Octopus Energy Italy from a config entry."""
    session = async_get_clientsession(hass)
    api = OctopusEnergyIT(entry.data["email"], entry.data["password"], session)

    # Log in once; the token (and refresh token) is reused afterwards.
    try:
        await api.authenticate()
    except OctopusEnergyITAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except OctopusEnergyITConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from err

    account_numbers = await _async_account_numbers(hass, entry, api)
    public_products_coordinator = await async_get_public_products_coordinator(
        hass, session
    )

    coordinator = OctopusEnergyITDataUpdateCoordinator(
        hass, entry, api, account_numbers, public_products_coordinator
    )
    await coordinator.async_config_entry_first_refresh()

    # A single public-tariffs device exists per Home Assistant instance.
    public_owner = hass.data.setdefault(DOMAIN, {}).setdefault(
        "public_owner", entry.entry_id
    )
    entry.runtime_data = OctopusEnergyITRuntimeData(
        api=api,
        coordinator=coordinator,
        account_number=account_numbers[0],
        account_numbers=account_numbers,
        public_products_coordinator=public_products_coordinator,
        public_device_id=PUBLIC_DEVICE_IDENTIFIER,
        owns_public_products=public_owner == entry.entry_id,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OctopusEnergyITConfigEntry
) -> bool:
    """Unload a config entry."""
    if not (
        unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    ):
        return False

    for account_number in entry.runtime_data.account_numbers:
        ir.async_delete_issue(hass, DOMAIN, f"no_electricity_tariff_{account_number}")

    remaining = [
        other.entry_id
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED
    ]
    domain_data = hass.data.get(DOMAIN, {})
    if not remaining:
        async_release_public_products(hass)
    elif domain_data.get("public_owner") == entry.entry_id:
        # Another entry takes over the public-tariffs device on its next reload.
        domain_data["public_owner"] = remaining[0]
    return unload_ok

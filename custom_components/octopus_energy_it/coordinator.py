"""Data update coordinators and runtime data for Octopus Energy Italy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .data_processor import process_api_data
from .octopus_energy_it import OctopusEnergyIT
from .statistics import StatisticsImporter
from .tariff_scraper import fetch_public_tariffs

_LOGGER = logging.getLogger(__name__)

PUBLIC_PRODUCTS_UPDATE_INTERVAL = timedelta(hours=1)
PUBLIC_PRODUCTS_RETRY_DELAY = 5 * 60  # seconds — used with async_call_later
PUBLIC_DEVICE_IDENTIFIER = "octopus_public_tariffs"


@dataclass
class OctopusEnergyITRuntimeData:
    """Objects shared by all platforms of one config entry."""

    api: OctopusEnergyIT
    coordinator: OctopusEnergyITDataUpdateCoordinator
    account_number: str | None
    account_numbers: list[str]
    public_products_coordinator: DataUpdateCoordinator
    public_device_id: str = PUBLIC_DEVICE_IDENTIFIER
    owns_public_products: bool = False


type OctopusEnergyITConfigEntry = ConfigEntry[OctopusEnergyITRuntimeData]


def update_electricity_tariff_issue(
    hass: HomeAssistant, account_number: str, has_tariff: bool
) -> None:
    """Create or clear the repair issue for an account with no active tariff."""
    issue_id = f"no_electricity_tariff_{account_number}"
    if has_tariff:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    else:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="no_electricity_tariff",
            translation_placeholders={"account_number": account_number},
        )


def update_device_reauth_issues(
    hass: HomeAssistant, devices: list[dict[str, Any]] | None
) -> None:
    """Raise a repair for each smart device whose link must be re-authorised.

    Kraken sets ``reAuthenticationState.isEligible`` when the connection to
    the vehicle or charger maker has expired; it can only be renewed in the
    Octopus app, so the repair is informational.
    """
    for device in devices or []:
        device_id = device.get("id")
        if not device_id:
            continue
        issue_id = f"device_reauthentication_{device_id}"
        state = device.get("reAuthenticationState") or {}
        if state.get("isEligible"):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="device_reauthentication_required",
                translation_placeholders={"device": device.get("name") or device_id},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


class OctopusEnergyITDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and process the data of every account of one Octopus login."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: OctopusEnergyIT,
        account_numbers: list[str],
        public_products_coordinator: DataUpdateCoordinator,
    ) -> None:
        """Initialise the coordinator for *account_numbers*."""
        primary = account_numbers[0] if account_numbers else None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{primary}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.api = api
        self.account_numbers = account_numbers
        self.public_products_coordinator = public_products_coordinator
        self.statistics = StatisticsImporter(hass)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data for all accounts; failing accounts are skipped."""
        if self.public_products_coordinator.data is None:
            await self.public_products_coordinator.async_request_refresh()
        available_products = self.public_products_coordinator.data or {}

        all_accounts_data: dict[str, Any] = {}
        for account_number in self.account_numbers:
            try:
                account_data = await self.api.fetch_all_data(account_number)
                if not account_data:
                    _LOGGER.warning(
                        "Failed to fetch data for account %s", account_number
                    )
                    continue
                processed = await process_api_data(
                    account_data, account_number, self.api, available_products
                )
            except Exception:
                _LOGGER.exception("Error fetching data for account %s", account_number)
                continue

            all_accounts_data.update(processed)
            update_electricity_tariff_issue(
                self.hass,
                account_number,
                processed[account_number].get("has_electricity_tariff", False),
            )
            update_device_reauth_issues(
                self.hass, processed[account_number].get("devices")
            )
            try:
                await self.statistics.async_import_account(
                    account_number, processed[account_number]
                )
            except Exception:
                # Statistics are a best-effort extra: never fail the update.
                _LOGGER.exception(
                    "Failed to import statistics for account %s", account_number
                )

        if self.api.auth_failed:
            # The stored password was rejected: start the reauth flow.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            )
        if not all_accounts_data:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="update_failed"
            )
        return all_accounts_data


def build_public_products_updater(
    hass: HomeAssistant, session: aiohttp.ClientSession, domain_data: dict[str, Any]
):
    """Return the update method of the public-tariffs coordinator.

    On a scraping failure it serves the cached tariffs (if any) and schedules a
    one-shot retry with ``hass.async_call_later``; changing the coordinator's
    ``update_interval`` at runtime would have no effect on the next poll.
    """

    def _cancel_retry() -> None:
        unsub = domain_data.pop("public_products_retry_unsub", None)
        if unsub is not None:
            unsub()

    def _schedule_retry() -> None:
        _cancel_retry()

        @callback
        def _do_retry(_now) -> None:
            domain_data.pop("public_products_retry_unsub", None)
            shared = domain_data.get("public_products_coordinator")
            if shared is not None:
                hass.async_create_task(shared.async_request_refresh())

        domain_data["public_products_retry_unsub"] = hass.async_call_later(
            PUBLIC_PRODUCTS_RETRY_DELAY, _do_retry
        )
        _LOGGER.debug(
            "Scheduled public tariffs retry in %ds", PUBLIC_PRODUCTS_RETRY_DELAY
        )

    async def _async_update_public_products() -> dict[str, Any]:
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
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="public_tariffs_unavailable"
            )
        _cancel_retry()
        domain_data["public_products_cache"] = products
        return products

    return _async_update_public_products


async def async_get_public_products_coordinator(
    hass: HomeAssistant, session: aiohttp.ClientSession
) -> DataUpdateCoordinator:
    """Return the public-tariffs coordinator shared by all config entries."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    coordinator = domain_data.get("public_products_coordinator")
    if coordinator is not None:
        if coordinator.data is None:
            await coordinator.async_request_refresh()
        return coordinator

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_public_products",
        update_method=build_public_products_updater(hass, session, domain_data),
        update_interval=PUBLIC_PRODUCTS_UPDATE_INTERVAL,
    )
    await coordinator.async_refresh()
    domain_data["public_products_coordinator"] = coordinator
    return coordinator


def async_release_public_products(hass: HomeAssistant) -> None:
    """Drop the shared public-tariffs state once no entry is loaded."""
    domain_data = hass.data.get(DOMAIN, {})
    unsub = domain_data.pop("public_products_retry_unsub", None)
    if unsub is not None:
        unsub()
    domain_data.pop("public_products_coordinator", None)
    domain_data.pop("public_products_cache", None)
    domain_data.pop("public_owner", None)

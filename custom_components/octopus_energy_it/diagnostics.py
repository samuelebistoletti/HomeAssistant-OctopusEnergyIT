"""Diagnostics support for Octopus Energy Italy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import OctopusEnergyITConfigEntry

# Personal or secret values that must never appear in a diagnostics download.
TO_REDACT = {
    "email",
    "password",
    "token",
    "refreshToken",
    "account_data",
    "account_number",
    "account_numbers",
    "number",
    "pod",
    "pdr",
    "electricity_pod",
    "marketSupplyPointId",
    "supplyPointId",
    "deviceId",
    "gas_pdr",
    "address",
    "billingAddress",
    "billingName",
    "integrationDeviceId",
    "termsAndConditionsUrl",
}

RAW_MEASUREMENTS = 10


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OctopusEnergyITConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry.

    Besides the processed coordinator data it includes the most recent raw
    electricity register readings, which is what is needed to investigate
    unexpected consumption deltas.
    """
    runtime = entry.runtime_data
    coordinator = runtime.coordinator

    accounts: dict[str, Any] = {}
    for index, (account_number, account) in enumerate(
        (coordinator.data or {}).items(), start=1
    ):
        raw_measurements: list[dict[str, Any]] | str = []
        property_id = account.get("electricity_property_id")
        pod = account.get("electricity_pod")
        if property_id and pod:
            try:
                raw_measurements = async_redact_data(
                    [
                        measurement.get("raw", measurement)
                        for measurement in await runtime.api.fetch_electricity_measurements(
                            property_id, pod, last=RAW_MEASUREMENTS
                        )
                    ],
                    TO_REDACT,
                )
            except Exception as err:  # noqa: BLE001 - diagnostics must not fail
                raw_measurements = f"unavailable: {err}"

        # Key accounts by position so account numbers are not leaked.
        accounts[f"account_{index}"] = {
            "data": async_redact_data(account, TO_REDACT),
            "raw_electricity_measurements": raw_measurements,
            "is_primary": account_number == runtime.account_number,
        }

    return {
        "entry": {
            "title": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "accounts": accounts,
        "public_products_available": bool(runtime.public_products_coordinator.data),
    }

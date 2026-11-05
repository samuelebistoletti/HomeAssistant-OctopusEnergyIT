"""Tests for the diagnostics platform."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.octopus_energy_it.diagnostics import (
    async_get_config_entry_diagnostics,
)

SECRETS = ("user@example.com", "hunter2", "A-1234ABCD", "IT001E12345678", "PDR999")


def _entry(fetch=None):
    api = SimpleNamespace(
        fetch_electricity_measurements=fetch
        or AsyncMock(
            return_value=[
                {"value": 10.0, "raw": {"value": "10.0", "readAt": "2026-11-01"}}
            ]
        )
    )
    coordinator = SimpleNamespace(
        last_update_success=True,
        update_interval="0:01:00",
        data={
            "A-1234ABCD": {
                "account_number": "A-1234ABCD",
                "electricity_pod": "IT001E12345678",
                "electricity_property_id": "42",
                "gas_pdr": "PDR999",
                "electricity_balance": 12.5,
                "account": {
                    "properties": [
                        {"electricitySupplyPoints": [{"pod": "IT001E12345678"}]}
                    ]
                },
            }
        },
    )
    runtime = SimpleNamespace(
        api=api,
        coordinator=coordinator,
        account_number="A-1234ABCD",
        public_products_coordinator=SimpleNamespace(data={"electricity": []}),
    )
    return SimpleNamespace(
        data={
            "email": "user@example.com",
            "password": "hunter2",
            "account_numbers": ["A-1234ABCD"],
        },
        runtime_data=runtime,
    )


async def test_diagnostics_redact_personal_data():
    result = await async_get_config_entry_diagnostics(None, _entry())
    dumped = json.dumps(result)

    for secret in SECRETS:
        assert secret not in dumped
    assert result["accounts"]["account_1"]["data"]["electricity_balance"] == 12.5


async def test_diagnostics_include_raw_measurements():
    entry = _entry()
    result = await async_get_config_entry_diagnostics(None, entry)

    assert result["accounts"]["account_1"]["raw_electricity_measurements"] == [
        {"value": "10.0", "readAt": "2026-11-01"}
    ]
    entry.runtime_data.api.fetch_electricity_measurements.assert_awaited_once_with(
        "42", "IT001E12345678", last=10
    )


async def test_diagnostics_survive_measurement_errors():
    entry = _entry(fetch=AsyncMock(side_effect=RuntimeError("down")))
    result = await async_get_config_entry_diagnostics(None, entry)

    assert result["accounts"]["account_1"]["raw_electricity_measurements"].startswith(
        "unavailable"
    )

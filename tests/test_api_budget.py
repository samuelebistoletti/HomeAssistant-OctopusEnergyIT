"""Tests for the API-budget measures: reading cache and dispatch fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.octopus_energy_it import octopus_energy_it as client_mod
from custom_components.octopus_energy_it.octopus_energy_it import OctopusEnergyIT

READINGS = [{"readAt": "2026-11-05T00:00:00+01:00", "value": 10.0}]


def _api():
    api = OctopusEnergyIT("a@example.com", "pw")
    api._token_manager.set_token("tok", expiry=4102444800)
    return api


async def test_electricity_readings_are_cached():
    api = _api()
    fetch = AsyncMock(return_value=READINGS)
    with patch.object(api, "_fetch_electricity_measurements", new=fetch):
        assert await api.fetch_electricity_measurements("p", "pod", last=10) == READINGS
        assert await api.fetch_electricity_measurements("p", "pod", last=10) == READINGS
        fetch.assert_awaited_once()

        # A different window is a different request.
        await api.fetch_electricity_measurements("p", "pod", last=2)
        assert fetch.await_count == 2


async def test_cache_expires():
    api = _api()
    fetch = AsyncMock(return_value=READINGS)
    with patch.object(api, "_fetch_electricity_measurements", new=fetch):
        await api.fetch_electricity_measurements("p", "pod", last=10)
        key = next(iter(api._readings_cache))
        api._readings_cache[key] = (0.0, READINGS)
        await api.fetch_electricity_measurements("p", "pod", last=10)
    assert fetch.await_count == 2


async def test_empty_readings_are_not_cached():
    api = _api()
    fetch = AsyncMock(side_effect=[[], READINGS])
    with patch.object(api, "_fetch_gas_meter_readings", new=fetch):
        assert await api.fetch_gas_meter_readings("A-1", "pdr", first=5) == []
        assert await api.fetch_gas_meter_readings("A-1", "pdr", first=5) == READINGS


async def test_rate_limited_dispatches_keep_the_last_plan():
    api = _api()
    plan = [{"start": "2026-11-06T18:30:00+00:00", "end": "2026-11-07T03:00:00+00:00"}]
    rate_limited = {
        "errors": [
            {"message": "Too many requests.", "extensions": {"errorCode": "KT-CT-1199"}}
        ]
    }
    execute = AsyncMock(
        side_effect=[{"data": {"flexPlannedDispatches": plan}}, rate_limited]
    )
    with patch.object(api, "_execute_graphql", new=execute):
        assert await api.fetch_flex_planned_dispatches("dev") == plan
        assert await api.fetch_flex_planned_dispatches("dev") == plan


async def test_dispatch_error_without_history_returns_none():
    api = _api()
    with patch.object(
        api,
        "_execute_graphql",
        new=AsyncMock(return_value={"errors": [{"message": "x"}]}),
    ):
        assert await api.fetch_flex_planned_dispatches("dev") is None


def test_unused_completed_dispatches_are_not_requested():
    assert "completedDispatches" not in client_mod.COMPREHENSIVE_QUERY

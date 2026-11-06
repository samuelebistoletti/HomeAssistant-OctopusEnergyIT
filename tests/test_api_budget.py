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


# ---------------------------------------------------------------------------
# Two-speed polling
# ---------------------------------------------------------------------------

ACCOUNT = {"id": "1", "ledgers": [], "properties": []}
DEVICE = {"id": "dev", "deviceType": "ELECTRIC_VEHICLES", "status": {"current": "LIVE"}}


def _full(account=ACCOUNT, devices=(DEVICE,)):
    return {"data": {"account": dict(account), "devices": list(devices)}}


def _devices(devices=(DEVICE,)):
    return {"data": {"devices": list(devices)}}


async def _fetch(api, responses):
    execute = AsyncMock(side_effect=responses)
    with (
        patch.object(api, "_execute_graphql", new=execute),
        patch.object(
            api, "fetch_flex_planned_dispatches", new=AsyncMock(return_value=[])
        ),
        patch.object(api, "_attach_charging_sessions", new=AsyncMock()),
    ):
        result = await api.fetch_all_data("A-1")
    return result, execute


async def test_first_poll_runs_the_full_query_then_devices_only():
    api = _api()
    first, execute = await _fetch(api, [_full()])
    assert execute.await_args.args[0] == client_mod.COMPREHENSIVE_QUERY

    second, execute = await _fetch(api, [_devices()])
    assert execute.await_args.args[0] == client_mod.DEVICES_QUERY
    assert second["account"] == first["account"]
    assert second["devices"] == [DEVICE]


async def test_full_query_again_after_account_refresh_interval():
    api = _api()
    await _fetch(api, [_full()])
    stamp, cached = api._account_cache["A-1"]
    api._account_cache["A-1"] = (stamp - client_mod.ACCOUNT_REFRESH - 1, cached)

    _result, execute = await _fetch(api, [_full()])
    assert execute.await_args.args[0] == client_mod.COMPREHENSIVE_QUERY


async def test_failed_full_query_reuses_cached_account():
    api = _api()
    first, _ = await _fetch(api, [_full()])
    stamp, cached = api._account_cache["A-1"]
    api._account_cache["A-1"] = (stamp - client_mod.ACCOUNT_REFRESH - 1, cached)

    result, _ = await _fetch(api, [{"data": {"account": None, "devices": [DEVICE]}}])
    assert result["account"] == first["account"]


def test_devices_query_is_the_devices_block_of_the_full_query():
    assert client_mod.DEVICES_QUERY.strip().startswith("query DevicesQuery(")
    assert "account(accountNumber" not in client_mod.DEVICES_QUERY
    assert "devices(accountNumber: $accountNumber)" in client_mod.DEVICES_QUERY


async def test_dispatches_are_throttled_per_device():
    api = _api()
    execute = AsyncMock(return_value={"data": {"flexPlannedDispatches": []}})
    with patch.object(api, "_execute_graphql", new=execute):
        await api.fetch_flex_planned_dispatches("dev", min_interval=30)
        await api.fetch_flex_planned_dispatches("dev", min_interval=30)
        assert execute.await_count == 1

        api._dispatches_requested_at["dev"] -= 31
        await api.fetch_flex_planned_dispatches("dev", min_interval=30)
        assert execute.await_count == 2


def test_dispatch_budget_stays_below_kraken_limit():
    # min_interval = 60 * devices / 4 s keeps the total at <= 4 requests a minute.
    for devices in range(1, 6):
        interval = 60 * devices / client_mod.DISPATCH_REQUESTS_PER_MINUTE
        assert devices * 60 / interval < 5  # Kraken limit: 5 requests a minute

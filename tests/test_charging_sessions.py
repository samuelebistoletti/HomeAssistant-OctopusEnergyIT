"""Tests for the last charging session (API client and sensor)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components.octopus_energy_it import octopus_energy_it as client_mod
from custom_components.octopus_energy_it.octopus_energy_it import OctopusEnergyIT
from custom_components.octopus_energy_it.sensor import OctopusLastChargingSessionSensor

NODE = {
    "start": "2026-11-05T22:00:00+00:00",
    "end": "2026-11-06T03:30:00+00:00",
    "stateOfChargeChange": "35.0",
    "stateOfChargeFinal": "80.0",
    "energyAdded": {"value": "21.4", "unit": "KILOWATT_HOUR"},
    "cost": {
        "amountAsMinorUnits": 297,
        "currencyDetails": {"iso4217CurrencyCode": "EUR"},
    },
    "type": "SMART",
}


def _response(nodes, has_previous=False):
    return {
        "data": {
            "devices": [
                {
                    "id": "dev-1",
                    "chargingSessions": {
                        "pageInfo": {"hasPreviousPage": has_previous},
                        "edges": [{"node": n} for n in nodes],
                    },
                }
            ]
        }
    }


def _node(start):
    return {**NODE, "start": start}


def _api():
    api = OctopusEnergyIT("a@example.com", "pw")
    api._token_manager.set_token("tok", expiry=4102444800)
    return api


async def test_session_is_flattened():
    api = _api()
    with patch.object(
        api, "_execute_graphql", new=AsyncMock(return_value=_response([NODE]))
    ):
        sessions = await api.fetch_charging_sessions("A-1", "dev-1")

    assert sessions == [
        {
            "start": NODE["start"],
            "end": NODE["end"],
            "energy_kwh": 21.4,
            "cost": 2.97,
            "currency": "EUR",
            "type": "SMART",
            "soc_change": 35.0,
            "soc_final": 80.0,
        }
    ]


async def test_first_fetch_reads_the_whole_history_in_pages():
    api = _api()
    execute = AsyncMock(
        side_effect=[
            _response([_node("2026-11-10T00:00:00Z")], has_previous=True),
            _response([_node("2026-11-01T00:00:00Z")], has_previous=False),
        ]
    )
    with patch.object(api, "_execute_graphql", new=execute):
        sessions = await api.fetch_charging_sessions("A-1", "dev-1")

    assert [s["start"] for s in sessions] == [
        "2026-11-01T00:00:00Z",
        "2026-11-10T00:00:00Z",
    ]
    first, second = (call.kwargs["variables"] for call in execute.await_args_list)
    assert first["last"] == client_mod.CHARGING_SESSION_PAGE
    assert first["before"] is None
    # ``before`` is a DateTime: the start of the oldest session read so far.
    assert second["before"] == "2026-11-10T00:00:00Z"


async def test_history_paging_stops_at_the_page_cap():
    api = _api()
    execute = AsyncMock(
        side_effect=[
            _response([_node(f"2026-10-{30 - i:02d}T00:00:00Z")], has_previous=True)
            for i in range(client_mod.CHARGING_SESSION_MAX_PAGES)
        ]
    )
    with patch.object(api, "_execute_graphql", new=execute):
        sessions = await api.fetch_charging_sessions("A-1", "dev-1")

    assert execute.await_count == client_mod.CHARGING_SESSION_MAX_PAGES
    assert len(sessions) == client_mod.CHARGING_SESSION_MAX_PAGES


async def test_later_fetches_read_only_recent_sessions_after_the_cache():
    api = _api()
    execute = AsyncMock(return_value=_response([NODE], has_previous=True))
    with patch.object(api, "_execute_graphql", new=execute):
        await api.fetch_charging_sessions("A-1", "dev-1")  # history: 10 pages
        calls = execute.await_count
        await api.fetch_charging_sessions("A-1", "dev-1")  # cached
        assert execute.await_count == calls

        api._charging_sessions["dev-1"] = (0.0, [])  # expire the cache
        await api.fetch_charging_sessions("A-1", "dev-1")

    assert execute.await_count == calls + 1
    variables = execute.await_args.kwargs["variables"]
    assert variables["last"] == client_mod.CHARGING_SESSION_RECENT
    assert variables["before"] is None


async def test_no_sessions_returns_empty_and_errors_keep_cache():
    api = _api()
    with patch.object(
        api, "_execute_graphql", new=AsyncMock(return_value=_response([]))
    ):
        assert await api.fetch_charging_sessions("A-1", "dev-1") == []

    api._charging_sessions["dev-1"] = (0.0, [{"energy_kwh": 5.0}])
    with patch.object(
        api,
        "_execute_graphql",
        new=AsyncMock(return_value={"errors": [{"message": "x"}]}),
    ):
        assert await api.fetch_charging_sessions("A-1", "dev-1") == [
            {"energy_kwh": 5.0}
        ]


async def test_error_during_history_keeps_pages_and_retries_later():
    api = _api()
    execute = AsyncMock(
        side_effect=[
            _response([_node("2026-11-10T00:00:00Z")], has_previous=True),
            {"errors": [{"message": "rate limited"}]},
        ]
    )
    with patch.object(api, "_execute_graphql", new=execute):
        sessions = await api.fetch_charging_sessions("A-1", "dev-1")

    assert [s["start"] for s in sessions] == ["2026-11-10T00:00:00Z"]
    assert "dev-1" not in api._sessions_backfilled


async def test_sessions_attached_only_to_ev_and_charge_points():
    api = _api()
    devices = [
        {"id": "ev", "deviceType": "ELECTRIC_VEHICLES"},
        {"id": "hp", "deviceType": "HEAT_PUMPS"},
    ]
    sessions = [{"energy_kwh": 1.0}, {"energy_kwh": 2.0}]
    with patch.object(
        api, "fetch_charging_sessions", new=AsyncMock(return_value=sessions)
    ) as fetch:
        await api._attach_charging_sessions("A-1", devices)

    fetch.assert_awaited_once_with("A-1", "ev")
    assert devices[0]["chargingSessions"] == sessions
    assert devices[0]["lastChargingSession"] == {"energy_kwh": 2.0}
    assert "lastChargingSession" not in devices[1]


async def test_device_without_sessions_has_no_last_session():
    api = _api()
    devices = [{"id": "ev", "deviceType": "CHARGE_POINTS"}]
    with patch.object(api, "fetch_charging_sessions", new=AsyncMock(return_value=[])):
        await api._attach_charging_sessions("A-1", devices)

    assert devices[0]["chargingSessions"] == []
    assert devices[0]["lastChargingSession"] is None


def test_sensor_reads_the_device_session():
    coordinator = SimpleNamespace(
        data={
            "A-1": {
                "devices": [
                    {
                        "id": "dev-1",
                        "lastChargingSession": {
                            "energy_kwh": 21.4,
                            "cost": 2.97,
                            "type": "SMART",
                        },
                    }
                ]
            }
        }
    )
    sensor = OctopusLastChargingSessionSensor("A-1", coordinator, "dev-1")

    assert sensor._attr_unique_id == "octopus_A-1_dev-1_last_charging_session"
    assert sensor.native_value == 21.4
    assert sensor.extra_state_attributes["cost"] == 2.97
    assert sensor.extra_state_attributes["session_type"] == "SMART"


async def test_boost_input_includes_target_and_end_time():
    from datetime import UTC, datetime

    api = _api()
    execute = AsyncMock(return_value={"data": {"updateBoostCharge": {"id": "dev-1"}}})
    end = datetime(2026, 11, 7, 6, 12, 40, tzinfo=UTC)  # rounded up to 06:30
    with patch.object(api, "_execute_graphql", new=execute):
        assert (
            await api.update_boost_charge(
                "dev-1", "BOOST", target_percentage=80, end_time=end
            )
            == "dev-1"
        )

    assert execute.await_args.kwargs["variables"] == {
        "input": {
            "deviceId": "dev-1",
            "action": "BOOST",
            "targetSocPercentage": 80,
            "endTime": "2026-11-07T06:30:00+00:00",
        }
    }


async def test_plain_boost_input_is_unchanged():
    api = _api()
    execute = AsyncMock(return_value={"data": {"updateBoostCharge": {"id": "dev-1"}}})
    with patch.object(api, "_execute_graphql", new=execute):
        await api.update_boost_charge("dev-1", "CANCEL")
    assert execute.await_args.kwargs["variables"] == {
        "input": {"deviceId": "dev-1", "action": "CANCEL"}
    }


def test_round_up_to_half_hour():
    from datetime import UTC, datetime

    from custom_components.octopus_energy_it.octopus_energy_it import (
        round_up_to_half_hour,
    )

    def at(h, m, s=0):
        return datetime(2026, 11, 7, h, m, s, tzinfo=UTC)

    assert round_up_to_half_hour(at(6, 0)) == at(6, 0)
    assert round_up_to_half_hour(at(6, 30)) == at(6, 30)
    assert round_up_to_half_hour(at(6, 0, 1)) == at(6, 30)
    assert round_up_to_half_hour(at(6, 12)) == at(6, 30)
    assert round_up_to_half_hour(at(6, 31)) == at(7, 0)
    assert round_up_to_half_hour(at(23, 45)) == datetime(2026, 11, 8, 0, 0, tzinfo=UTC)

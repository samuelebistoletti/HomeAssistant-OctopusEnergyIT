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


def _response(nodes):
    return {
        "data": {
            "devices": [
                {
                    "id": "dev-1",
                    "chargingSessions": {"edges": [{"node": n} for n in nodes]},
                }
            ]
        }
    }


def _api():
    api = OctopusEnergyIT("a@example.com", "pw")
    api._token_manager.set_token("tok", expiry=4102444800)
    return api


async def test_session_is_flattened():
    api = _api()
    with patch.object(
        api, "_execute_graphql", new=AsyncMock(return_value=_response([NODE]))
    ):
        session = await api.fetch_last_charging_session("A-1", "dev-1")

    assert session == {
        "start": NODE["start"],
        "end": NODE["end"],
        "energy_kwh": 21.4,
        "cost": 2.97,
        "currency": "EUR",
        "type": "SMART",
        "soc_change": 35.0,
        "soc_final": 80.0,
    }


async def test_session_is_cached_for_fifteen_minutes():
    api = _api()
    execute = AsyncMock(return_value=_response([NODE]))
    with patch.object(api, "_execute_graphql", new=execute):
        await api.fetch_last_charging_session("A-1", "dev-1")
        await api.fetch_last_charging_session("A-1", "dev-1")
        execute.assert_awaited_once()

        api._charging_sessions["dev-1"] = (0.0, None)  # expire the cache
        await api.fetch_last_charging_session("A-1", "dev-1")
        assert execute.await_count == 2


async def test_no_sessions_returns_none_and_errors_keep_cache():
    api = _api()
    with patch.object(
        api, "_execute_graphql", new=AsyncMock(return_value=_response([]))
    ):
        assert await api.fetch_last_charging_session("A-1", "dev-1") is None

    api._charging_sessions["dev-1"] = (0.0, {"energy_kwh": 5.0})
    with patch.object(
        api,
        "_execute_graphql",
        new=AsyncMock(return_value={"errors": [{"message": "x"}]}),
    ):
        assert await api.fetch_last_charging_session("A-1", "dev-1") == {
            "energy_kwh": 5.0
        }


async def test_sessions_attached_only_to_ev_and_charge_points():
    api = _api()
    devices = [
        {"id": "ev", "deviceType": "ELECTRIC_VEHICLES"},
        {"id": "hp", "deviceType": "HEAT_PUMPS"},
    ]
    with patch.object(
        api,
        "fetch_last_charging_session",
        new=AsyncMock(return_value={"energy_kwh": 1.0}),
    ) as fetch:
        await api._attach_charging_sessions("A-1", devices)

    fetch.assert_awaited_once_with("A-1", "ev")
    assert devices[0]["lastChargingSession"] == {"energy_kwh": 1.0}
    assert "lastChargingSession" not in devices[1]


def test_query_requests_only_the_last_session():
    assert "chargingSessions(last: 1)" in client_mod.LAST_CHARGING_SESSION_QUERY


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
    end = datetime(2026, 11, 7, 6, 30, tzinfo=UTC)
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

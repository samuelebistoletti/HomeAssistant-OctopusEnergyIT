"""Tests for the gas self-reading (API client and action). Nothing is sent."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.octopus_energy_it import services as services_mod
from custom_components.octopus_energy_it.octopus_energy_it import (
    OctopusEnergyIT,
    OctopusEnergyITConnectionError,
    OctopusEnergyITRequestError,
)

PDR = "00000000000000"


def _api():
    api = OctopusEnergyIT("a@example.com", "pw")
    api._token_manager.set_token("tok", expiry=4102444800)
    return api


class TestSubmitGasSelfReading:
    async def test_sends_pdr_value_and_date(self):
        api = _api()
        execute = AsyncMock(
            return_value={"data": {"submitGasSelfReading": {"submitted": True}}}
        )
        with patch.object(api, "_execute_graphql", new=execute):
            await api.submit_gas_self_reading(PDR, 540, date(2026, 11, 6))

        assert execute.await_args.kwargs["variables"] == {
            "input": {"pdr": PDR, "consumptionValue": 540, "readingDate": "2026-11-06"}
        }

    async def test_date_is_optional(self):
        api = _api()
        execute = AsyncMock(
            return_value={"data": {"submitGasSelfReading": {"submitted": True}}}
        )
        with patch.object(api, "_execute_graphql", new=execute):
            await api.submit_gas_self_reading(PDR, 540)
        assert "readingDate" not in execute.await_args.kwargs["variables"]["input"]

    async def test_kraken_error_code_is_raised(self):
        api = _api()
        response = {
            "errors": [
                {
                    "message": "Reading not needed",
                    "extensions": {"errorCode": "KT-IT-6411"},
                }
            ]
        }
        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)),
            pytest.raises(OctopusEnergyITRequestError) as err,
        ):
            await api.submit_gas_self_reading(PDR, 540)
        assert err.value.code == "KT-IT-6411"

    async def test_not_submitted_raises(self):
        api = _api()
        response = {"data": {"submitGasSelfReading": {"submitted": False}}}
        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)),
            pytest.raises(OctopusEnergyITRequestError),
        ):
            await api.submit_gas_self_reading(PDR, 540)

    async def test_no_response_is_a_connection_error(self):
        api = _api()
        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)),
            pytest.raises(OctopusEnergyITConnectionError),
        ):
            await api.submit_gas_self_reading(PDR, 540)


def _hass(accounts, state=ConfigEntryState.LOADED):
    api = MagicMock()
    api.submit_gas_self_reading = AsyncMock()
    runtime = SimpleNamespace(
        api=api,
        coordinator=SimpleNamespace(data=accounts, async_request_refresh=AsyncMock()),
    )
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(
        return_value=[SimpleNamespace(state=state, runtime_data=runtime)]
    )
    return hass, api, runtime


def _gas_account(last=534.0):
    return {"gas_pdr": PDR, "gas_last_reading": {"value": last}}


def _call(hass, **data):
    return SimpleNamespace(hass=hass, data=data)


class TestSubmitGasReadingAction:
    async def test_submits_to_the_only_gas_account(self):
        hass, api, runtime = _hass({"A-1": _gas_account(), "A-2": {"gas_pdr": None}})
        await services_mod._async_submit_gas_reading(_call(hass, reading=540))

        api.submit_gas_self_reading.assert_awaited_once_with(PDR, 540, None)
        runtime.coordinator.async_request_refresh.assert_awaited_once()

    async def test_reading_below_last_is_rejected_before_sending(self):
        hass, api, _ = _hass({"A-1": _gas_account(last=534.0)})
        with pytest.raises(ServiceValidationError) as err:
            await services_mod._async_submit_gas_reading(_call(hass, reading=53))
        assert err.value.translation_key == "gas_reading_below_last"
        api.submit_gas_self_reading.assert_not_awaited()

    async def test_two_gas_accounts_need_account_number(self):
        hass, api, _ = _hass({"A-1": _gas_account(), "A-2": _gas_account()})
        with pytest.raises(ServiceValidationError) as err:
            await services_mod._async_submit_gas_reading(_call(hass, reading=540))
        assert err.value.translation_key == "gas_account_ambiguous"

        await services_mod._async_submit_gas_reading(
            _call(hass, reading=540, account_number="A-2")
        )
        api.submit_gas_self_reading.assert_awaited_once()

    async def test_unknown_account_number(self):
        hass, _, _ = _hass({"A-1": _gas_account()})
        with pytest.raises(ServiceValidationError) as err:
            await services_mod._async_submit_gas_reading(
                _call(hass, reading=540, account_number="A-9")
            )
        assert err.value.translation_key == "gas_account_not_found"

    @pytest.mark.parametrize(
        ("code", "key"),
        [
            ("KT-IT-6410", "gas_reading_invalid"),
            ("KT-IT-6411", "gas_reading_not_needed"),
        ],
    )
    async def test_kraken_errors_are_translated(self, code, key):
        hass, api, _ = _hass({"A-1": _gas_account()})
        api.submit_gas_self_reading.side_effect = OctopusEnergyITRequestError(code, "x")
        with pytest.raises(ServiceValidationError) as err:
            await services_mod._async_submit_gas_reading(_call(hass, reading=540))
        assert err.value.translation_key == key

    async def test_other_failures_raise_home_assistant_error(self):
        hass, api, _ = _hass({"A-1": _gas_account()})
        api.submit_gas_self_reading.side_effect = OctopusEnergyITConnectionError()
        with pytest.raises(HomeAssistantError) as err:
            await services_mod._async_submit_gas_reading(_call(hass, reading=540))
        assert err.value.translation_key == "gas_reading_failed"
        assert not isinstance(err.value, ServiceValidationError)

    def test_schema_requires_non_negative_integer(self):
        import voluptuous as vol

        data = services_mod.SUBMIT_GAS_READING_SCHEMA(
            {"reading": "540", "reading_date": "2026-11-06"}
        )
        assert data == {"reading": 540, "reading_date": date(2026, 11, 6)}
        with pytest.raises(vol.Invalid):
            services_mod.SUBMIT_GAS_READING_SCHEMA({"reading": -1})

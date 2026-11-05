"""Tests for setup/unload, the account coordinator and the service actions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.octopus_energy_it.__init__ as init_mod
from custom_components.octopus_energy_it import (
    coordinator as coord_mod,
    services as services_mod,
)
from custom_components.octopus_energy_it.const import DOMAIN
from custom_components.octopus_energy_it.coordinator import (
    OctopusEnergyITDataUpdateCoordinator,
    OctopusEnergyITRuntimeData,
)
from custom_components.octopus_energy_it.octopus_energy_it import (
    OctopusEnergyITAuthError,
    OctopusEnergyITConnectionError,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

ACCOUNT = "A-1234ABCD"
DEVICE_ID = "device-1"


def _api(**overrides):
    api = MagicMock()
    api.auth_failed = False
    api.authenticate = AsyncMock()
    api.fetch_all_data = AsyncMock(return_value={"account": {"id": "1"}})
    api.fetch_accounts = AsyncMock(return_value=[{"number": ACCOUNT}])
    api.set_device_preferences = AsyncMock(return_value=True)
    api.format_time_to_hh_mm = MagicMock(side_effect=lambda value: value[:5])
    for key, value in overrides.items():
        setattr(api, key, value)
    return api


def _public_coordinator(data=None):
    return SimpleNamespace(data=data or {}, async_request_refresh=AsyncMock())


def _coordinator(api, accounts=(ACCOUNT,)):
    return OctopusEnergyITDataUpdateCoordinator(
        MagicMock(), MagicMock(), api, list(accounts), _public_coordinator()
    )


def _processed(account, has_tariff=True):
    async def _process(_data, account_number, _api, _products):
        return {account_number: {"has_electricity_tariff": has_tariff}}

    return _process


# ---------------------------------------------------------------------------
# OctopusEnergyITDataUpdateCoordinator
# ---------------------------------------------------------------------------


class TestAccountCoordinator:
    async def test_returns_processed_data_for_every_account(self):
        api = _api()
        coordinator = _coordinator(api, accounts=("A-1", "A-2"))
        with patch.object(coord_mod, "process_api_data", new=_processed(None)):
            data = await coordinator._async_update_data()

        assert set(data) == {"A-1", "A-2"}

    async def test_failing_account_is_skipped(self):
        api = _api()
        api.fetch_all_data = AsyncMock(side_effect=[RuntimeError("boom"), {"x": 1}])
        coordinator = _coordinator(api, accounts=("A-1", "A-2"))
        with patch.object(coord_mod, "process_api_data", new=_processed(None)):
            data = await coordinator._async_update_data()

        assert set(data) == {"A-2"}

    async def test_no_data_for_any_account_raises_update_failed(self):
        api = _api(fetch_all_data=AsyncMock(return_value=None))
        with pytest.raises(UpdateFailed):
            await _coordinator(api)._async_update_data()

    async def test_rejected_credentials_raise_auth_failed(self):
        api = _api(fetch_all_data=AsyncMock(return_value=None))
        api.auth_failed = True
        with pytest.raises(ConfigEntryAuthFailed):
            await _coordinator(api)._async_update_data()

    async def test_missing_tariff_raises_repair_issue(self):
        api = _api()
        coordinator = _coordinator(api)
        with (
            patch.object(
                coord_mod, "process_api_data", new=_processed(None, has_tariff=False)
            ),
            patch.object(coord_mod, "update_electricity_tariff_issue") as issue,
        ):
            await coordinator._async_update_data()

        issue.assert_called_once_with(coordinator.hass, ACCOUNT, False)

    async def test_public_products_refreshed_when_empty(self):
        api = _api()
        coordinator = _coordinator(api)
        coordinator.public_products_coordinator.data = None
        with patch.object(coord_mod, "process_api_data", new=_processed(None)):
            await coordinator._async_update_data()

        coordinator.public_products_coordinator.async_request_refresh.assert_awaited()


# ---------------------------------------------------------------------------
# async_setup_entry / async_unload_entry
# ---------------------------------------------------------------------------


def _hass(entries=()):
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_entries = MagicMock(return_value=list(entries))
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


def _entry(entry_id="entry-1", data=None, state=ConfigEntryState.LOADED):
    return SimpleNamespace(
        entry_id=entry_id,
        state=state,
        data=data
        or {"email": "a@example.com", "password": "pw", "account_numbers": [ACCOUNT]},
        runtime_data=None,
    )


@pytest.fixture
def setup_patches():
    api = _api()
    public = _public_coordinator()
    with (
        patch.object(init_mod, "OctopusEnergyIT", return_value=api),
        patch.object(
            init_mod,
            "async_get_public_products_coordinator",
            new=AsyncMock(return_value=public),
        ),
        patch.object(
            OctopusEnergyITDataUpdateCoordinator,
            "async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
    ):
        yield api, public


class TestSetupEntry:
    async def test_success_stores_runtime_data_and_forwards_platforms(
        self, setup_patches
    ):
        api, public = setup_patches
        hass, entry = _hass(), _entry()

        assert await init_mod.async_setup_entry(hass, entry) is True

        runtime = entry.runtime_data
        assert isinstance(runtime, OctopusEnergyITRuntimeData)
        assert runtime.api is api
        assert runtime.account_numbers == [ACCOUNT]
        assert runtime.public_products_coordinator is public
        assert runtime.owns_public_products is True
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    async def test_rejected_credentials_raise_auth_failed(self, setup_patches):
        api, _ = setup_patches
        api.authenticate.side_effect = OctopusEnergyITAuthError()
        with pytest.raises(ConfigEntryAuthFailed):
            await init_mod.async_setup_entry(_hass(), _entry())

    async def test_connection_error_raises_not_ready(self, setup_patches):
        api, _ = setup_patches
        api.authenticate.side_effect = OctopusEnergyITConnectionError()
        with pytest.raises(ConfigEntryNotReady):
            await init_mod.async_setup_entry(_hass(), _entry())

    async def test_accounts_discovered_and_saved_when_missing(self, setup_patches):
        hass = _hass()
        entry = _entry(data={"email": "a@example.com", "password": "pw"})

        await init_mod.async_setup_entry(hass, entry)

        saved = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert saved["account_numbers"] == [ACCOUNT]
        assert saved["account_number"] == ACCOUNT

    async def test_no_accounts_raises_not_ready(self, setup_patches):
        api, _ = setup_patches
        api.fetch_accounts.return_value = []
        entry = _entry(data={"email": "a@example.com", "password": "pw"})
        with pytest.raises(ConfigEntryNotReady):
            await init_mod.async_setup_entry(_hass(), entry)

    async def test_second_entry_does_not_own_public_products(self, setup_patches):
        hass = _hass()
        hass.data[DOMAIN] = {"public_owner": "entry-0"}
        entry = _entry()

        await init_mod.async_setup_entry(hass, entry)

        assert entry.runtime_data.owns_public_products is False


class TestUnloadEntry:
    def _loaded(self, entry_id="entry-1"):
        entry = _entry(entry_id)
        entry.runtime_data = SimpleNamespace(account_numbers=[ACCOUNT])
        return entry

    async def test_last_entry_releases_public_products(self):
        entry = self._loaded()
        hass = _hass(entries=[entry])
        hass.data[DOMAIN] = {
            "public_owner": entry.entry_id,
            "public_products_coordinator": object(),
            "public_products_cache": {},
        }

        assert await init_mod.async_unload_entry(hass, entry) is True
        assert hass.data[DOMAIN] == {}

    async def test_ownership_moves_to_remaining_entry(self):
        entry, other = self._loaded(), self._loaded("entry-2")
        hass = _hass(entries=[entry, other])
        hass.data[DOMAIN] = {"public_owner": entry.entry_id}

        await init_mod.async_unload_entry(hass, entry)

        assert hass.data[DOMAIN]["public_owner"] == "entry-2"

    async def test_failed_platform_unload_keeps_state(self):
        entry = self._loaded()
        hass = _hass(entries=[entry])
        hass.config_entries.async_unload_platforms.return_value = False
        hass.data[DOMAIN] = {"public_owner": entry.entry_id}

        assert await init_mod.async_unload_entry(hass, entry) is False
        assert hass.data[DOMAIN] == {"public_owner": entry.entry_id}


# ---------------------------------------------------------------------------
# set_device_preferences service
# ---------------------------------------------------------------------------


def _service_hass(api, *, state=ConfigEntryState.LOADED, devices=None):
    runtime = SimpleNamespace(
        api=api,
        coordinator=SimpleNamespace(
            data={ACCOUNT: {"devices": devices or [{"id": DEVICE_ID}]}},
            async_request_refresh=AsyncMock(),
        ),
    )
    entry = SimpleNamespace(state=state, runtime_data=runtime)
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    return hass, runtime


def _call(hass, **data):
    payload = {"device_id": DEVICE_ID, "target_percentage": 80, "target_time": "07:00"}
    payload.update(data)
    return SimpleNamespace(hass=hass, data=payload)


class TestSetDevicePreferencesService:
    def test_schema_coerces_percentage(self):
        data = services_mod.SET_DEVICE_PREFERENCES_SCHEMA(
            {"device_id": DEVICE_ID, "target_percentage": "75", "target_time": "06:00"}
        )
        assert data["target_percentage"] == 75.0

    async def test_success_calls_api_and_refreshes(self):
        api = _api()
        hass, runtime = _service_hass(api)

        await services_mod._async_set_device_preferences(_call(hass))

        api.set_device_preferences.assert_awaited_once_with(DEVICE_ID, 80, "07:00")
        runtime.coordinator.async_request_refresh.assert_awaited_once()

    async def test_percentage_is_clamped(self):
        api = _api()
        hass, _ = _service_hass(api)

        await services_mod._async_set_device_preferences(
            _call(hass, target_percentage=150)
        )

        assert api.set_device_preferences.await_args.args[1] == 100

    async def test_unknown_device_raises_validation_error(self):
        hass, _ = _service_hass(_api())
        with pytest.raises(ServiceValidationError) as err:
            await services_mod._async_set_device_preferences(
                _call(hass, device_id="nope")
            )
        assert err.value.translation_key == "device_not_found"

    async def test_device_of_unloaded_entry_is_not_found(self):
        hass, _ = _service_hass(_api(), state=ConfigEntryState.NOT_LOADED)
        with pytest.raises(ServiceValidationError):
            await services_mod._async_set_device_preferences(_call(hass))

    @pytest.mark.parametrize("value", ["22:00", "03:59"])
    async def test_time_outside_window_raises_validation_error(self, value):
        hass, _ = _service_hass(_api())
        with pytest.raises(ServiceValidationError) as err:
            await services_mod._async_set_device_preferences(
                _call(hass, target_time=value)
            )
        assert err.value.translation_key == "invalid_target_time"

    async def test_unparsable_time_raises_validation_error(self):
        api = _api(format_time_to_hh_mm=MagicMock(side_effect=ValueError("bad")))
        hass, _ = _service_hass(api)
        with pytest.raises(ServiceValidationError):
            await services_mod._async_set_device_preferences(
                _call(hass, target_time="soon")
            )

    async def test_api_failure_raises_home_assistant_error(self):
        api = _api(set_device_preferences=AsyncMock(return_value=False))
        hass, _ = _service_hass(api)
        with pytest.raises(HomeAssistantError) as err:
            await services_mod._async_set_device_preferences(_call(hass))
        assert err.value.translation_key == "set_preferences_failed"
        assert not isinstance(err.value, ServiceValidationError)

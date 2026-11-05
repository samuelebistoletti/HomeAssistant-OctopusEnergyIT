"""Tests for the Octopus Energy Italy config flow (user, reauth, reconfigure)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.octopus_energy_it import config_flow
from custom_components.octopus_energy_it.config_flow import OctopusEnergyITConfigFlow
from custom_components.octopus_energy_it.octopus_energy_it import (
    OctopusEnergyITAuthError,
    OctopusEnergyITConnectionError,
)
from tests.conftest import AbortFlow

ACCOUNT = {"number": "A-1234ABCD"}


def _entry(unique_id="user@example.com", email="user@example.com"):
    return SimpleNamespace(
        entry_id="entry-1",
        unique_id=unique_id,
        data={"email": email, "password": "old", "account_numbers": ["A-1234ABCD"]},
    )


def _flow(entries=(), context=None):
    flow = OctopusEnergyITConfigFlow()
    entries = list(entries)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda _domain: entries,
            async_get_entry=lambda entry_id: next(
                (e for e in entries if e.entry_id == entry_id), None
            ),
        )
    )
    flow.context = context or {}
    return flow


def _api(*, auth_exc=None, accounts=None):
    api = MagicMock()
    api.authenticate = AsyncMock(side_effect=auth_exc)
    api.fetch_accounts_with_initial_data = AsyncMock(
        return_value=[ACCOUNT] if accounts is None else accounts
    )
    return api


@pytest.fixture
def patch_api():
    def _patch(api):
        return patch.object(config_flow, "OctopusEnergyIT", return_value=api)

    return _patch


class TestUserStep:
    async def test_shows_form_without_input(self):
        result = await _flow().async_step_user()
        assert result == {
            "type": "form",
            "step_id": "user",
            "errors": {},
            "description_placeholders": None,
        }

    async def test_creates_entry_with_lowercase_unique_id(self, patch_api):
        flow = _flow()
        with patch_api(_api()):
            result = await flow.async_step_user(
                {"email": " User@Example.com ", "password": "pw"}
            )

        assert result["type"] == "create_entry"
        assert result["data"]["email"] == "User@Example.com"
        assert result["data"]["account_data"] == ACCOUNT
        assert flow.unique_id == "user@example.com"

    async def test_aborts_when_login_already_configured(self, patch_api):
        flow = _flow(entries=[_entry()])
        with patch_api(_api()), pytest.raises(AbortFlow, match="already_configured"):
            await flow.async_step_user({"email": "USER@example.com", "password": "pw"})

    @pytest.mark.parametrize(
        ("api", "error"),
        [
            (_api(auth_exc=OctopusEnergyITAuthError()), "invalid_auth"),
            (_api(auth_exc=OctopusEnergyITConnectionError()), "cannot_connect"),
            (_api(auth_exc=RuntimeError("boom")), "unknown"),
            (_api(accounts=[]), "no_accounts"),
        ],
    )
    async def test_errors_are_mapped(self, patch_api, api, error):
        with patch_api(api):
            result = await _flow().async_step_user(
                {"email": "user@example.com", "password": "pw"}
            )

        assert result["type"] == "form"
        assert result["errors"] == {"base": error}


class TestReauth:
    async def test_reauth_shows_password_form_for_the_entry_email(self):
        flow = _flow(entries=[_entry()], context={"entry_id": "entry-1"})
        result = await flow.async_step_reauth({})

        assert result["step_id"] == "reauth_confirm"
        assert result["description_placeholders"] == {"email": "user@example.com"}

    async def test_reauth_updates_password_and_reloads(self, patch_api):
        flow = _flow(entries=[_entry()], context={"entry_id": "entry-1"})
        with patch_api(_api()):
            result = await flow.async_step_reauth_confirm({"password": "new"})

        assert result == {"type": "abort", "reason": "reauth_successful"}
        assert flow.updated["data"]["password"] == "new"
        assert flow.updated["data"]["account_numbers"] == ["A-1234ABCD"]

    async def test_reauth_wrong_password_keeps_form(self, patch_api):
        flow = _flow(entries=[_entry()], context={"entry_id": "entry-1"})
        with patch_api(_api(auth_exc=OctopusEnergyITAuthError())):
            result = await flow.async_step_reauth_confirm({"password": "bad"})

        assert result["errors"] == {"base": "invalid_auth"}
        assert flow.updated is None


class TestReconfigure:
    async def test_reconfigure_updates_credentials(self, patch_api):
        flow = _flow(entries=[_entry()], context={"entry_id": "entry-1"})
        with patch_api(_api()):
            result = await flow.async_step_reconfigure(
                {"email": "user@example.com", "password": "new"}
            )

        assert result["reason"] == "reconfigure_successful"
        assert flow.updated["data"]["password"] == "new"

    async def test_reconfigure_rejects_a_different_account(self, patch_api):
        flow = _flow(entries=[_entry()], context={"entry_id": "entry-1"})
        with patch_api(_api()), pytest.raises(AbortFlow, match="wrong_account"):
            await flow.async_step_reconfigure(
                {"email": "other@example.com", "password": "pw"}
            )

    async def test_legacy_entry_without_unique_id_may_switch_login(self, patch_api):
        flow = _flow(entries=[_entry(unique_id=None)], context={"entry_id": "entry-1"})
        with patch_api(_api()):
            result = await flow.async_step_reconfigure(
                {"email": "other@example.com", "password": "pw"}
            )

        assert result["reason"] == "reconfigure_successful"
        assert flow.updated["data"]["email"] == "other@example.com"

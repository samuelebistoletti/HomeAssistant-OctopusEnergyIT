"""
Tests for the OctopusEnergyIT API client (octopus_energy_it.py).

All HomeAssistant dependencies are mocked so these tests can run without
a Home Assistant installation.
"""

import sys
import types
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out homeassistant before importing the module under test
# ---------------------------------------------------------------------------

# homeassistant.exceptions stub
_ha_exceptions = types.ModuleType("homeassistant.exceptions")


class ConfigEntryNotReady(Exception):
    pass


_ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady

_ha = types.ModuleType("homeassistant")
sys.modules.setdefault("homeassistant", _ha)
sys.modules.setdefault("homeassistant.exceptions", _ha_exceptions)

# python_graphql_client stub (replaced per-test via patch)
_graphql_mod = types.ModuleType("python_graphql_client")


class _StubGraphqlClient:
    def __init__(self, endpoint, headers=None):
        pass

    async def execute_async(self, query, variables=None):
        return {}


_graphql_mod.GraphqlClient = _StubGraphqlClient
sys.modules.setdefault("python_graphql_client", _graphql_mod)

# Import the module under test using importlib to handle the relative imports
import importlib
import importlib.util
import os

_MODULE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "custom_components",
    "octopus_energy_it",
    "octopus_energy_it.py",
)

_spec = importlib.util.spec_from_file_location(
    "custom_components.octopus_energy_it.octopus_energy_it",
    _MODULE_PATH,
)
_mod = importlib.util.module_from_spec(_spec)
# Patch the relative imports that the module will resolve at load time
_mod.__package__ = "custom_components.octopus_energy_it"
_spec.loader.exec_module(_mod)

OctopusEnergyIT = _mod.OctopusEnergyIT
TokenManager = _mod.TokenManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT_NUMBER = "A-TEST1234"
DEVICE_ID = "krakenflex-device-test-001"

# A minimal valid-looking JWT whose payload has an "exp" field set in the far
# future.  We use PyJWT to produce a real token rather than crafting raw bytes
# so that TokenManager.set_token() can decode it correctly.
try:
    import jwt as _pyjwt

    _FUTURE_EXP = int(datetime(2099, 1, 1, tzinfo=UTC).timestamp())
    _VALID_TOKEN = _pyjwt.encode(
        {"sub": "test", "exp": _FUTURE_EXP}, "secret", algorithm="HS256"
    )
    # pyjwt >=2 returns str; <2 returns bytes
    if isinstance(_VALID_TOKEN, bytes):
        _VALID_TOKEN = _VALID_TOKEN.decode()
except Exception:
    # Fallback: a token that will fail JWT decode — set_token will use the
    # auto-refresh interval instead.
    _VALID_TOKEN = "fallback.token.value"
    _FUTURE_EXP = None


def _make_api() -> OctopusEnergyIT:
    """Return a fresh API client instance."""
    return OctopusEnergyIT(email="test@example.com", password="s3cr3t")


def _success_login_response(token=_VALID_TOKEN, exp=_FUTURE_EXP):
    """Build a successful obtainKrakenToken GraphQL response."""
    payload = {"exp": exp} if exp is not None else {}
    return {
        "data": {
            "obtainKrakenToken": {
                "token": token,
                "payload": payload,
            }
        }
    }


def _error_response(error_code: str, message: str = "Error"):
    """Build a GraphQL error response with an extension errorCode."""
    return {
        "errors": [
            {
                "message": message,
                "extensions": {"errorCode": error_code},
            }
        ]
    }


# ---------------------------------------------------------------------------
# TokenManager unit tests
# ---------------------------------------------------------------------------


class TestTokenManager:
    def test_new_manager_has_no_token(self):
        tm = TokenManager()
        assert tm.token is None
        assert tm.expiry is None
        assert not tm.is_valid

    def test_set_token_stores_token(self):
        tm = TokenManager()
        tm.set_token("abc", expiry=_FUTURE_EXP)
        assert tm.token == "abc"

    def test_token_with_future_expiry_is_valid(self):
        tm = TokenManager()
        tm.set_token(_VALID_TOKEN, expiry=_FUTURE_EXP)
        assert tm.is_valid

    def test_token_with_past_expiry_is_invalid(self):
        tm = TokenManager()
        past = datetime(2000, 1, 1, tzinfo=UTC).timestamp()
        tm.set_token("oldtoken", expiry=past)
        assert not tm.is_valid

    def test_token_near_expiry_is_invalid(self):
        """A token expiring within TOKEN_REFRESH_MARGIN seconds is invalid."""
        tm = TokenManager()
        # 100 seconds in the future — inside the 300 s margin
        near_exp = datetime.now(UTC).timestamp() + 100
        tm.set_token("neartoken", expiry=near_exp)
        assert not tm.is_valid

    def test_clear_removes_token(self):
        tm = TokenManager()
        tm.set_token("abc", expiry=_FUTURE_EXP)
        tm.clear()
        assert tm.token is None
        assert tm.expiry is None
        assert not tm.is_valid

    def test_set_token_decodes_jwt_expiry(self):
        """set_token without an explicit expiry falls back to JWT decode."""
        tm = TokenManager()
        tm.set_token(_VALID_TOKEN)
        # If pyjwt decoded successfully we should have a future expiry
        if _FUTURE_EXP is not None:
            assert tm.expiry == float(_FUTURE_EXP)
            assert tm.is_valid

    def test_set_token_undecipherable_jwt_uses_auto_interval(self):
        """An opaque token that cannot be decoded gets a fallback expiry."""
        tm = TokenManager()
        before = datetime.now(UTC).timestamp()
        with patch(f"{_mod.__name__}.jwt.decode", side_effect=Exception("bad token")):
            tm.set_token("not.a.jwt")
        after = datetime.now(UTC).timestamp()
        # Expiry should be roughly TOKEN_AUTO_REFRESH_INTERVAL seconds away
        assert tm.expiry is not None
        assert before + 2900 <= tm.expiry <= after + 3100


# ---------------------------------------------------------------------------
# login() tests
# ---------------------------------------------------------------------------


class TestLogin:
    async def test_login_success_stores_token(self):
        api = _make_api()
        with patch.object(
            api,
            "_execute_graphql",
            new=AsyncMock(return_value=_success_login_response()),
        ):
            result = await api.login()

        assert result is True
        assert api._token_manager.token == _VALID_TOKEN

    async def test_login_success_with_payload_exp_sets_expiry(self):
        api = _make_api()
        with patch.object(
            api,
            "_execute_graphql",
            new=AsyncMock(return_value=_success_login_response()),
        ):
            await api.login()

        if _FUTURE_EXP is not None:
            assert api._token_manager.expiry == float(_FUTURE_EXP)

    async def test_login_invalid_credentials_returns_false_immediately(self):
        """KT-CT-1138 must abort without retrying."""
        api = _make_api()
        responses = [_error_response("KT-CT-1138", "Invalid credentials")]
        call_count = 0

        async def _mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return responses[0]

        with patch.object(api, "_execute_graphql", new=_mock_execute):
            result = await api.login()

        assert result is False
        assert call_count == 1  # Must not retry

    async def test_login_rate_limit_retries_with_backoff(self):
        """KT-CT-1199 should trigger retries until attempts are exhausted."""
        api = _make_api()
        call_count = 0

        async def _mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _error_response("KT-CT-1199", "Too many requests")

        with (
            patch.object(api, "_execute_graphql", new=_mock_execute),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await api.login()

        assert result is False
        # 5 retries configured in the real implementation
        assert call_count == 5

    async def test_login_rate_limit_succeeds_on_later_attempt(self):
        """After rate limit errors the client should succeed when a good response arrives."""
        api = _make_api()
        attempts = [
            _error_response("KT-CT-1199", "Too many requests"),
            _error_response("KT-CT-1199", "Too many requests"),
            _success_login_response(),
        ]
        call_count = 0

        async def _mock_execute(*args, **kwargs):
            nonlocal call_count
            resp = attempts[min(call_count, len(attempts) - 1)]
            call_count += 1
            return resp

        with (
            patch.object(api, "_execute_graphql", new=_mock_execute),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await api.login()

        assert result is True
        assert call_count == 3

    async def test_login_network_error_returns_false(self):
        """A raised exception during the GraphQL call should result in False."""
        api = _make_api()

        async def _mock_execute(*args, **kwargs):
            raise ConnectionError("Network failure")

        with (
            patch.object(api, "_execute_graphql", new=_mock_execute),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await api.login()

        assert result is False

    async def test_login_skips_when_token_already_valid(self):
        """If the token is still valid, login() should return True without a request."""
        api = _make_api()
        api._token_manager.set_token(_VALID_TOKEN, expiry=_FUTURE_EXP)

        execute_mock = AsyncMock(return_value=_success_login_response())
        with patch.object(api, "_execute_graphql", new=execute_mock):
            result = await api.login()

        assert result is True
        execute_mock.assert_not_called()

    async def test_login_non_dict_response_retries(self):
        """A non-dict response (e.g. None) should trigger retry logic."""
        api = _make_api()
        call_count = 0

        async def _mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return None  # non-dict triggers continue path

        with (
            patch.object(api, "_execute_graphql", new=_mock_execute),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await api.login()

        assert result is False
        assert call_count == 5


# ---------------------------------------------------------------------------
# _execute_graphql() / token-refresh tests
# ---------------------------------------------------------------------------


class TestExecuteGraphql:
    async def test_fresh_token_makes_request_without_refresh(self):
        api = _make_api()
        api._token_manager.set_token(_VALID_TOKEN, expiry=_FUTURE_EXP)

        mock_client = MagicMock()
        mock_client.execute_async = AsyncMock(
            return_value={"data": {"hello": "world"}}
        )

        with patch.object(api, "_get_graphql_client", return_value=mock_client):
            result = await api._execute_graphql("query { hello }")

        assert result == {"data": {"hello": "world"}}
        mock_client.execute_async.assert_called_once()

    async def test_expired_token_triggers_ensure_token_before_request(self):
        """When the token is invalid, ensure_token (login) is called first."""
        api = _make_api()
        # Do NOT set a token — token manager reports invalid

        mock_client = MagicMock()
        mock_client.execute_async = AsyncMock(
            return_value={"data": {"hello": "world"}}
        )

        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_get_graphql_client", return_value=mock_client),
        ):
            result = await api._execute_graphql("query { hello }")

        assert result is not None

    async def test_ensure_token_failure_returns_none(self):
        """If ensure_token fails, _execute_graphql returns None without a request."""
        api = _make_api()

        mock_client = MagicMock()
        mock_client.execute_async = AsyncMock(return_value={"data": {}})

        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=False)),
            patch.object(api, "_get_graphql_client", return_value=mock_client),
        ):
            result = await api._execute_graphql("query { hello }")

        assert result is None
        mock_client.execute_async.assert_not_called()

    async def test_kt_ct_1124_refreshes_token_and_retries(self):
        """KT-CT-1124 (expired JWT) should trigger a token refresh and retry."""
        api = _make_api()
        api._token_manager.set_token(_VALID_TOKEN, expiry=_FUTURE_EXP)

        call_count = 0

        async def _mock_execute_async(query, variables=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _error_response("KT-CT-1124", "JWT has expired")
            return {"data": {"result": "ok"}}

        mock_client = MagicMock()
        mock_client.execute_async = _mock_execute_async

        with (
            patch.object(api, "_get_graphql_client", return_value=mock_client),
            patch.object(api, "login", new=AsyncMock(return_value=True)),
        ):
            result = await api._execute_graphql("query { hello }", retry_on_token_error=True)

        # The second call should return the good response
        assert result == {"data": {"result": "ok"}}

    async def test_kt_ct_1124_on_retry_raises_none(self):
        """If the retry after KT-CT-1124 also fails login, return None."""
        api = _make_api()
        api._token_manager.set_token(_VALID_TOKEN, expiry=_FUTURE_EXP)

        mock_client = MagicMock()
        mock_client.execute_async = AsyncMock(
            return_value=_error_response("KT-CT-1124", "JWT has expired")
        )

        with (
            patch.object(api, "_get_graphql_client", return_value=mock_client),
            patch.object(api, "login", new=AsyncMock(return_value=False)),
        ):
            result = await api._execute_graphql("query { hello }", retry_on_token_error=True)

        assert result is None

    async def test_network_exception_returns_none(self):
        """A raised exception inside execute_async should return None."""
        api = _make_api()
        api._token_manager.set_token(_VALID_TOKEN, expiry=_FUTURE_EXP)

        mock_client = MagicMock()
        mock_client.execute_async = AsyncMock(side_effect=OSError("connection refused"))

        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_get_graphql_client", return_value=mock_client),
        ):
            result = await api._execute_graphql("query { hello }")

        assert result is None

    async def test_require_auth_false_skips_ensure_token(self):
        """When require_auth=False the client skips the token check."""
        api = _make_api()

        mock_client = MagicMock()
        mock_client.execute_async = AsyncMock(return_value={"data": {}})
        ensure_token_mock = AsyncMock(return_value=True)

        with (
            patch.object(api, "ensure_token", new=ensure_token_mock),
            patch.object(api, "_get_graphql_client", return_value=mock_client),
        ):
            await api._execute_graphql("query { hello }", require_auth=False)

        ensure_token_mock.assert_not_called()


# ---------------------------------------------------------------------------
# update_boost_charge() tests
# ---------------------------------------------------------------------------


class TestUpdateBoostCharge:
    async def test_boost_action_returns_device_id(self):
        api = _make_api()
        response = {
            "data": {"updateBoostCharge": {"id": DEVICE_ID}}
        }
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)):
            result = await api.update_boost_charge(DEVICE_ID, "BOOST")

        assert result == DEVICE_ID

    async def test_cancel_action_returns_device_id(self):
        api = _make_api()
        response = {
            "data": {"updateBoostCharge": {"id": DEVICE_ID}}
        }
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)):
            result = await api.update_boost_charge(DEVICE_ID, "CANCEL")

        assert result == DEVICE_ID

    async def test_graphql_error_returns_none(self):
        api = _make_api()
        response = _error_response("KT-BOOST-001", "Device not found")
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)):
            result = await api.update_boost_charge(DEVICE_ID, "BOOST")

        assert result is None

    async def test_non_dict_response_returns_none(self):
        api = _make_api()
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)):
            result = await api.update_boost_charge(DEVICE_ID, "BOOST")

        assert result is None

    async def test_missing_data_key_returns_none(self):
        """If updateBoostCharge key is absent, return None."""
        api = _make_api()
        response = {"data": {}}
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)):
            result = await api.update_boost_charge(DEVICE_ID, "BOOST")

        assert result is None

    async def test_passes_correct_variables(self):
        """Verify that the correct variables dict is forwarded to _execute_graphql."""
        api = _make_api()
        execute_mock = AsyncMock(
            return_value={"data": {"updateBoostCharge": {"id": DEVICE_ID}}}
        )
        with patch.object(api, "_execute_graphql", new=execute_mock):
            await api.update_boost_charge(DEVICE_ID, "BOOST")

        _, kwargs = execute_mock.call_args
        variables = execute_mock.call_args[0][1] if execute_mock.call_args[0][1:] else kwargs.get("variables")
        assert variables == {"input": {"deviceId": DEVICE_ID, "action": "BOOST"}}


# ---------------------------------------------------------------------------
# set_device_preferences() tests
# ---------------------------------------------------------------------------


class TestSetDevicePreferences:
    async def test_valid_inputs_returns_true(self):
        api = _make_api()
        response = {"data": {"setDevicePreferences": {"id": DEVICE_ID}}}
        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)),
        ):
            result = await api.set_device_preferences(DEVICE_ID, 80, "07:00")

        assert result is True

    async def test_percentage_clamps_below_10(self):
        """Values below 10 are clamped to 10 — does not raise, still returns True."""
        api = _make_api()
        response = {"data": {"setDevicePreferences": {"id": DEVICE_ID}}}
        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)),
        ):
            result = await api.set_device_preferences(DEVICE_ID, 5, "07:00")

        assert result is True

    async def test_percentage_clamps_above_100(self):
        """Values above 100 are clamped to 100 — does not raise, still returns True."""
        api = _make_api()
        response = {"data": {"setDevicePreferences": {"id": DEVICE_ID}}}
        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)),
        ):
            result = await api.set_device_preferences(DEVICE_ID, 150, "07:00")

        assert result is True

    async def test_invalid_time_outside_range_returns_false(self):
        """A time outside 04:00-17:00 should return False."""
        api = _make_api()
        with patch.object(api, "ensure_token", new=AsyncMock(return_value=True)):
            result = await api.set_device_preferences(DEVICE_ID, 80, "22:00")

        assert result is False

    async def test_unparseable_time_returns_false(self):
        """A completely invalid time string should return False."""
        api = _make_api()
        with patch.object(api, "ensure_token", new=AsyncMock(return_value=True)):
            result = await api.set_device_preferences(DEVICE_ID, 80, "not-a-time")

        assert result is False

    async def test_graphql_error_returns_false(self):
        api = _make_api()
        response = _error_response("KT-PREF-001", "Preference update failed")
        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=response)),
        ):
            result = await api.set_device_preferences(DEVICE_ID, 80, "07:00")

        assert result is False

    async def test_non_dict_response_returns_false(self):
        api = _make_api()
        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)),
        ):
            result = await api.set_device_preferences(DEVICE_ID, 80, "07:00")

        assert result is False

    async def test_ensure_token_failure_returns_false(self):
        api = _make_api()
        with patch.object(api, "ensure_token", new=AsyncMock(return_value=False)):
            result = await api.set_device_preferences(DEVICE_ID, 80, "07:00")

        assert result is False

    async def test_schedules_cover_all_seven_days(self):
        """The mutation variables should include a schedule for every day of the week."""
        api = _make_api()
        execute_mock = AsyncMock(
            return_value={"data": {"setDevicePreferences": {"id": DEVICE_ID}}}
        )
        with (
            patch.object(api, "ensure_token", new=AsyncMock(return_value=True)),
            patch.object(api, "_execute_graphql", new=execute_mock),
        ):
            await api.set_device_preferences(DEVICE_ID, 80, "07:00")

        # _execute_graphql is called as (query, variables=...) — variables may be
        # a positional or keyword argument depending on the call site.
        args, kwargs = execute_mock.call_args
        call_variables = args[1] if len(args) > 1 else kwargs.get("variables", {})
        schedules = call_variables["input"]["schedules"]
        days = {s["dayOfWeek"] for s in schedules}
        assert days == {
            "MONDAY",
            "TUESDAY",
            "WEDNESDAY",
            "THURSDAY",
            "FRIDAY",
            "SATURDAY",
            "SUNDAY",
        }


# ---------------------------------------------------------------------------
# fetch_all_data() tests
# ---------------------------------------------------------------------------


class TestFetchAllData:
    def _minimal_graphql_response(self, devices=None, dispatches=None):
        """Build a realistic COMPREHENSIVE_QUERY response."""
        return {
            "data": {
                "account": {
                    "id": "acc-001",
                    "ledgers": [
                        {"balance": 1000, "ledgerType": "ELECTRICITY_LEDGER"}
                    ],
                    "properties": [],
                },
                "devices": devices if devices is not None else [],
                "completedDispatches": dispatches if dispatches is not None else [],
            }
        }

    async def test_returns_structured_dict_with_required_keys(self):
        api = _make_api()
        raw = self._minimal_graphql_response()

        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)),
            patch.object(
                api, "fetch_flex_planned_dispatches", new=AsyncMock(return_value=[])
            ),
        ):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert isinstance(result, dict)
        for key in ("account", "products", "devices", "plannedDispatches", "completedDispatches"):
            assert key in result, f"Missing key: {key}"

    async def test_devices_populated_from_response(self):
        api = _make_api()
        device = {
            "id": DEVICE_ID,
            "name": "Test EV",
            "deviceType": "ELECTRIC_VEHICLES",
        }
        raw = self._minimal_graphql_response(devices=[device])

        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)),
            patch.object(
                api, "fetch_flex_planned_dispatches", new=AsyncMock(return_value=[])
            ),
        ):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert len(result["devices"]) == 1
        assert result["devices"][0]["id"] == DEVICE_ID

    async def test_planned_dispatches_fetched_per_device(self):
        """For each device, fetch_flex_planned_dispatches must be called once."""
        api = _make_api()
        device = {"id": DEVICE_ID, "name": "Test EV", "deviceType": "ELECTRIC_VEHICLES"}
        raw = self._minimal_graphql_response(devices=[device])

        flex_mock = AsyncMock(
            return_value=[
                {"start": "2024-01-16T05:00:00Z", "end": "2024-01-16T07:00:00Z", "energyAddedKwh": 10.0, "type": "SMART"}
            ]
        )

        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)),
            patch.object(api, "fetch_flex_planned_dispatches", new=flex_mock),
        ):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        flex_mock.assert_called_once_with(DEVICE_ID)
        assert len(result["plannedDispatches"]) == 1

    async def test_returns_none_on_network_error(self):
        api = _make_api()

        with patch.object(
            api,
            "_execute_graphql",
            new=AsyncMock(side_effect=OSError("network error")),
        ):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert result is None

    async def test_returns_none_when_graphql_returns_none(self):
        api = _make_api()

        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert result is None

    async def test_handles_response_without_devices_key(self):
        """Missing 'devices' in the GraphQL data should produce an empty list."""
        api = _make_api()
        raw = {
            "data": {
                "account": {
                    "id": "acc-001",
                    "ledgers": [],
                    "properties": [],
                },
                # no 'devices' key
                "completedDispatches": [],
            }
        }

        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert result is not None
        assert result["devices"] == []

    async def test_handles_critical_graphql_errors_returns_none(self):
        """A response with only top-level errors and no data should return None."""
        api = _make_api()
        raw = {
            "errors": [
                {
                    "message": "Unauthorized",
                    "extensions": {"errorCode": "KT-CT-9999"},
                }
            ]
        }

        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert result is None

    async def test_non_critical_device_errors_do_not_block_account_data(self):
        """KT-CT-4301 errors on devices/dispatches paths should not nullify the result."""
        api = _make_api()
        raw = {
            "data": {
                "account": {
                    "id": "acc-001",
                    "ledgers": [],
                    "properties": [],
                },
                "devices": [],
                "completedDispatches": [],
            },
            "errors": [
                {
                    "message": "No device found",
                    "path": ["devices"],
                    "extensions": {"errorCode": "KT-CT-4301"},
                }
            ],
        }

        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert result is not None
        assert result["account"]["id"] == "acc-001"

    async def test_flex_dispatch_exception_does_not_abort_fetch(self):
        """If fetch_flex_planned_dispatches raises, fetch_all_data should still return data."""
        api = _make_api()
        device = {"id": DEVICE_ID, "name": "Test EV", "deviceType": "ELECTRIC_VEHICLES"}
        raw = self._minimal_graphql_response(devices=[device])

        with (
            patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)),
            patch.object(
                api,
                "fetch_flex_planned_dispatches",
                new=AsyncMock(side_effect=RuntimeError("dispatch API error")),
            ),
        ):
            result = await api.fetch_all_data(ACCOUNT_NUMBER)

        assert result is not None
        assert result["plannedDispatches"] == []


# ---------------------------------------------------------------------------
# format_time_to_hh_mm() static method tests
# ---------------------------------------------------------------------------


class TestFormatTimeToHhMm:
    def test_hh_mm_string_unchanged(self):
        assert OctopusEnergyIT.format_time_to_hh_mm("07:30") == "07:30"

    def test_hh_mm_ss_truncates_seconds(self):
        assert OctopusEnergyIT.format_time_to_hh_mm("07:30:45") == "07:30"

    def test_integer_hour_as_string(self):
        assert OctopusEnergyIT.format_time_to_hh_mm("5") == "05:00"

    def test_integer_hour_as_number(self):
        assert OctopusEnergyIT.format_time_to_hh_mm(5) == "05:00"

    def test_numeric_hour_out_of_range_raises(self):
        with pytest.raises(ValueError):
            OctopusEnergyIT.format_time_to_hh_mm(25)

    def test_negative_hour_raises(self):
        with pytest.raises(ValueError):
            OctopusEnergyIT.format_time_to_hh_mm(-1)

    def test_unparseable_string_raises(self):
        with pytest.raises(ValueError):
            OctopusEnergyIT.format_time_to_hh_mm("not-a-time")

    def test_12h_am_format(self):
        result = OctopusEnergyIT.format_time_to_hh_mm("07:00 AM")
        assert result == "07:00"

    def test_12h_pm_format(self):
        result = OctopusEnergyIT.format_time_to_hh_mm("01:00 PM")
        assert result == "13:00"


# ---------------------------------------------------------------------------
# to_float_or_none() static method tests
# ---------------------------------------------------------------------------


class TestToFloatOrNone:
    def test_none_returns_none(self):
        assert OctopusEnergyIT.to_float_or_none(None) is None

    def test_int_converted_to_float(self):
        assert OctopusEnergyIT.to_float_or_none(5) == 5.0

    def test_float_returned_as_float(self):
        assert OctopusEnergyIT.to_float_or_none(3.14) == 3.14

    def test_numeric_string_converted(self):
        assert OctopusEnergyIT.to_float_or_none("0.25") == 0.25

    def test_non_numeric_string_returns_none(self):
        assert OctopusEnergyIT.to_float_or_none("abc") is None


# ---------------------------------------------------------------------------
# format_cents_from_eur() static method tests
# ---------------------------------------------------------------------------


class TestFormatCentsFromEur:
    def test_none_returns_zero_string(self):
        assert OctopusEnergyIT.format_cents_from_eur(None) == "0"

    def test_zero_returns_zero_string(self):
        assert OctopusEnergyIT.format_cents_from_eur(0) == "0"

    def test_converts_eur_to_cents(self):
        assert OctopusEnergyIT.format_cents_from_eur(0.25) == "25"

    def test_strips_trailing_zeros(self):
        # 0.1 EUR/kWh = 10 cents — should not have trailing zeros
        result = OctopusEnergyIT.format_cents_from_eur(0.1)
        assert result == "10"

    def test_non_numeric_returns_zero_string(self):
        assert OctopusEnergyIT.format_cents_from_eur("bad") == "0"


# ---------------------------------------------------------------------------
# flatten_connection() static method tests
# ---------------------------------------------------------------------------


class TestFlattenConnection:
    def test_relay_connection_extracted(self):
        conn = {
            "edges": [
                {"node": {"id": "1"}},
                {"node": {"id": "2"}},
            ]
        }
        result = OctopusEnergyIT.flatten_connection(conn)
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_plain_list_returned_unchanged(self):
        lst = [{"id": "1"}, {"id": "2"}]
        assert OctopusEnergyIT.flatten_connection(lst) == lst

    def test_empty_edges_returns_empty_list(self):
        assert OctopusEnergyIT.flatten_connection({"edges": []}) == []

    def test_edges_with_none_node_filtered_out(self):
        conn = {
            "edges": [
                {"node": {"id": "1"}},
                {"node": None},
                None,
            ]
        }
        result = OctopusEnergyIT.flatten_connection(conn)
        assert result == [{"id": "1"}]

    def test_non_dict_non_list_returns_empty_list(self):
        assert OctopusEnergyIT.flatten_connection(None) == []
        assert OctopusEnergyIT.flatten_connection("string") == []


# ---------------------------------------------------------------------------
# fetch_accounts_with_initial_data() tests
# ---------------------------------------------------------------------------


class TestFetchAccountsWithInitialData:
    async def test_returns_accounts_list(self):
        api = _make_api()
        raw = {
            "data": {
                "viewer": {
                    "accounts": [
                        {"number": ACCOUNT_NUMBER, "ledgers": []},
                    ]
                }
            }
        }
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_accounts_with_initial_data()

        assert result == [{"number": ACCOUNT_NUMBER, "ledgers": []}]

    async def test_empty_accounts_returns_none(self):
        api = _make_api()
        raw = {"data": {"viewer": {"accounts": []}}}
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_accounts_with_initial_data()

        assert result is None

    async def test_graphql_errors_returns_none(self):
        api = _make_api()
        raw = _error_response("KT-AUTH-001", "Not authorized")
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_accounts_with_initial_data()

        assert result is None

    async def test_non_dict_response_returns_none(self):
        api = _make_api()
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)):
            result = await api.fetch_accounts_with_initial_data()

        assert result is None


# ---------------------------------------------------------------------------
# change_device_suspension() tests
# ---------------------------------------------------------------------------


class TestChangeDeviceSuspension:
    async def test_returns_device_id_on_success(self):
        api = _make_api()
        raw = {"data": {"updateDeviceSmartControl": {"id": DEVICE_ID}}}
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.change_device_suspension(DEVICE_ID, "SUSPEND")

        assert result == DEVICE_ID

    async def test_graphql_error_returns_none(self):
        api = _make_api()
        raw = _error_response("KT-SUSPEND-001", "Cannot suspend")
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.change_device_suspension(DEVICE_ID, "SUSPEND")

        assert result is None

    async def test_non_dict_response_returns_none(self):
        api = _make_api()
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)):
            result = await api.change_device_suspension(DEVICE_ID, "RESUME")

        assert result is None


# ---------------------------------------------------------------------------
# fetch_flex_planned_dispatches() tests
# ---------------------------------------------------------------------------


class TestFetchFlexPlannedDispatches:
    async def test_returns_dispatches_list(self):
        api = _make_api()
        raw = {
            "data": {
                "flexPlannedDispatches": [
                    {
                        "start": "2024-01-16T05:00:00Z",
                        "end": "2024-01-16T07:00:00Z",
                        "energyAddedKwh": 10.0,
                        "type": "SMART",
                    }
                ]
            }
        }
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_flex_planned_dispatches(DEVICE_ID)

        assert len(result) == 1
        assert result[0]["energyAddedKwh"] == 10.0

    async def test_empty_dispatches_returns_empty_list(self):
        api = _make_api()
        raw = {"data": {"flexPlannedDispatches": []}}
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_flex_planned_dispatches(DEVICE_ID)

        assert result == []

    async def test_graphql_error_returns_none(self):
        api = _make_api()
        raw = _error_response("KT-DISP-001", "No device found")
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=raw)):
            result = await api.fetch_flex_planned_dispatches(DEVICE_ID)

        assert result is None

    async def test_non_dict_response_returns_none(self):
        api = _make_api()
        with patch.object(api, "_execute_graphql", new=AsyncMock(return_value=None)):
            result = await api.fetch_flex_planned_dispatches(DEVICE_ID)

        assert result is None

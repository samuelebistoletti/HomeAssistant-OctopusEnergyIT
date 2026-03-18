"""Shared fixtures and module stubs for OctopusEnergyIT tests.

The stub block at the top of this file runs before any test module is collected,
ensuring that homeassistant and all third-party dependencies resolve without a
real HA installation.
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure the project root is on sys.path so that
# `custom_components.octopus_energy_it.*` can be imported as real packages.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Module stubs — injected before any integration code is imported
# ---------------------------------------------------------------------------

def _stub(dotted_name: str) -> types.ModuleType:
    """Return (and register) a minimal stub module (idempotent)."""
    if dotted_name not in sys.modules:
        mod = types.ModuleType(dotted_name)
        # Wire up attribute on parent so `from parent import child` works.
        parts = dotted_name.rsplit(".", 1)
        if len(parts) == 2:
            parent = sys.modules.get(parts[0])
            if parent is not None:
                setattr(parent, parts[1], mod)
        sys.modules[dotted_name] = mod
    return sys.modules[dotted_name]


def _install_stubs() -> None:
    """Install all required stubs (safe to call multiple times)."""

    # ---- custom_components package (must be a proper package with __path__) ----
    # This ensures test_api_client.py's setdefault() doesn't override it with a
    # plain module, which would prevent submodule imports in other test files.
    _cc_path = os.path.join(_REPO_ROOT, "custom_components")
    _oeit_path = os.path.join(_cc_path, "octopus_energy_it")

    if "custom_components" not in sys.modules:
        _cc = types.ModuleType("custom_components")
        _cc.__path__ = [_cc_path]
        _cc.__package__ = "custom_components"
        sys.modules["custom_components"] = _cc

    if "custom_components.octopus_energy_it" not in sys.modules:
        _oeit = types.ModuleType("custom_components.octopus_energy_it")
        _oeit.__path__ = [_oeit_path]
        _oeit.__package__ = "custom_components.octopus_energy_it"
        sys.modules["custom_components.octopus_energy_it"] = _oeit
        setattr(sys.modules["custom_components"], "octopus_energy_it", _oeit)

    # ---- third-party ----
    _aiohttp = _stub("aiohttp")
    if not hasattr(_aiohttp, "ClientSession"):
        _aiohttp.ClientSession = object
        _aiohttp.ClientError = Exception

        class _ClientResponseError(Exception):
            def __init__(self, request_info=None, history=(), status=None, **kw):
                self.status = status
                super().__init__(f"HTTP {status}")

        _aiohttp.ClientResponseError = _ClientResponseError
        _aiohttp.ClientConnectionError = Exception

        class _ClientTimeout:
            def __init__(self, *, total=None, connect=None, sock_read=None, sock_connect=None):
                self.total = total

        _aiohttp.ClientTimeout = _ClientTimeout

    _jwt = _stub("jwt")
    if not hasattr(_jwt, "decode"):
        _jwt.decode = MagicMock(return_value={})
        _jwt.PyJWTError = Exception

    _gql = _stub("python_graphql_client")
    if not hasattr(_gql, "GraphqlClient"):
        _gql.GraphqlClient = object

    # ---- homeassistant hierarchy ----
    _stub("homeassistant")
    _stub("homeassistant.components")
    _stub("homeassistant.helpers")
    _stub("homeassistant.util")

    _const = _stub("homeassistant.const")
    if not hasattr(_const, "Platform"):
        _const.Platform = types.SimpleNamespace(
            BINARY_SENSOR="binary_sensor",
            SENSOR="sensor",
            SWITCH="switch",
            NUMBER="number",
            SELECT="select",
        )

    _core = _stub("homeassistant.core")
    if not hasattr(_core, "HomeAssistant"):
        _core.HomeAssistant = type("HomeAssistant", (), {})
        _core.ServiceCall = type("ServiceCall", (), {})
        _core.callback = lambda f: f

    _ce = _stub("homeassistant.config_entries")
    if not hasattr(_ce, "ConfigEntry"):
        _ce.ConfigEntry = type("ConfigEntry", (), {"data": {}})

    _exc = _stub("homeassistant.exceptions")
    if not hasattr(_exc, "HomeAssistantError"):
        _exc.HomeAssistantError = Exception
        _exc.ConfigEntryNotReady = Exception
    # Always ensure ServiceValidationError is present (needed by __init__.py top-level import)
    if not hasattr(_exc, "ServiceValidationError"):
        _exc.ServiceValidationError = Exception

    _dt = _stub("homeassistant.util.dt")
    if not hasattr(_dt, "utcnow"):
        def _parse_dt(s):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s)
            except (ValueError, TypeError):
                return None

        def _as_utc(dt_obj):
            if dt_obj is None:
                return None
            if dt_obj.tzinfo is None:
                return dt_obj.replace(tzinfo=timezone.utc)
            return dt_obj.astimezone(timezone.utc)

        _dt.utcnow = lambda: datetime.now(tz=timezone.utc)
        _dt.parse_datetime = _parse_dt
        _dt.as_utc = _as_utc

    _coord = _stub("homeassistant.helpers.update_coordinator")
    if not hasattr(_coord, "CoordinatorEntity"):
        class _CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator
            async def async_update(self):
                pass
        _coord.CoordinatorEntity = _CoordinatorEntity
        _coord.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
        _coord.UpdateFailed = Exception

    _dr = _stub("homeassistant.helpers.device_registry")
    if not hasattr(_dr, "DeviceInfo"):
        _dr.DeviceInfo = dict

    _ep = _stub("homeassistant.helpers.entity_platform")
    if not hasattr(_ep, "AddEntitiesCallback"):
        _ep.AddEntitiesCallback = type("AddEntitiesCallback", (), {})

    _ac = _stub("homeassistant.helpers.aiohttp_client")
    if not hasattr(_ac, "async_get_clientsession"):
        _ac.async_get_clientsession = MagicMock(return_value=None)

    _sensor = _stub("homeassistant.components.sensor")
    if not hasattr(_sensor, "SensorEntity"):
        _sensor.SensorEntity = type("SensorEntity", (), {})
        _sensor.SensorDeviceClass = types.SimpleNamespace(
            TIMESTAMP="timestamp", ENERGY="energy", MONETARY="monetary",
            POWER="power", GAS="gas", DATA_RATE="data_rate",
        )
        _sensor.SensorStateClass = types.SimpleNamespace(
            MEASUREMENT="measurement",
            TOTAL_INCREASING="total_increasing",
            TOTAL="total",
        )

    _bs = _stub("homeassistant.components.binary_sensor")
    if not hasattr(_bs, "BinarySensorEntity"):
        _bs.BinarySensorEntity = type("BinarySensorEntity", (), {})

    _sw = _stub("homeassistant.components.switch")
    if not hasattr(_sw, "SwitchEntity"):
        _sw.SwitchEntity = type("SwitchEntity", (), {})

    _num = _stub("homeassistant.components.number")
    if not hasattr(_num, "NumberEntity"):
        _num.NumberEntity = type("NumberEntity", (), {})
        _num.NumberMode = types.SimpleNamespace(SLIDER="slider", BOX="box")
        _num.RestoreNumber = type("RestoreNumber", (), {})

    _sel = _stub("homeassistant.components.select")
    if not hasattr(_sel, "SelectEntity"):
        _sel.SelectEntity = type("SelectEntity", (), {})


_install_stubs()

# ---------------------------------------------------------------------------
# Constants shared across test modules
# ---------------------------------------------------------------------------

ACCOUNT_NUMBER = "A-TEST1234"
DEVICE_ID = "krakenflex-device-test-001"

# ---------------------------------------------------------------------------
# Home Assistant mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Return a lightweight mock of homeassistant.core.HomeAssistant."""
    hass = MagicMock()
    hass.async_call_later = MagicMock()
    hass.async_create_task = MagicMock()
    hass.data = {}
    return hass


# ---------------------------------------------------------------------------
# Coordinator mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_coordinator():
    """Return a mock DataUpdateCoordinator."""
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# API client mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api():
    """Return a mock of OctopusEnergyIT with all async methods as AsyncMock."""
    api = MagicMock()
    api.login = AsyncMock(return_value=True)
    api.ensure_token = AsyncMock(return_value=True)
    api.fetch_accounts_with_initial_data = AsyncMock()
    api.accounts = AsyncMock(return_value=[ACCOUNT_NUMBER])
    api.fetch_accounts = AsyncMock()
    api.fetch_all_data = AsyncMock()
    api.fetch_flex_planned_dispatches = AsyncMock(return_value=[])
    api.update_boost_charge = AsyncMock(return_value=DEVICE_ID)
    api.change_device_suspension = AsyncMock(return_value=DEVICE_ID)
    api.set_device_preferences = AsyncMock(return_value=True)
    api.get_vehicle_devices = AsyncMock(return_value=[])
    api.fetch_gas_meter_readings = AsyncMock(return_value=[])
    api.fetch_electricity_measurements = AsyncMock(return_value=[])
    return api


# ---------------------------------------------------------------------------
# Realistic account-level data (simulates fetch_all_data return value)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_account_data():
    """Return a realistic dict that mirrors what fetch_all_data returns."""
    return {
        "account": {
            "id": "acc-001",
            "ledgers": [
                {"balance": 4250, "ledgerType": "ELECTRICITY_LEDGER"},
                {"balance": 900, "ledgerType": "GAS_LEDGER"},
            ],
            "properties": [
                {
                    "id": "prop-001",
                    "electricitySupplyPoints": [
                        {
                            "id": "esp-001",
                            "pod": "IT001E12345678901",
                            "status": "ACTIVE",
                            "enrolmentStatus": "ENROLLED",
                            "enrolmentStartDate": "2023-01-01",
                            "supplyStartDate": "2023-01-15",
                            "cancellationReason": None,
                            "isSmartMeter": True,
                            "product": {
                                "__typename": "ElectricityProductType",
                                "code": "VAR-IT-24-01-01",
                                "description": "Tariff F1/F2/F3",
                                "displayName": "Smart Flex",
                                "fullName": "Octopus Smart Flex",
                                "termsAndConditionsUrl": "https://example.com/terms",
                                "validTo": None,
                                "params": {
                                    "productType": "TIME_OF_USE",
                                    "annualStandingCharge": 200.0,
                                    "consumptionCharge": 0.25,
                                    "consumptionChargeF2": 0.22,
                                    "consumptionChargeF3": 0.18,
                                },
                                "prices": {
                                    "productType": "TIME_OF_USE",
                                    "annualStandingCharge": 200.0,
                                    "annualStandingChargeUnits": "EUR/year",
                                    "consumptionCharge": 0.25,
                                    "consumptionChargeF2": 0.22,
                                    "consumptionChargeF3": 0.18,
                                    "consumptionChargeUnits": "EUR/kWh",
                                },
                            },
                            "agreements": [
                                {
                                    "id": "agr-001",
                                    "validFrom": "2023-01-15",
                                    "validTo": None,
                                    "agreedAt": "2022-12-01",
                                    "terminatedAt": None,
                                    "isActive": True,
                                    "product": {
                                        "__typename": "ElectricityProductType",
                                        "code": "VAR-IT-24-01-01",
                                        "description": "Tariff F1/F2/F3",
                                        "displayName": "Smart Flex",
                                        "fullName": "Octopus Smart Flex",
                                        "termsAndConditionsUrl": "https://example.com/terms",
                                        "validTo": None,
                                        "params": {
                                            "productType": "TIME_OF_USE",
                                            "annualStandingCharge": 200.0,
                                            "consumptionCharge": 0.25,
                                            "consumptionChargeF2": 0.22,
                                            "consumptionChargeF3": 0.18,
                                        },
                                        "prices": {
                                            "productType": "TIME_OF_USE",
                                            "annualStandingCharge": 200.0,
                                            "annualStandingChargeUnits": "EUR/year",
                                            "consumptionCharge": 0.25,
                                            "consumptionChargeF2": 0.22,
                                            "consumptionChargeF3": 0.18,
                                            "consumptionChargeUnits": "EUR/kWh",
                                        },
                                    },
                                }
                            ],
                        }
                    ],
                    "gasSupplyPoints": [
                        {
                            "id": "gsp-001",
                            "pdr": "IT001G12345678901",
                            "status": "ACTIVE",
                            "enrolmentStatus": "ENROLLED",
                            "enrolmentStartDate": "2023-01-01",
                            "supplyStartDate": "2023-01-15",
                            "cancellationReason": None,
                            "isSmartMeter": False,
                            "product": {
                                "__typename": "GasProductType",
                                "code": "GAS-IT-24-01-01",
                                "description": "Gas Standard",
                                "displayName": "Gas Flex",
                                "fullName": "Octopus Gas Flex",
                                "termsAndConditionsUrl": "https://example.com/gas-terms",
                                "validTo": None,
                                "params": {
                                    "productType": "FIXED",
                                    "annualStandingCharge": 120.0,
                                    "consumptionCharge": 0.95,
                                },
                                "prices": {
                                    "annualStandingCharge": 120.0,
                                    "consumptionCharge": 0.95,
                                },
                            },
                            "agreements": [],
                        }
                    ],
                }
            ],
        },
        "products": [
            {
                "code": "VAR-IT-24-01-01",
                "description": "Tariff F1/F2/F3",
                "name": "Octopus Smart Flex",
                "displayName": "Smart Flex",
                "validFrom": "2023-01-15",
                "validTo": None,
                "agreementId": "agr-001",
                "productType": "TIME_OF_USE",
                "isTimeOfUse": True,
                "type": "TimeOfUse",
                "timeslots": [],
                "termsAndConditionsUrl": "https://example.com/terms",
                "pricing": {
                    "base": 0.25,
                    "f2": 0.22,
                    "f3": 0.18,
                    "units": "EUR/kWh",
                    "annualStandingCharge": 200.0,
                    "annualStandingChargeUnits": "EUR/year",
                },
                "params": {
                    "productType": "TIME_OF_USE",
                    "annualStandingCharge": 200.0,
                    "consumptionCharge": 0.25,
                    "consumptionChargeF2": 0.22,
                    "consumptionChargeF3": 0.18,
                },
                "rawPrices": {
                    "productType": "TIME_OF_USE",
                    "annualStandingCharge": 200.0,
                    "annualStandingChargeUnits": "EUR/year",
                    "consumptionCharge": 0.25,
                    "consumptionChargeF2": 0.22,
                    "consumptionChargeF3": 0.18,
                    "consumptionChargeUnits": "EUR/kWh",
                },
                "grossRate": "25",
                "supplyPoint": {
                    "id": "esp-001",
                    "pod": "IT001E12345678901",
                    "status": "ACTIVE",
                    "enrolmentStatus": "ENROLLED",
                    "enrolmentStartDate": "2023-01-01",
                    "supplyStartDate": "2023-01-15",
                    "isSmartMeter": True,
                    "cancellationReason": None,
                },
                "unitRateForecast": [],
            }
        ],
        "completedDispatches": [
            {
                "delta": -1.5,
                "deltaKwh": 1.5,
                "end": "2024-01-15T08:00:00Z",
                "endDt": "2024-01-15T08:00:00Z",
                "meta": {"location": "HOME", "source": "smart_flex"},
                "start": "2024-01-15T06:00:00Z",
                "startDt": "2024-01-15T06:00:00Z",
            }
        ],
        "devices": [
            {
                "id": DEVICE_ID,
                "name": "Test EV",
                "deviceType": "ELECTRIC_VEHICLES",
                "integrationDeviceId": "ext-device-001",
                "provider": "TEST_PROVIDER",
                "status": {
                    "current": "SMART_CONTROL_CAPABLE",
                    "currentState": "SMART_CONTROL_CAPABLE",
                    "isSuspended": False,
                },
                "preferences": {
                    "mode": "CHARGE",
                    "schedules": [
                        {
                            "dayOfWeek": "MONDAY",
                            "max": 80,
                            "min": 10,
                            "time": "07:00",
                        }
                    ],
                    "targetType": "PERCENTAGE",
                    "unit": "PERCENTAGE",
                    "gridExport": False,
                },
                "preferenceSetting": {
                    "deviceType": "ELECTRIC_VEHICLES",
                    "id": "pref-001",
                    "mode": "CHARGE",
                    "scheduleSettings": [
                        {
                            "id": "sched-001",
                            "max": 100,
                            "min": 10,
                            "step": 10,
                            "timeFrom": "04:00",
                            "timeStep": 30,
                            "timeTo": "17:00",
                        }
                    ],
                    "unit": "PERCENTAGE",
                },
                "alerts": [],
                "vehicleVariant": {
                    "model": "Test Model X",
                    "batterySize": 75.0,
                },
            }
        ],
        "plannedDispatches": [
            {
                "start": "2024-01-16T05:00:00Z",
                "startDt": "2024-01-16T05:00:00Z",
                "end": "2024-01-16T07:00:00Z",
                "endDt": "2024-01-16T07:00:00Z",
                "deltaKwh": 12.5,
                "delta": 12.5,
                "type": "SMART",
                "meta": {
                    "source": "flex_api",
                    "type": "SMART",
                    "deviceId": DEVICE_ID,
                },
            }
        ],
        "gas_products": [],
    }


# ---------------------------------------------------------------------------
# Coordinator data structure (keyed by account number)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_coordinator_data(sample_account_data):
    """Return coordinator.data dict keyed by account number."""
    return {
        ACCOUNT_NUMBER: {
            "devices": sample_account_data["devices"],
            "products": sample_account_data["products"],
            "ledgers": sample_account_data["account"]["ledgers"],
            "properties": sample_account_data["account"]["properties"],
            "plannedDispatches": sample_account_data["plannedDispatches"],
            "completedDispatches": sample_account_data["completedDispatches"],
            "meterReadings": {
                "electricity": [],
                "gas": [],
            },
            "electricity_balance": 42.50,
            "gas_balance": 9.00,
        }
    }

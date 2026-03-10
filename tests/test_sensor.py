"""Tests for sensor.py — dispatch window logic and meter reading sensors."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so sensor.py can be imported without homeassistant installed
# ---------------------------------------------------------------------------

import sys
import types


def _make_ha_stubs():
    """Insert lightweight HA stubs into sys.modules."""

    def _stub_module(*parts):
        mod = types.ModuleType(".".join(parts))
        sys.modules[".".join(parts)] = mod
        return mod

    # Top-level homeassistant package
    ha = types.ModuleType("homeassistant")
    sys.modules.setdefault("homeassistant", ha)

    for sub in [
        "homeassistant.components",
        "homeassistant.components.sensor",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.device_registry",
        "homeassistant.util",
        "homeassistant.util.dt",
        "homeassistant.exceptions",
    ]:
        if sub not in sys.modules:
            sys.modules[sub] = types.ModuleType(sub)

    # SensorEntity / SensorDeviceClass / SensorStateClass stubs
    sensor_mod = sys.modules["homeassistant.components.sensor"]
    if not hasattr(sensor_mod, "SensorEntity"):
        sensor_mod.SensorEntity = type("SensorEntity", (), {})
    if not hasattr(sensor_mod, "SensorDeviceClass"):
        sensor_mod.SensorDeviceClass = types.SimpleNamespace(
            TIMESTAMP="timestamp", ENERGY="energy", MONETARY="monetary",
            POWER="power", GAS="gas"
        )
    if not hasattr(sensor_mod, "SensorStateClass"):
        sensor_mod.SensorStateClass = types.SimpleNamespace(
            MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing"
        )

    # CoordinatorEntity stub
    coord_mod = sys.modules["homeassistant.helpers.update_coordinator"]
    if not hasattr(coord_mod, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator
            async def async_update(self):
                pass
        coord_mod.CoordinatorEntity = CoordinatorEntity

    # DeviceInfo stub
    device_mod = sys.modules["homeassistant.helpers.device_registry"]
    if not hasattr(device_mod, "DeviceInfo"):
        device_mod.DeviceInfo = dict

    # ConfigEntry stub
    config_mod = sys.modules["homeassistant.config_entries"]
    if not hasattr(config_mod, "ConfigEntry"):
        config_mod.ConfigEntry = type("ConfigEntry", (), {})

    # HomeAssistant / callback stubs
    core_mod = sys.modules["homeassistant.core"]
    if not hasattr(core_mod, "HomeAssistant"):
        core_mod.HomeAssistant = type("HomeAssistant", (), {})
    if not hasattr(core_mod, "callback"):
        core_mod.callback = lambda f: f

    # AddEntitiesCallback stub
    ep_mod = sys.modules["homeassistant.helpers.entity_platform"]
    if not hasattr(ep_mod, "AddEntitiesCallback"):
        ep_mod.AddEntitiesCallback = type("AddEntitiesCallback", (), {})

    # HomeAssistantError stub
    exc_mod = sys.modules["homeassistant.exceptions"]
    if not hasattr(exc_mod, "HomeAssistantError"):
        exc_mod.HomeAssistantError = Exception

    # homeassistant.util.dt stubs — utcnow, parse_datetime, as_utc
    dt_mod = sys.modules["homeassistant.util.dt"]
    if not hasattr(dt_mod, "utcnow"):
        dt_mod.utcnow = lambda: datetime.now(tz=timezone.utc)
    if not hasattr(dt_mod, "parse_datetime"):
        from datetime import datetime as _dt
        def _parse_dt(s):
            if not s:
                return None
            try:
                return _dt.fromisoformat(s)
            except (ValueError, TypeError):
                return None
        dt_mod.parse_datetime = _parse_dt
    if not hasattr(dt_mod, "as_utc"):
        def _as_utc(dt_obj):
            if dt_obj is None:
                return None
            if dt_obj.tzinfo is None:
                return dt_obj.replace(tzinfo=timezone.utc)
            return dt_obj.astimezone(timezone.utc)
        dt_mod.as_utc = _as_utc


_make_ha_stubs()

# Now we can import from the integration
from custom_components.octopus_energy_it.sensor import (  # noqa: E402
    _effective_dispatch_window,
    OctopusEvNextDispatchStartSensor,
    OctopusEvNextDispatchEndSensor,
    OctopusElectricityLastDailyReadingSensor,
    OctopusElectricityLastReadingSensor,
)
from custom_components.octopus_energy_it.entity import OctopusCoordinatorEntity  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT = "A-TEST001"

_UTC = timezone.utc

_T_1601 = datetime(2024, 1, 15, 16, 1, 0, tzinfo=_UTC)
_T_1700 = datetime(2024, 1, 15, 17, 0, 0, tzinfo=_UTC)
_T_1701 = datetime(2024, 1, 15, 17, 1, 0, tzinfo=_UTC)
_T_1800 = datetime(2024, 1, 15, 18, 0, 0, tzinfo=_UTC)
_T_1801 = datetime(2024, 1, 15, 18, 1, 0, tzinfo=_UTC)
_T_1900 = datetime(2024, 1, 15, 19, 0, 0, tzinfo=_UTC)


def _make_coordinator(account_data: dict) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {ACCOUNT: account_data}
    coordinator.last_update_success = True
    return coordinator


def _make_sensor(cls, coordinator):
    """Instantiate a sensor entity, patching CoordinatorEntity.__init__."""
    with patch.object(OctopusCoordinatorEntity, "__init__", lambda self, acc, coord: None):
        sensor = cls.__new__(cls)
        sensor._account_number = ACCOUNT
        sensor.coordinator = coordinator
        # Call the sensor's own __init__ directly but skip super().__init__
        sensor._attr_unique_id = None
        sensor._attr_device_info = {}
    return sensor


# ---------------------------------------------------------------------------
# _effective_dispatch_window
# ---------------------------------------------------------------------------

class TestEffectiveDispatchWindow:
    """Tests for the _effective_dispatch_window helper."""

    def test_active_and_future_returns_active(self):
        """When both current and future dispatches exist, the active one wins."""
        account_data = {
            "current_start": _T_1601,
            "current_end": _T_1701,
            "next_start": _T_1700,
            "next_end": _T_1800,
        }
        start, end = _effective_dispatch_window(account_data)
        assert start == _T_1601
        assert end == _T_1701

    def test_only_future_returns_future(self):
        """When current_start is absent, fall through to next_start / next_end."""
        account_data = {
            "next_start": _T_1700,
            "next_end": _T_1800,
        }
        start, end = _effective_dispatch_window(account_data)
        assert start == _T_1700
        assert end == _T_1800

    def test_only_active_returns_active(self):
        """Only current_start / current_end present — returns them."""
        account_data = {
            "current_start": _T_1601,
            "current_end": _T_1701,
        }
        start, end = _effective_dispatch_window(account_data)
        assert start == _T_1601
        assert end == _T_1701

    def test_no_dispatches_returns_none_none(self):
        """Empty account data yields (None, None)."""
        start, end = _effective_dispatch_window({})
        assert start is None
        assert end is None

    def test_current_start_none_explicit_falls_back_to_next(self):
        """Explicit None for current_start triggers fall-through to next_*."""
        account_data = {
            "current_start": None,
            "current_end": _T_1701,
            "next_start": _T_1800,
            "next_end": _T_1900,
        }
        start, end = _effective_dispatch_window(account_data)
        assert start == _T_1800
        assert end == _T_1900

    def test_missing_next_end_returns_none_end(self):
        """Only future start set (edge case) — end is None."""
        account_data = {"next_start": _T_1700}
        start, end = _effective_dispatch_window(account_data)
        assert start == _T_1700
        assert end is None


# ---------------------------------------------------------------------------
# OctopusEvNextDispatchStartSensor.native_value
# ---------------------------------------------------------------------------

class TestOctopusEvNextDispatchStartSensor:
    """Tests for OctopusEvNextDispatchStartSensor.native_value."""

    def _sensor(self, account_data):
        coord = _make_coordinator(account_data)
        return _make_sensor(OctopusEvNextDispatchStartSensor, coord)

    def test_active_dispatch_plus_future_returns_active_start(self):
        sensor = self._sensor({
            "current_start": _T_1601,
            "current_end": _T_1701,
            "next_start": _T_1700,
            "next_end": _T_1800,
        })
        assert sensor.native_value == _T_1601

    def test_only_future_dispatch_returns_future_start(self):
        sensor = self._sensor({
            "next_start": _T_1700,
            "next_end": _T_1800,
        })
        assert sensor.native_value == _T_1700

    def test_no_dispatches_returns_none(self):
        sensor = self._sensor({})
        assert sensor.native_value is None

    def test_no_coordinator_data_returns_none(self):
        coord = MagicMock()
        coord.data = None
        sensor = _make_sensor(OctopusEvNextDispatchStartSensor, coord)
        assert sensor.native_value is None


# ---------------------------------------------------------------------------
# OctopusEvNextDispatchEndSensor.native_value
# ---------------------------------------------------------------------------

class TestOctopusEvNextDispatchEndSensor:
    """Tests for OctopusEvNextDispatchEndSensor.native_value."""

    def _sensor(self, account_data):
        coord = _make_coordinator(account_data)
        return _make_sensor(OctopusEvNextDispatchEndSensor, coord)

    def test_active_dispatch_plus_future_returns_active_end(self):
        sensor = self._sensor({
            "current_start": _T_1601,
            "current_end": _T_1701,
            "next_start": _T_1700,
            "next_end": _T_1800,
        })
        assert sensor.native_value == _T_1701

    def test_only_future_dispatch_returns_future_end(self):
        sensor = self._sensor({
            "next_start": _T_1700,
            "next_end": _T_1800,
        })
        assert sensor.native_value == _T_1800

    def test_no_dispatches_returns_none(self):
        sensor = self._sensor({})
        assert sensor.native_value is None

    def test_no_coordinator_data_returns_none(self):
        coord = MagicMock()
        coord.data = None
        sensor = _make_sensor(OctopusEvNextDispatchEndSensor, coord)
        assert sensor.native_value is None


# ---------------------------------------------------------------------------
# OctopusElectricityLastDailyReadingSensor.native_value
# ---------------------------------------------------------------------------

class TestOctopusElectricityLastDailyReadingSensor:
    """Tests for OctopusElectricityLastDailyReadingSensor.native_value."""

    def _sensor(self, reading):
        account_data = {"electricity_last_reading": reading} if reading is not None else {}
        coord = _make_coordinator(account_data)
        return _make_sensor(OctopusElectricityLastDailyReadingSensor, coord)

    def test_value_rounded_to_three_decimal_places(self):
        sensor = self._sensor({"value": "1.2345"})
        result = sensor.native_value
        assert result == 1.234
        # Confirm it is NOT rounded to 2 decimal places
        assert result != round(1.2345, 2)

    def test_value_exact_three_decimals_unchanged(self):
        sensor = self._sensor({"value": "100.123"})
        assert sensor.native_value == 100.123

    def test_value_needs_no_rounding(self):
        sensor = self._sensor({"value": "42.0"})
        assert sensor.native_value == 42.0

    def test_value_none_returns_none(self):
        sensor = self._sensor({"value": None})
        assert sensor.native_value is None

    def test_reading_absent_returns_none(self):
        sensor = self._sensor(None)
        assert sensor.native_value is None

    def test_integer_value_as_string(self):
        sensor = self._sensor({"value": "50"})
        assert sensor.native_value == 50.0

    def test_extra_precision_truncates_at_third_place(self):
        # round(1.23456, 3) == 1.235 (standard rounding)
        sensor = self._sensor({"value": "1.23456"})
        assert sensor.native_value == round(1.23456, 3)


# ---------------------------------------------------------------------------
# OctopusElectricityLastReadingSensor.native_value
# ---------------------------------------------------------------------------

class TestOctopusElectricityLastReadingSensor:
    """Tests for OctopusElectricityLastReadingSensor.native_value (end_register_value)."""

    def _sensor(self, reading):
        account_data = {"electricity_last_reading": reading} if reading is not None else {}
        coord = _make_coordinator(account_data)
        return _make_sensor(OctopusElectricityLastReadingSensor, coord)

    def test_value_rounded_to_three_decimal_places(self):
        sensor = self._sensor({"end_register_value": "100.123456"})
        assert sensor.native_value == 100.123

    def test_value_none_returns_none(self):
        sensor = self._sensor({"end_register_value": None})
        assert sensor.native_value is None

    def test_reading_absent_returns_none(self):
        sensor = self._sensor(None)
        assert sensor.native_value is None

    def test_integer_string_value(self):
        sensor = self._sensor({"end_register_value": "9999"})
        assert sensor.native_value == 9999.0

    def test_high_precision_rounding(self):
        sensor = self._sensor({"end_register_value": "0.9999"})
        assert sensor.native_value == round(0.9999, 3)

    def test_reading_without_end_register_key_returns_none(self):
        # Reading dict has no end_register_value key at all
        sensor = self._sensor({"value": "42.0"})
        assert sensor.native_value is None

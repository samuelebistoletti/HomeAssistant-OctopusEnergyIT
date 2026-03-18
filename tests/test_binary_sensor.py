"""Tests for binary_sensor.py — IntelligentDispatchingBinarySensor."""

import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# HA stubs (idempotent — safe to run alongside other test modules)
# ---------------------------------------------------------------------------


def _ensure_ha_stubs():
    def _stub(name):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
        return sys.modules[name]

    _stub("homeassistant")
    _stub("homeassistant.components")
    _stub("homeassistant.config_entries")
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.entity_platform")
    _stub("homeassistant.helpers.device_registry")
    _stub("homeassistant.util")

    binary_mod = _stub("homeassistant.components.binary_sensor")
    if not hasattr(binary_mod, "BinarySensorEntity"):
        binary_mod.BinarySensorEntity = type("BinarySensorEntity", (), {})

    coord_mod = _stub("homeassistant.helpers.update_coordinator")
    if not hasattr(coord_mod, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator
            async def async_update(self):
                pass
        coord_mod.CoordinatorEntity = CoordinatorEntity

    device_mod = _stub("homeassistant.helpers.device_registry")
    if not hasattr(device_mod, "DeviceInfo"):
        device_mod.DeviceInfo = dict

    config_mod = _stub("homeassistant.config_entries")
    if not hasattr(config_mod, "ConfigEntry"):
        config_mod.ConfigEntry = type("ConfigEntry", (), {})

    core_mod = _stub("homeassistant.core")
    if not hasattr(core_mod, "HomeAssistant"):
        core_mod.HomeAssistant = type("HomeAssistant", (), {})
    if not hasattr(core_mod, "callback"):
        core_mod.callback = lambda f: f

    ep_mod = _stub("homeassistant.helpers.entity_platform")
    if not hasattr(ep_mod, "AddEntitiesCallback"):
        ep_mod.AddEntitiesCallback = type("AddEntitiesCallback", (), {})

    exc_mod = _stub("homeassistant.exceptions")
    if not hasattr(exc_mod, "HomeAssistantError"):
        exc_mod.HomeAssistantError = Exception

    dt_mod = _stub("homeassistant.util.dt")
    if not hasattr(dt_mod, "utcnow"):
        dt_mod.utcnow = lambda: datetime.now(tz=timezone.utc)
    if not hasattr(dt_mod, "parse_datetime"):
        def _parse_dt(s):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s)
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

    # sensor stubs needed by entity.py / sensor.py imports
    sensor_mod = _stub("homeassistant.components.sensor")
    if not hasattr(sensor_mod, "SensorEntity"):
        sensor_mod.SensorEntity = type("SensorEntity", (), {})
    if not hasattr(sensor_mod, "SensorDeviceClass"):
        sensor_mod.SensorDeviceClass = types.SimpleNamespace(TIMESTAMP="timestamp", ENERGY="energy", MONETARY="monetary")
    if not hasattr(sensor_mod, "SensorStateClass"):
        sensor_mod.SensorStateClass = types.SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing")

    switch_mod = _stub("homeassistant.components.switch")
    if not hasattr(switch_mod, "SwitchEntity"):
        switch_mod.SwitchEntity = type("SwitchEntity", (), {})


_ensure_ha_stubs()

from custom_components.octopus_energy_it.binary_sensor import (  # noqa: E402
    OctopusIntelligentDispatchingBinarySensor,
)
from custom_components.octopus_energy_it.entity import OctopusCoordinatorEntity  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT = "A-TEST001"
_UTC = timezone.utc

# A fixed "now" we can control via patch
_NOW = datetime(2024, 1, 15, 17, 30, 0, tzinfo=_UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_coordinator(planned_dispatches: list) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {
        ACCOUNT: {
            "devices": [{"id": "dev-001"}],
            "planned_dispatches": planned_dispatches,
        }
    }
    coordinator.last_update_success = True
    return coordinator


def _make_sensor(coordinator) -> OctopusIntelligentDispatchingBinarySensor:
    """Build the binary sensor, bypassing super().__init__."""
    with patch.object(OctopusCoordinatorEntity, "__init__", lambda self, acc, coord: None):
        sensor = OctopusIntelligentDispatchingBinarySensor.__new__(
            OctopusIntelligentDispatchingBinarySensor
        )
        sensor._account_number = ACCOUNT
        sensor.coordinator = coordinator
        sensor._attr_device_info = {}
        sensor._attr_unique_id = f"octopus_{ACCOUNT}_intelligent_dispatching"
        sensor._attributes = {}
    return sensor


def _sensor_with_dispatches(dispatches: list) -> OctopusIntelligentDispatchingBinarySensor:
    return _make_sensor(_make_coordinator(dispatches))


# ---------------------------------------------------------------------------
# OctopusIntelligentDispatchingBinarySensor.is_on
# ---------------------------------------------------------------------------

class TestIntelligentDispatchingBinarySensorIsOn:
    """Tests for OctopusIntelligentDispatchingBinarySensor.is_on."""

    def _is_on(self, dispatches, now=_NOW):
        """Helper: evaluate is_on with a fixed 'now'.

        The production code does `from homeassistant.util.dt import utcnow`,
        so `utcnow` is bound directly in the binary_sensor module namespace.
        We must patch it there, not on the dt stub module.
        """
        sensor = _sensor_with_dispatches(dispatches)
        target = "custom_components.octopus_energy_it.binary_sensor.utcnow"
        with patch(target, return_value=now):
            return sensor.is_on

    # ------------------------------------------------------------------
    # Dispatch containing 'now'
    # ------------------------------------------------------------------

    def test_dispatch_window_containing_now_is_on_true(self):
        """A dispatch whose window contains the current time → is_on=True."""
        dispatches = [
            {
                "start": _iso(_NOW - timedelta(minutes=30)),
                "end": _iso(_NOW + timedelta(minutes=30)),
            }
        ]
        assert self._is_on(dispatches) is True

    def test_dispatch_starting_exactly_at_now_is_on_true(self):
        """Boundary: start == now → active (start <= now <= end)."""
        dispatches = [
            {
                "start": _iso(_NOW),
                "end": _iso(_NOW + timedelta(hours=1)),
            }
        ]
        assert self._is_on(dispatches) is True

    def test_dispatch_ending_exactly_at_now_is_on_true(self):
        """Boundary: end == now → still active (start <= now <= end)."""
        dispatches = [
            {
                "start": _iso(_NOW - timedelta(hours=1)),
                "end": _iso(_NOW),
            }
        ]
        assert self._is_on(dispatches) is True

    # ------------------------------------------------------------------
    # Future dispatch
    # ------------------------------------------------------------------

    def test_dispatch_in_future_is_on_false(self):
        """Dispatch that hasn't started yet → is_on=False."""
        dispatches = [
            {
                "start": _iso(_NOW + timedelta(hours=1)),
                "end": _iso(_NOW + timedelta(hours=2)),
            }
        ]
        assert self._is_on(dispatches) is False

    # ------------------------------------------------------------------
    # Past dispatch
    # ------------------------------------------------------------------

    def test_dispatch_in_past_is_on_false(self):
        """Dispatch that already ended → is_on=False."""
        dispatches = [
            {
                "start": _iso(_NOW - timedelta(hours=2)),
                "end": _iso(_NOW - timedelta(hours=1)),
            }
        ]
        assert self._is_on(dispatches) is False

    # ------------------------------------------------------------------
    # Empty / missing dispatches
    # ------------------------------------------------------------------

    def test_empty_planned_dispatches_is_on_false(self):
        assert self._is_on([]) is False

    def test_no_planned_dispatches_key_is_on_false(self):
        """Account data has no planned_dispatches key at all."""
        coordinator = MagicMock()
        coordinator.data = {
            ACCOUNT: {"devices": [{"id": "dev-001"}]}
        }
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        dt_mod = sys.modules["homeassistant.util.dt"]
        with patch.object(dt_mod, "utcnow", return_value=_NOW):
            assert sensor.is_on is False

    def test_no_coordinator_data_is_on_false(self):
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        assert sensor.is_on is False

    # ------------------------------------------------------------------
    # Multiple dispatches — only one active
    # ------------------------------------------------------------------

    def test_multiple_dispatches_one_active_returns_true(self):
        """Among several dispatches, the one containing now activates the sensor."""
        dispatches = [
            # past
            {"start": _iso(_NOW - timedelta(hours=3)), "end": _iso(_NOW - timedelta(hours=2))},
            # active
            {"start": _iso(_NOW - timedelta(minutes=15)), "end": _iso(_NOW + timedelta(minutes=15))},
            # future
            {"start": _iso(_NOW + timedelta(hours=1)), "end": _iso(_NOW + timedelta(hours=2))},
        ]
        assert self._is_on(dispatches) is True

    def test_multiple_dispatches_none_active_returns_false(self):
        dispatches = [
            {"start": _iso(_NOW - timedelta(hours=3)), "end": _iso(_NOW - timedelta(hours=2))},
            {"start": _iso(_NOW + timedelta(hours=1)), "end": _iso(_NOW + timedelta(hours=2))},
        ]
        assert self._is_on(dispatches) is False

    # ------------------------------------------------------------------
    # Malformed dispatch entries are skipped gracefully
    # ------------------------------------------------------------------

    def test_dispatch_missing_start_is_skipped(self):
        dispatches = [
            {"end": _iso(_NOW + timedelta(hours=1))},
        ]
        assert self._is_on(dispatches) is False

    def test_dispatch_missing_end_is_skipped(self):
        dispatches = [
            {"start": _iso(_NOW - timedelta(hours=1))},
        ]
        assert self._is_on(dispatches) is False

    def test_dispatch_with_invalid_datetime_string_is_skipped(self):
        """Invalid datetime strings must not raise — sensor returns False."""
        dispatches = [
            {"start": "not-a-date", "end": "also-not-a-date"},
        ]
        # Should not raise; sensor treats the dispatch as non-active
        result = self._is_on(dispatches)
        assert result is False

    # ------------------------------------------------------------------
    # Account not in coordinator data
    # ------------------------------------------------------------------

    def test_account_not_in_coordinator_data_is_on_false(self):
        coordinator = MagicMock()
        coordinator.data = {"OTHER-ACCOUNT": {"planned_dispatches": []}}
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        assert sensor.is_on is False


# ---------------------------------------------------------------------------
# OctopusIntelligentDispatchingBinarySensor.available
# ---------------------------------------------------------------------------


class TestIntelligentDispatchingBinarySensorAvailable:
    """Tests for OctopusIntelligentDispatchingBinarySensor.available."""

    def test_available_when_coordinator_ok_and_account_present(self):
        coordinator = _make_coordinator([])
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        assert sensor.available is True

    def test_unavailable_when_coordinator_update_failed(self):
        coordinator = _make_coordinator([])
        coordinator.last_update_success = False
        sensor = _make_sensor(coordinator)
        assert sensor.available is False

    def test_unavailable_when_coordinator_data_is_none(self):
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        assert sensor.available is False

    def test_unavailable_when_coordinator_data_not_dict(self):
        coordinator = MagicMock()
        coordinator.data = ["not", "a", "dict"]
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        assert sensor.available is False

    def test_unavailable_when_account_not_in_data(self):
        coordinator = MagicMock()
        coordinator.data = {"OTHER-ACCOUNT": {}}
        coordinator.last_update_success = True
        sensor = _make_sensor(coordinator)
        assert sensor.available is False

    def test_unavailable_when_coordinator_is_none(self):
        sensor = _make_sensor(MagicMock())
        sensor.coordinator = None
        assert sensor.available is False

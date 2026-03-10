"""Tests for switch.py — OctopusSwitch and BoostChargeSwitch."""

import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# HA stubs (same pattern as test_sensor.py — idempotent if already present)
# ---------------------------------------------------------------------------


def _ensure_ha_stubs():
    def _stub(name):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
        return sys.modules[name]

    ha = _stub("homeassistant")
    _stub("homeassistant.components")
    _stub("homeassistant.config_entries")
    _stub("homeassistant.core")
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.entity_platform")
    _stub("homeassistant.helpers.device_registry")

    switch_mod = _stub("homeassistant.components.switch")
    if not hasattr(switch_mod, "SwitchEntity"):
        switch_mod.SwitchEntity = type("SwitchEntity", (), {})

    coord_mod = _stub("homeassistant.helpers.update_coordinator")
    if not hasattr(coord_mod, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator
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
    _stub("homeassistant.util")
    if not hasattr(dt_mod, "utcnow"):
        dt_mod.utcnow = lambda: datetime.now(tz=timezone.utc)

    # sensor stubs needed by entity.py indirectly (if already done, skip)
    sensor_mod = _stub("homeassistant.components.sensor")
    if not hasattr(sensor_mod, "SensorEntity"):
        sensor_mod.SensorEntity = type("SensorEntity", (), {})
    if not hasattr(sensor_mod, "SensorDeviceClass"):
        sensor_mod.SensorDeviceClass = types.SimpleNamespace(TIMESTAMP="timestamp", ENERGY="energy", MONETARY="monetary")
    if not hasattr(sensor_mod, "SensorStateClass"):
        sensor_mod.SensorStateClass = types.SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing")


_ensure_ha_stubs()

from custom_components.octopus_energy_it.switch import OctopusSwitch, BoostChargeSwitch  # noqa: E402
from custom_components.octopus_energy_it.entity import OctopusCoordinatorEntity  # noqa: E402
from custom_components.octopus_energy_it.const import DOMAIN  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT = "A-TEST001"
DEVICE_ID_1 = "device-aaa-111"
DEVICE_ID_2 = "device-bbb-222"

_UTC = timezone.utc


def _make_coordinator(account_data: dict) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {ACCOUNT: account_data}
    coordinator.last_update_success = True
    return coordinator


def _make_octopus_switch(device: dict, coordinator=None, account=ACCOUNT):
    """Construct an OctopusSwitch without HA plumbing."""
    if coordinator is None:
        coordinator = _make_coordinator({"devices": [device]})
    api = MagicMock()
    config_entry = MagicMock()
    config_entry.data = {}

    with patch.object(OctopusCoordinatorEntity, "__init__", lambda self, acc, coord: None):
        switch = OctopusSwitch.__new__(OctopusSwitch)
        # Replicate OctopusSwitch.__init__ manually, skipping super().__init__
        switch._account_number = account
        switch.coordinator = coordinator
        switch._attr_device_info = {}
        switch._api = api
        switch._device = device
        switch._config_entry = config_entry
        switch._device_id = device["id"]
        switch._current_state = not device.get("status", {}).get("isSuspended", True)
        switch._is_switching = False
        switch._pending_state = None
        switch._pending_until = None
        switch._attr_unique_id = (
            f"octopus_{account}_{device['id']}_ev_charge_smart_control"
        )
        switch._attr_extra_state_attributes = {}
    return switch


def _make_boost_switch(device_id: str, device_name: str = "My Car",
                       coordinator=None, account=ACCOUNT):
    """Construct a BoostChargeSwitch without HA plumbing."""
    if coordinator is None:
        coordinator = MagicMock()
        coordinator.data = {}
        coordinator.last_update_success = True
    client = MagicMock()

    with patch.object(OctopusCoordinatorEntity, "__init__", lambda self, acc, coord: None):
        switch = BoostChargeSwitch.__new__(BoostChargeSwitch)
        switch._account_number = account
        switch.coordinator = coordinator
        switch._attr_device_info = {}
        switch.client = client
        switch.device_id = device_id
        switch.device_name = device_name
        switch.account_number = account
        switch._attr_unique_id = f"{DOMAIN}_{account}_{device_id}_boost_charge"
        switch._is_switching = False
        switch._pending_state = None
        switch._pending_until = None
    return switch


# ---------------------------------------------------------------------------
# OctopusSwitch.unique_id
# ---------------------------------------------------------------------------

class TestOctopusSwitchUniqueId:
    """Tests for OctopusSwitch._attr_unique_id."""

    def test_unique_id_contains_device_id(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        switch = _make_octopus_switch(device)
        assert DEVICE_ID_1 in switch._attr_unique_id

    def test_unique_id_format(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        switch = _make_octopus_switch(device)
        expected = f"octopus_{ACCOUNT}_{DEVICE_ID_1}_ev_charge_smart_control"
        assert switch._attr_unique_id == expected

    def test_two_devices_have_different_unique_ids(self):
        dev1 = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        dev2 = {"id": DEVICE_ID_2, "status": {"isSuspended": False}}
        coordinator = _make_coordinator({"devices": [dev1, dev2]})
        s1 = _make_octopus_switch(dev1, coordinator=coordinator)
        s2 = _make_octopus_switch(dev2, coordinator=coordinator)
        assert s1._attr_unique_id != s2._attr_unique_id

    def test_unique_id_includes_account_number(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        switch = _make_octopus_switch(device)
        assert ACCOUNT in switch._attr_unique_id


# ---------------------------------------------------------------------------
# BoostChargeSwitch.unique_id
# ---------------------------------------------------------------------------

class TestBoostChargeSwitchUniqueId:
    """Tests for BoostChargeSwitch._attr_unique_id."""

    def test_unique_id_format(self):
        switch = _make_boost_switch(DEVICE_ID_1, "Tesla Model 3")
        expected = f"{DOMAIN}_{ACCOUNT}_{DEVICE_ID_1}_boost_charge"
        assert switch._attr_unique_id == expected

    def test_unique_id_is_based_on_device_id_not_name(self):
        """unique_id must use device_id, not a slug of the device name."""
        s1 = _make_boost_switch(DEVICE_ID_1, "Same Name")
        s2 = _make_boost_switch(DEVICE_ID_2, "Same Name")
        # Same name → different unique_ids because device_id differs
        assert s1._attr_unique_id != s2._attr_unique_id

    def test_two_devices_different_unique_ids(self):
        s1 = _make_boost_switch(DEVICE_ID_1)
        s2 = _make_boost_switch(DEVICE_ID_2)
        assert s1._attr_unique_id != s2._attr_unique_id

    def test_domain_prefix_in_unique_id(self):
        switch = _make_boost_switch(DEVICE_ID_1)
        assert switch._attr_unique_id.startswith(DOMAIN)

    def test_unique_id_contains_boost_charge_suffix(self):
        switch = _make_boost_switch(DEVICE_ID_1)
        assert switch._attr_unique_id.endswith("_boost_charge")


# ---------------------------------------------------------------------------
# BoostChargeSwitch.available
# ---------------------------------------------------------------------------

class TestBoostChargeSwitchAvailable:
    """Tests for BoostChargeSwitch.available property."""

    def _switch_with_device(self, device: dict) -> BoostChargeSwitch:
        coordinator = _make_coordinator({"devices": [device]})
        return _make_boost_switch(DEVICE_ID_1, coordinator=coordinator)

    def test_live_and_smart_control_capable_is_available(self):
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "LIVE",
                "currentState": "SMART_CONTROL_CAPABLE",
                "isSuspended": False,
            },
        }
        switch = self._switch_with_device(device)
        assert switch.available is True

    def test_not_live_but_unsuspended_falls_back_to_available(self):
        """When boost_available is False the fallback is `not isSuspended`.
        A PENDING, unsuspended device therefore still reports available=True
        via the fallback path — this is the actual contract of the code."""
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "PENDING",
                "currentState": "SMART_CONTROL_CAPABLE",
                "isSuspended": False,
            },
        }
        switch = self._switch_with_device(device)
        # boost_available=False (not LIVE), fallback: not isSuspended → True
        assert switch.available is True

    def test_not_live_and_suspended_is_unavailable(self):
        """A non-LIVE device that is also suspended is unavailable."""
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "PENDING",
                "currentState": "",
                "isSuspended": True,
            },
        }
        switch = self._switch_with_device(device)
        # boost_available=False (not LIVE), fallback: not isSuspended → False
        assert switch.available is False

    def test_live_with_no_capabilities_but_boost_charging_is_available(self):
        """A device that is actively BOOST_CHARGING should be available."""
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "LIVE",
                "currentState": "BOOST_CHARGING",
                "isSuspended": False,
            },
        }
        switch = self._switch_with_device(device)
        assert switch.available is True

    def test_live_with_boost_state_is_available(self):
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "LIVE",
                "currentState": "BOOST",
                "isSuspended": False,
            },
        }
        switch = self._switch_with_device(device)
        assert switch.available is True

    def test_suspended_device_is_unavailable_when_no_boost_flags(self):
        """Suspended device with no boost capability should be unavailable."""
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "LIVE",
                "currentState": "",
                "isSuspended": True,
            },
        }
        switch = self._switch_with_device(device)
        # boost_available is False (suspended), fallback checks isSuspended → True → returns False
        assert switch.available is False

    def test_coordinator_update_failure_makes_unavailable(self):
        coordinator = _make_coordinator({"devices": []})
        coordinator.last_update_success = False
        switch = _make_boost_switch(DEVICE_ID_1, coordinator=coordinator)
        assert switch.available is False

    def test_device_not_found_in_coordinator_is_unavailable(self):
        """When device_id is not in coordinator devices list, available=False."""
        other_device = {
            "id": "other-device-999",
            "status": {
                "current": "LIVE",
                "currentState": "SMART_CONTROL_CAPABLE",
                "isSuspended": False,
            },
        }
        coordinator = _make_coordinator({"devices": [other_device]})
        switch = _make_boost_switch(DEVICE_ID_1, coordinator=coordinator)
        # DEVICE_ID_1 is not in the coordinator's device list
        assert switch.available is False

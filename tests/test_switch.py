"""Tests for switch.py — OctopusSwitch and BoostChargeSwitch."""

import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
        switch._api = client
        switch._device_id = device_id
        switch._device_name = device_name
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


# ---------------------------------------------------------------------------
# OctopusSwitch.available
# ---------------------------------------------------------------------------


class TestOctopusSwitchAvailable:
    """Tests for OctopusSwitch.available."""

    def test_available_when_coordinator_has_data_and_device_found(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        coordinator = _make_coordinator({"devices": [device]})
        coordinator.last_update_success = True
        switch = _make_octopus_switch(device, coordinator=coordinator)
        assert switch.available is True

    def test_unavailable_when_coordinator_update_failed(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        coordinator = _make_coordinator({"devices": [device]})
        coordinator.last_update_success = False
        switch = _make_octopus_switch(device, coordinator=coordinator)
        assert switch.available is False

    def test_unavailable_when_device_not_in_coordinator(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        coordinator = _make_coordinator({"devices": []})  # empty list
        switch = _make_octopus_switch(device, coordinator=coordinator)
        assert switch.available is False

    def test_unavailable_when_account_not_in_coordinator(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        coordinator = MagicMock()
        coordinator.data = {"OTHER-ACCOUNT": {"devices": [device]}}
        coordinator.last_update_success = True
        switch = _make_octopus_switch(device, coordinator=coordinator)
        assert switch.available is False


# ---------------------------------------------------------------------------
# OctopusSwitch.is_on
# ---------------------------------------------------------------------------


class TestOctopusSwitchIsOn:
    """Tests for OctopusSwitch.is_on."""

    _UTCNOW = "custom_components.octopus_energy_it.switch.utcnow"

    def _make(self, is_suspended: bool) -> "OctopusSwitch":
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": is_suspended}}
        return _make_octopus_switch(device)

    def test_not_suspended_is_on_true(self):
        switch = self._make(is_suspended=False)
        assert switch.is_on is True

    def test_suspended_is_on_false(self):
        switch = self._make(is_suspended=True)
        assert switch.is_on is False

    def test_pending_state_returned_before_timeout(self):
        """While _is_switching, is_on returns _pending_state instead of API state."""
        switch = self._make(is_suspended=True)  # API says off
        switch._is_switching = True
        switch._pending_state = True  # optimistic: we want it on
        switch._pending_until = datetime(2099, 1, 1, tzinfo=_UTC)
        with patch(self._UTCNOW, return_value=datetime(2026, 1, 1, tzinfo=_UTC)):
            assert switch.is_on is True  # pending overrides API

    def test_pending_state_cleared_after_timeout(self):
        """After timeout, pending is cleared and API state wins."""
        switch = self._make(is_suspended=True)  # API says off
        switch._is_switching = True
        switch._pending_state = True
        switch._pending_until = datetime(2020, 1, 1, tzinfo=_UTC)  # past
        with patch(self._UTCNOW, return_value=datetime(2026, 1, 1, tzinfo=_UTC)):
            result = switch.is_on
        # After timeout expiry, pending cleared, device is suspended → False
        assert result is False
        assert switch._is_switching is False
        assert switch._pending_state is None

    def test_no_device_returns_false(self):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        coordinator = _make_coordinator({"devices": []})  # device gone
        switch = _make_octopus_switch(device, coordinator=coordinator)
        assert switch.is_on is False


# ---------------------------------------------------------------------------
# OctopusSwitch.async_turn_on / async_turn_off
# ---------------------------------------------------------------------------


class TestOctopusSwitchTurnOnOff:
    """Tests for OctopusSwitch.async_turn_on and async_turn_off."""

    from unittest.mock import AsyncMock as _AsyncMock

    _UTCNOW = "custom_components.octopus_energy_it.switch.utcnow"
    _FIXED_NOW = datetime(2026, 3, 18, 12, 0, 0, tzinfo=_UTC)

    def _make(self, is_suspended=False):
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": is_suspended}}
        switch = _make_octopus_switch(device)
        switch.async_write_ha_state = MagicMock()
        switch.coordinator.async_request_refresh = AsyncMock()
        return switch

    @pytest.mark.asyncio
    async def test_turn_on_calls_api_unsuspend(self):
        switch = self._make()
        switch._api.change_device_suspension = AsyncMock(return_value=True)
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_on()
        switch._api.change_device_suspension.assert_awaited_once_with(DEVICE_ID_1, "UNSUSPEND")

    @pytest.mark.asyncio
    async def test_turn_on_sets_pending_state(self):
        switch = self._make()
        switch._api.change_device_suspension = AsyncMock(return_value=True)
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_on()
        # After success, coordinator refresh is requested; pending may be cleared by coordinator update
        switch.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_on_api_failure_clears_pending(self):
        switch = self._make()
        switch._api.change_device_suspension = AsyncMock(return_value=False)
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_on()
        assert switch._is_switching is False
        assert switch._pending_state is None

    @pytest.mark.asyncio
    async def test_turn_on_api_exception_clears_pending(self):
        switch = self._make()
        switch._api.change_device_suspension = AsyncMock(side_effect=Exception("boom"))
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_on()
        assert switch._is_switching is False
        assert switch._pending_state is None

    @pytest.mark.asyncio
    async def test_turn_off_calls_api_suspend(self):
        switch = self._make()
        switch._api.change_device_suspension = AsyncMock(return_value=True)
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_off()
        switch._api.change_device_suspension.assert_awaited_once_with(DEVICE_ID_1, "SUSPEND")

    @pytest.mark.asyncio
    async def test_turn_off_api_failure_clears_pending(self):
        switch = self._make()
        switch._api.change_device_suspension = AsyncMock(return_value=False)
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_off()
        assert switch._is_switching is False
        assert switch._pending_state is None


# ---------------------------------------------------------------------------
# OctopusSwitch._handle_coordinator_update
# ---------------------------------------------------------------------------


class TestOctopusSwitchCoordinatorUpdate:

    def _make_with_device(self, is_suspended: bool) -> "OctopusSwitch":
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": is_suspended}}
        switch = _make_octopus_switch(device)
        switch.async_write_ha_state = MagicMock()
        return switch

    def test_state_updated_from_coordinator(self):
        switch = self._make_with_device(is_suspended=False)
        switch._current_state = False  # stale
        # Coordinator now says not suspended (on)
        switch._handle_coordinator_update()
        assert switch._current_state is True

    def test_switching_confirmed_clears_pending(self):
        """When API confirms the pending state, _is_switching is cleared."""
        device = {"id": DEVICE_ID_1, "status": {"isSuspended": False}}
        coordinator = _make_coordinator({"devices": [device]})
        switch = _make_octopus_switch(device, coordinator=coordinator)
        switch.async_write_ha_state = MagicMock()
        switch._is_switching = True
        switch._pending_state = True  # wanted: on (not suspended)
        switch._handle_coordinator_update()
        assert switch._is_switching is False
        assert switch._pending_state is None

    def test_always_writes_ha_state(self):
        switch = self._make_with_device(is_suspended=False)
        switch._handle_coordinator_update()
        switch.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# BoostChargeSwitch.is_on
# ---------------------------------------------------------------------------


class TestBoostChargeSwitchIsOn:

    _UTCNOW = "custom_components.octopus_energy_it.switch.utcnow"

    def _switch_with_state(self, current_state: str) -> "BoostChargeSwitch":
        device = {
            "id": DEVICE_ID_1,
            "status": {
                "current": "LIVE",
                "currentState": current_state,
                "isSuspended": False,
            },
        }
        return _make_boost_switch(DEVICE_ID_1, coordinator=_make_coordinator({"devices": [device]}))

    def test_boost_charging_is_on_true(self):
        switch = self._switch_with_state("BOOST_CHARGING")
        assert switch.is_on is True

    def test_boost_state_is_on_true(self):
        switch = self._switch_with_state("BOOST")
        assert switch.is_on is True

    def test_smart_control_capable_is_on_false(self):
        switch = self._switch_with_state("SMART_CONTROL_CAPABLE")
        assert switch.is_on is False

    def test_no_device_data_is_on_false(self):
        coordinator = _make_coordinator({"devices": []})
        switch = _make_boost_switch(DEVICE_ID_1, coordinator=coordinator)
        assert switch.is_on is False

    def test_pending_state_overrides_before_timeout(self):
        switch = self._switch_with_state("SMART_CONTROL_CAPABLE")  # API: off
        switch._is_switching = True
        switch._pending_state = True
        switch._pending_until = datetime(2099, 1, 1, tzinfo=_UTC)
        with patch(self._UTCNOW, return_value=datetime(2026, 1, 1, tzinfo=_UTC)):
            assert switch.is_on is True

    def test_pending_cleared_after_timeout(self):
        switch = self._switch_with_state("SMART_CONTROL_CAPABLE")
        switch._is_switching = True
        switch._pending_state = True
        switch._pending_until = datetime(2020, 1, 1, tzinfo=_UTC)  # past
        with patch(self._UTCNOW, return_value=datetime(2026, 1, 1, tzinfo=_UTC)):
            result = switch.is_on
        assert result is False
        assert switch._is_switching is False


# ---------------------------------------------------------------------------
# BoostChargeSwitch.async_turn_on / async_turn_off
# ---------------------------------------------------------------------------


class TestBoostChargeSwitchTurnOnOff:

    _UTCNOW = "custom_components.octopus_energy_it.switch.utcnow"
    _FIXED_NOW = datetime(2026, 3, 18, 12, 0, 0, tzinfo=_UTC)

    def _make(self, current_state="SMART_CONTROL_CAPABLE"):
        device = {
            "id": DEVICE_ID_1,
            "status": {"current": "LIVE", "currentState": current_state, "isSuspended": False},
        }
        coordinator = _make_coordinator({"devices": [device]})
        switch = _make_boost_switch(DEVICE_ID_1, coordinator=coordinator)
        switch.async_write_ha_state = MagicMock()
        switch.coordinator.async_request_refresh = AsyncMock()
        return switch

    @pytest.mark.asyncio
    async def test_turn_on_calls_boost_api(self):
        switch = self._make()
        switch._api.update_boost_charge = AsyncMock(return_value="ok")
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_on()
        switch._api.update_boost_charge.assert_awaited_once_with(DEVICE_ID_1, "BOOST")

    @pytest.mark.asyncio
    async def test_turn_on_requests_coordinator_refresh(self):
        switch = self._make()
        switch._api.update_boost_charge = AsyncMock(return_value="ok")
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_on()
        switch.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_on_api_returns_none_clears_pending(self):
        import sys
        ha_exc = sys.modules["homeassistant.exceptions"]
        switch = self._make()
        switch._api.update_boost_charge = AsyncMock(return_value=None)
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            with pytest.raises(ha_exc.HomeAssistantError):
                await switch.async_turn_on()
        assert switch._is_switching is False

    @pytest.mark.asyncio
    async def test_turn_on_api_exception_clears_pending(self):
        import sys
        ha_exc = sys.modules["homeassistant.exceptions"]
        switch = self._make()
        switch._api.update_boost_charge = AsyncMock(side_effect=RuntimeError("api down"))
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            with pytest.raises(ha_exc.HomeAssistantError):
                await switch.async_turn_on()
        assert switch._is_switching is False

    @pytest.mark.asyncio
    async def test_turn_off_calls_cancel_api(self):
        switch = self._make()
        switch._api.update_boost_charge = AsyncMock(return_value="ok")
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_off()
        switch._api.update_boost_charge.assert_awaited_once_with(DEVICE_ID_1, "CANCEL")

    @pytest.mark.asyncio
    async def test_turn_off_no_device_data_raises_no_error(self):
        """turn_off does not check device data before acting (unlike turn_on)."""
        coordinator = _make_coordinator({"devices": []})
        switch = _make_boost_switch(DEVICE_ID_1, coordinator=coordinator)
        switch.async_write_ha_state = MagicMock()
        switch.coordinator.async_request_refresh = AsyncMock()
        switch._api.update_boost_charge = AsyncMock(return_value="ok")
        with patch(self._UTCNOW, return_value=self._FIXED_NOW):
            await switch.async_turn_off()  # should not raise

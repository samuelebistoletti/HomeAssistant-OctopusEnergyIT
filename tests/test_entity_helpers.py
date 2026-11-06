"""Tests for the device capability and time-window helpers."""

from custom_components.octopus_energy_it.entity import (
    CAPABILITY_BOOST,
    CAPABILITY_SUSPEND,
    device_supports,
    device_time_window,
)

CAPS = [
    {"__typename": "FlexTriggerBoostChargeCapability"},
    {"__typename": "FlexUpdatePreferencesCapability"},
]


def test_listed_capability_is_supported():
    assert device_supports({"capabilities": CAPS}, CAPABILITY_BOOST) is True


def test_missing_capability_is_not_supported():
    assert device_supports({"capabilities": CAPS}, CAPABILITY_SUSPEND) is False


def test_unknown_capabilities_return_none():
    assert device_supports({}, CAPABILITY_BOOST) is None
    assert device_supports({"capabilities": None}, CAPABILITY_BOOST) is None


def test_time_window_from_schedule_settings():
    device = {
        "preferenceSetting": {
            "scheduleSettings": [{"timeFrom": "04:00:00", "timeTo": "11:00:00"}]
        }
    }
    assert device_time_window(device) == ("04:00", "11:00")


def test_time_window_defaults_without_settings():
    assert device_time_window({}) == ("04:00", "17:00")
    assert device_time_window(None) == ("04:00", "17:00")

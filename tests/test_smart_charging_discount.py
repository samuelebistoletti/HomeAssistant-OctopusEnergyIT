"""Tests for the Intelligent Octopus discount setting (issue #36)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.octopus_energy_it.coordinator import (
    OctopusEnergyITDataUpdateCoordinator,
)
from custom_components.octopus_energy_it.number import (
    OctopusSmartChargingDiscountNumber,
    async_setup_entry,
)


def _entry(options=None):
    return SimpleNamespace(
        options=options or {}, data={"account_numbers": ["A-1"]}, runtime_data=None
    )


def _coordinator(devices):
    return SimpleNamespace(data={"A-1": {"devices": devices}})


def _number(options=None):
    entry = _entry(options)
    number = OctopusSmartChargingDiscountNumber("A-1", _coordinator([]), entry)
    number.hass = SimpleNamespace(config_entries=MagicMock())
    number.async_write_ha_state = MagicMock()
    return number, entry


def test_default_discount_is_thirty_percent():
    number, _ = _number()
    assert number.native_value == 30.0
    assert number._attr_unique_id == "octopus_A-1_smart_charging_discount"


def test_discount_is_read_from_the_entry_options():
    number, _ = _number({"smart_charging_discount": 25})
    assert number.native_value == 25.0


async def test_setting_the_discount_updates_the_options():
    number, entry = _number({"other": "kept"})
    await number.async_set_native_value(20.0)

    number.hass.config_entries.async_update_entry.assert_called_once_with(
        entry, options={"other": "kept", "smart_charging_discount": 20}
    )
    number.async_write_ha_state.assert_called_once()


async def _setup(devices):
    entry = _entry()
    entry.runtime_data = SimpleNamespace(
        coordinator=_coordinator(devices), api=MagicMock(), account_number="A-1"
    )
    added = []
    await async_setup_entry(None, entry, added.extend)
    return [e for e in added if isinstance(e, OctopusSmartChargingDiscountNumber)]


async def test_discount_entity_only_with_an_ev_or_charger():
    assert len(await _setup([{"id": "c", "deviceType": "CHARGE_POINTS"}])) == 1
    assert await _setup([{"id": "h", "deviceType": "HEAT_PUMPS"}]) == []
    assert await _setup([]) == []


def test_coordinator_reads_the_discount_from_the_options():
    discount = OctopusEnergyITDataUpdateCoordinator.smart_charging_discount.fget
    assert discount(SimpleNamespace(config_entry=_entry())) == 30.0
    assert (
        discount(SimpleNamespace(config_entry=_entry({"smart_charging_discount": 15})))
        == 15.0
    )
    assert discount(SimpleNamespace(config_entry=None)) == 30.0

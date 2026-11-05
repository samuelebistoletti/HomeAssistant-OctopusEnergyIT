"""Check every sensor's device class, unit and state class against HA rules.

The allowed combinations below are copied from Home Assistant 2026.11
(``homeassistant.components.sensor.const``: ``DEVICE_CLASS_UNITS`` and
``DEVICE_CLASS_STATE_CLASSES``). Home Assistant logs a warning, and the
Energy dashboard may reject the entity, when a sensor breaks them.
"""

import inspect

import pytest

from custom_components.octopus_energy_it import sensor as sensor_mod

_ENERGY_UNITS = {"Wh", "kWh", "MWh", "GWh", "TWh", "J", "kJ", "MJ", "GJ"}
_RULES = {
    # device class: (allowed units or None for any, allowed state classes)
    "monetary": (None, {None, "total"}),
    "energy": (_ENERGY_UNITS, {None, "total", "total_increasing"}),
    "energy_storage": (_ENERGY_UNITS, {None, "measurement"}),
    "gas": ({"m³", "L", "ft³", "CCF", "MCF"}, {None, "total", "total_increasing"}),
    "duration": (
        {"d", "h", "min", "s", "ms"},
        {None, "measurement", "total", "total_increasing"},
    ),
    "timestamp": (None, {None}),
}

_SENSOR_CLASSES = [
    cls
    for _name, cls in inspect.getmembers(sensor_mod, inspect.isclass)
    if cls.__module__ == sensor_mod.__name__ and issubclass(cls, sensor_mod.SensorEntity)
]


def test_sensor_classes_found():
    assert len(_SENSOR_CLASSES) > 20


@pytest.mark.parametrize("cls", _SENSOR_CLASSES, ids=lambda cls: cls.__name__)
def test_device_class_unit_and_state_class_are_valid(cls):
    device_class = getattr(cls, "_attr_device_class", None)
    if device_class is None:
        return
    assert device_class in _RULES, f"add HA rules for {device_class!r}"
    units, state_classes = _RULES[device_class]

    unit = cls.__dict__.get("_attr_native_unit_of_measurement")
    if unit is None:
        unit = getattr(cls, "_attr_native_unit_of_measurement", None)
    if units is not None and isinstance(unit, str):
        assert unit in units, f"{unit!r} is not valid for {device_class}"

    assert getattr(cls, "_attr_state_class", None) in state_classes

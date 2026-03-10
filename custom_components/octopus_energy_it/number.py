"""Number entities per Octopus Energy Italy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    OctopusCoordinatorEntity,
    OctopusDeviceScheduleMixin,
    first_device_schedule,
    get_account_data,
    resolve_account_numbers,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Configura le entità number."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    account_numbers = resolve_account_numbers(
        entry, coordinator, data.get("account_number")
    )

    entities: list[OctopusDeviceChargeTargetNumber] = []

    for account_number in account_numbers:
        account_data = get_account_data(coordinator, account_number)
        if not account_data:
            continue

        devices = account_data.get("devices") or []
        if not isinstance(devices, list):
            continue

        for device in devices:
            if not isinstance(device, dict):
                continue
            device_id = device.get("id")
            schedule = first_device_schedule(device)
            if not device_id or not schedule:
                continue

            entities.append(
                OctopusDeviceChargeTargetNumber(
                    account_number=account_number,
                    device_id=device_id,
                    coordinator=coordinator,
                    api=api,
                )
            )

    if entities:
        async_add_entities(entities)


class OctopusDeviceChargeTargetNumber(
    OctopusDeviceScheduleMixin, OctopusCoordinatorEntity, NumberEntity
):
    """Numero per modificare la percentuale di carica SmartFlex."""

    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_registry_enabled_default = True
    _attr_translation_key = "ev_charge_target_number"
    _attr_icon = "mdi:target"

    def __init__(self, account_number: str, device_id: str, coordinator, api) -> None:
        super().__init__(account_number, coordinator)
        self._device_id = device_id
        self._api = api

        self._attr_unique_id = f"octopus_{account_number}_{device_id}_charge_target"

    def _parse_float(self, value: Any, default: float) -> float:
        try:
            if value is None:
                return default
            return float(str(value))
        except (TypeError, ValueError):
            return default

    @property
    def translation_placeholders(self) -> dict[str, str]:
        placeholders = super().translation_placeholders
        device = self._current_device()
        placeholders["device"] = (device or {}).get("name") or self._device_id
        return placeholders

    # NumberEntity API ----------------------------------------------------
    @property
    def native_value(self) -> float | None:
        return self._current_target_percentage()

    @property
    def native_min_value(self) -> float:
        setting = self._schedule_setting()
        if setting:
            return self._parse_float(setting.get("min"), 10)
        return 10

    @property
    def native_max_value(self) -> float:
        setting = self._schedule_setting()
        if setting:
            return self._parse_float(setting.get("max"), 100)
        return 100

    @property
    def native_step(self) -> float:
        setting = self._schedule_setting()
        if setting:
            step = self._parse_float(setting.get("step"), 1)
            return step if step > 0 else 1
        return 1

    async def async_set_native_value(self, value: float) -> None:
        target_time = self._current_target_time()
        if not target_time:
            setting = self._schedule_setting()
            target_time = (
                str(setting.get("timeFrom", "06:00"))[:5] if setting else "06:00"
            )

        step = self.native_step or 1
        target_percentage = int(round(value / step) * step)

        min_value = int(self.native_min_value)
        max_value = int(self.native_max_value)
        if min_value > max_value:
            min_value, max_value = max_value, min_value
        target_percentage = max(min_value, min(max_value, target_percentage))

        success = await self._api.set_device_preferences(
            self._device_id,
            target_percentage,
            target_time,
        )
        if not success:
            raise HomeAssistantError("Impossibile aggiornare il target di carica")

        self._update_local_schedule(
            target_percentage=target_percentage, target_time=f"{target_time}:00"
        )
        await self.coordinator.async_request_refresh()

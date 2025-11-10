"""Number entities per Octopus Energy Italy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
from .entity import OctopusCoordinatorEntity


def _get_account_data(coordinator, account_number: str) -> dict[str, Any] | None:
    """Recupera i dati dell'account dal coordinatore condiviso."""
    data = getattr(coordinator, "data", None)
    if isinstance(data, dict):
        account_data = data.get(account_number)
        if isinstance(account_data, dict):
            return account_data
    return None


def _first_device_schedule(device: dict[str, Any]) -> dict[str, Any] | None:
    preferences = device.get("preferences") or {}
    if not isinstance(preferences, dict):
        return None
    schedules = preferences.get("schedules") or []
    if not isinstance(schedules, list):
        return None
    for entry in schedules:
        if isinstance(entry, dict):
            return entry
    return None


def _schedule_setting(device: dict[str, Any]) -> dict[str, Any] | None:
    pref_setting = device.get("preferenceSetting") or {}
    if not isinstance(pref_setting, dict):
        return None
    settings = pref_setting.get("scheduleSettings") or []
    if not isinstance(settings, list):
        return None
    for entry in settings:
        if isinstance(entry, dict):
            return entry
    return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Configura le entità number."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    account_numbers = data.get("account_numbers") or []
    if not account_numbers:
        primary = data.get("account_number")
        if primary:
            account_numbers = [primary]

    entities: list[OctopusDeviceChargeTargetNumber] = []

    for account_number in account_numbers:
        account_data = _get_account_data(coordinator, account_number)
        if not account_data:
            continue

        devices = account_data.get("devices") or []
        if not isinstance(devices, list):
            continue

        for device in devices:
            if not isinstance(device, dict):
                continue
            device_id = device.get("id")
            schedule = _first_device_schedule(device)
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


class OctopusDeviceChargeTargetNumber(OctopusCoordinatorEntity, NumberEntity):
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

    # Helpers --------------------------------------------------------------
    def _current_device(self) -> dict[str, Any] | None:
        account = _get_account_data(self.coordinator, self._account_number)
        if not account:
            return None
        devices = account.get("devices") or []
        if not isinstance(devices, list):
            return None
        for device in devices:
            if isinstance(device, dict) and device.get("id") == self._device_id:
                return device
        return None

    def _current_schedule(self) -> dict[str, Any] | None:
        device = self._current_device()
        if not device:
            return None
        return _first_device_schedule(device)

    def _schedule_setting(self) -> dict[str, Any] | None:
        device = self._current_device()
        if not device:
            return None
        return _schedule_setting(device)

    def _parse_float(self, value: Any, default: float) -> float:
        try:
            if value is None:
                return default
            return float(str(value))
        except (TypeError, ValueError):
            return default

    def _current_target_time(self) -> str | None:
        schedule = self._current_schedule()
        if not schedule:
            return None
        time_value = schedule.get("time")
        if not time_value:
            return None
        return str(time_value)[:5]

    def _current_target_percentage(self) -> int | None:
        schedule = self._current_schedule()
        if not schedule:
            return None
        value = schedule.get("max")
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _update_local_schedule(
        self, *, target_percentage: int | None = None, target_time: str | None = None
    ) -> None:
        account = _get_account_data(self.coordinator, self._account_number)
        if not account:
            return
        devices = account.get("devices") or []
        if not isinstance(devices, list):
            return
        for device in devices:
            if not isinstance(device, dict) or device.get("id") != self._device_id:
                continue
            preferences = device.setdefault("preferences", {})
            if not isinstance(preferences, dict):
                preferences = {}
                device["preferences"] = preferences
            schedules = preferences.setdefault("schedules", [])
            if not isinstance(schedules, list) or not schedules:
                break
            schedule = schedules[0]
            if not isinstance(schedule, dict):
                break
            if target_percentage is not None:
                schedule["max"] = target_percentage
            if target_time is not None:
                stored_time = (
                    target_time if len(target_time) > 5 else f"{target_time}:00"
                )
                schedule["time"] = stored_time
            break
        self.coordinator.async_set_updated_data(dict(self.coordinator.data))

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
            return self._parse_float(setting.get("min"), 20)
        return 20

    @property
    def native_max_value(self) -> float:
        setting = self._schedule_setting()
        if setting:
            return self._parse_float(setting.get("max"), 100)
        return 100

    @property
    def native_step(self) -> float:
        return 5

    async def async_set_native_value(self, value: float) -> None:
        target_time = self._current_target_time()
        if not target_time:
            setting = self._schedule_setting()
            target_time = (
                str(setting.get("timeFrom", "06:00"))[:5] if setting else "06:00"
            )

        step = self.native_step or 5
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

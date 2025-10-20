"""Select entities per Octopus Energy Italy."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def _get_account_data(coordinator, account_number: str) -> dict[str, Any] | None:
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


def _build_time_options(setting: dict[str, Any] | None) -> list[str]:
    if not setting:
        return []

    time_from = str(setting.get("timeFrom", "04:00"))[:5]
    time_to = str(setting.get("timeTo", "17:00"))[:5]
    step_minutes = setting.get("timeStep")
    try:
        step = int(step_minutes) if step_minutes is not None else 30
    except (TypeError, ValueError):
        step = 30
    if step <= 0:
        step = 30

    try:
        start_dt = datetime.strptime(time_from, "%H:%M")
        end_dt = datetime.strptime(time_to, "%H:%M")
    except ValueError:
        return []

    options: list[str] = []
    current = start_dt
    while current <= end_dt:
        options.append(current.strftime("%H:%M"))
        current += timedelta(minutes=step)
    return options


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Configura le entità select."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    account_numbers = data.get("account_numbers") or []
    if not account_numbers:
        primary = data.get("account_number")
        if primary:
            account_numbers = [primary]

    entities: list[OctopusDeviceTargetTimeSelect] = []

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
                OctopusDeviceTargetTimeSelect(
                    account_number=account_number,
                    device_id=device_id,
                    coordinator=coordinator,
                    api=api,
                )
            )

    if entities:
        async_add_entities(entities)


class OctopusDeviceTargetTimeSelect(CoordinatorEntity, SelectEntity):
    """Select per impostare l'orario di completamento SmartFlex."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, account_number: str, device_id: str, coordinator, api) -> None:
        super().__init__(coordinator)
        self._account_number = account_number
        self._device_id = device_id
        self._api = api

        self._attr_name = f"Octopus {account_number} EV Ready Time"
        self._attr_unique_id = (
            f"octopus_{account_number}_{device_id}_target_time_select"
        )
        self._attr_has_entity_name = False

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

    def _current_time(self) -> str | None:
        schedule = self._current_schedule()
        if not schedule:
            return None
        time_val = schedule.get("time")
        if not time_val:
            return None
        return str(time_val)[:5]

    def _update_local_schedule(self, *, target_time: str | None = None) -> None:
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
            if not isinstance(schedules, list) or not schedules or target_time is None:
                break
            schedule = schedules[0]
            if not isinstance(schedule, dict):
                break
            stored_time = target_time if len(target_time) > 5 else f"{target_time}:00"
            schedule["time"] = stored_time
            break
        self.coordinator.async_set_updated_data(dict(self.coordinator.data))

    # SelectEntity API ----------------------------------------------------
    @property
    def options(self) -> list[str]:
        device = self._current_device()
        return _build_time_options(_schedule_setting(device) if device else None)

    @property
    def current_option(self) -> str | None:
        return self._current_time()

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise HomeAssistantError("Orario non valido per il dispositivo")

        percentage = self._current_target_percentage()
        if percentage is None:
            percentage = 80

        success = await self._api.set_device_preferences(
            self._device_id,
            int(percentage),
            option,
        )
        if not success:
            raise HomeAssistantError("Impossibile aggiornare l'orario di ricarica")

        self._update_local_schedule(target_time=f"{option}:00")
        await self.coordinator.async_request_refresh()

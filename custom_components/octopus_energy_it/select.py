"""Select entities per Octopus Energy Italy."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    OctopusCoordinatorEntity,
    OctopusDeviceScheduleMixin,
    device_schedule_setting,
    first_device_schedule,
    get_account_data,
    resolve_account_numbers,
)


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

    account_numbers = resolve_account_numbers(
        entry, coordinator, data.get("account_number")
    )

    entities: list[OctopusDeviceTargetTimeSelect] = []

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
                OctopusDeviceTargetTimeSelect(
                    account_number=account_number,
                    device_id=device_id,
                    coordinator=coordinator,
                    api=api,
                )
            )

    if entities:
        async_add_entities(entities)


class OctopusDeviceTargetTimeSelect(
    OctopusDeviceScheduleMixin, OctopusCoordinatorEntity, SelectEntity
):
    """Select per impostare l'orario di completamento SmartFlex."""

    _attr_entity_registry_enabled_default = True
    _attr_translation_key = "ev_ready_time_select"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, account_number: str, device_id: str, coordinator, api) -> None:
        super().__init__(account_number, coordinator)
        self._device_id = device_id
        self._api = api

        self._attr_unique_id = (
            f"octopus_{account_number}_{device_id}_target_time_select"
        )

    @property
    def translation_placeholders(self) -> dict[str, str]:
        placeholders = super().translation_placeholders
        device = self._current_device()
        placeholders["device"] = (device or {}).get("name") or self._device_id
        return placeholders

    # SelectEntity API ----------------------------------------------------
    @property
    def options(self) -> list[str]:
        device = self._current_device()
        return _build_time_options(device_schedule_setting(device) if device else None)

    @property
    def current_option(self) -> str | None:
        return self._current_target_time()

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

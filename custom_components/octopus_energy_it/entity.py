"""Shared helpers for Octopus Energy Italy entities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


# ---------------------------------------------------------------------------
# Shared data-access helpers (used by number.py, select.py, …)
# ---------------------------------------------------------------------------


def get_account_data(coordinator, account_number: str) -> dict[str, Any] | None:
    """Return the account dict for *account_number* from coordinator data."""
    data = getattr(coordinator, "data", None)
    if isinstance(data, dict):
        account_data = data.get(account_number)
        if isinstance(account_data, dict):
            return account_data
    return None


def first_device_schedule(device: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first schedule entry from device preferences, or None."""
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


def device_schedule_setting(device: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first scheduleSettings entry from preferenceSetting, or None."""
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


def resolve_account_numbers(
    entry: ConfigEntry,
    coordinator,
    primary_account_number: str | None = None,
) -> list[str]:
    """
    Return the list of account numbers for this config entry.

    Falls back progressively:
    1. ``entry.data["account_numbers"]``
    2. ``primary_account_number`` (single-account legacy path)
    3. All keys present in ``coordinator.data``
    """
    account_numbers: list[str] = list(entry.data.get("account_numbers") or [])
    if not account_numbers and primary_account_number:
        account_numbers = [primary_account_number]
    if not account_numbers and coordinator.data:
        account_numbers = list(coordinator.data.keys())
    return account_numbers


class OctopusEntityMixin:
    """Mixin that configures shared attributes for Octopus entities."""

    _attr_has_entity_name = True

    def __init__(self, account_number: str) -> None:
        self._account_number = account_number
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_number)},
            manufacturer="Octopus Energy Italy",
            model="Kraken",
            name=f"{account_number}",
        )

    @property
    def translation_placeholders(self) -> dict[str, str]:
        """Expose placeholders for translated strings."""
        return {"account": self._account_number}


class OctopusCoordinatorEntity(OctopusEntityMixin, CoordinatorEntity):
    """Base entity for coordinator-backed Octopus entities."""

    def __init__(self, account_number: str, coordinator) -> None:
        OctopusEntityMixin.__init__(self, account_number)
        CoordinatorEntity.__init__(self, coordinator)


class OctopusDeviceScheduleMixin:
    """Mixin providing shared device-schedule helpers for number/select entities."""

    _device_id: str
    _account_number: str

    def _current_device(self) -> dict[str, Any] | None:
        account = get_account_data(self.coordinator, self._account_number)
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
        return first_device_schedule(device)

    def _schedule_setting(self) -> dict[str, Any] | None:
        device = self._current_device()
        if not device:
            return None
        return device_schedule_setting(device)

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

    def _current_target_time(self) -> str | None:
        schedule = self._current_schedule()
        if not schedule:
            return None
        time_value = schedule.get("time")
        if not time_value:
            return None
        return str(time_value)[:5]

    def _update_local_schedule(
        self, *, target_percentage: int | None = None, target_time: str | None = None
    ) -> None:
        account = get_account_data(self.coordinator, self._account_number)
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


class OctopusPublicProductsEntity(CoordinatorEntity):
    """Entity representing public products not tied to a specific account."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, *, device_identifier: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            manufacturer="Octopus Energy Italy",
            name="Octopus Energy Public Tariffs",
            model="Octopus Energy Public Tariffs",
        )

"""Service actions of the Octopus Energy Italy integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import DOMAIN
from .entity import device_time_window

if TYPE_CHECKING:
    from .coordinator import OctopusEnergyITRuntimeData

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_DEVICE_PREFERENCES = "set_device_preferences"
ATTR_DEVICE_ID = "device_id"
ATTR_TARGET_PERCENTAGE = "target_percentage"
ATTR_TARGET_TIME = "target_time"

SERVICE_BOOST_CHARGE = "boost_charge"
ATTR_END_TIME = "end_time"

BOOST_CHARGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_TARGET_PERCENTAGE): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=100)
        ),
        vol.Optional(ATTR_END_TIME): cv.datetime,
    }
)

SET_DEVICE_PREFERENCES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_TARGET_PERCENTAGE): vol.Coerce(float),
        vol.Required(ATTR_TARGET_TIME): cv.string,
    }
)


def _find_device_owner(
    hass: HomeAssistant, device_id: str
) -> tuple[OctopusEnergyITRuntimeData, dict] | tuple[None, None]:
    """Return the runtime data and device dict of the entry owning *device_id*."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime = entry.runtime_data
        for account in (runtime.coordinator.data or {}).values():
            for device in account.get("devices") or []:
                if device.get("id") == device_id:
                    return runtime, device
    return None, None


async def _async_set_device_preferences(call: ServiceCall) -> None:
    """Set the SmartFlex charge target and ready-by time of a device."""
    hass = call.hass
    device_id: str = call.data[ATTR_DEVICE_ID]
    # Kraken accepts whole percentages between 10 and 100.
    target_percentage = max(10, min(100, round(call.data[ATTR_TARGET_PERCENTAGE])))
    target_time: str = call.data[ATTR_TARGET_TIME]

    runtime, device = _find_device_owner(hass, device_id)
    if runtime is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )

    try:
        formatted_time = runtime.api.format_time_to_hh_mm(target_time)
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_target_time",
            translation_placeholders={
                "time": str(target_time),
                "start": "04:00",
                "end": "17:00",
            },
        ) from err
    window = device_time_window(device)
    if not window[0] <= formatted_time <= window[1]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_target_time",
            translation_placeholders={
                "time": formatted_time,
                "start": window[0],
                "end": window[1],
            },
        )

    if not await runtime.api.set_device_preferences(
        device_id, target_percentage, formatted_time, time_window=window
    ):
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="set_preferences_failed"
        )

    _LOGGER.debug(
        "Set preferences of %s: %s%% by %s",
        device_id,
        target_percentage,
        formatted_time,
    )
    await runtime.coordinator.async_request_refresh()


async def _async_boost_charge(call: ServiceCall) -> None:
    """Start a boost charge, optionally up to a target or until a time."""
    device_id: str = call.data[ATTR_DEVICE_ID]
    runtime, _device = _find_device_owner(call.hass, device_id)
    if runtime is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )
    end_time = call.data.get(ATTR_END_TIME)
    if end_time is not None:
        end_time = dt_util.as_utc(end_time)
        if end_time <= dt_util.utcnow():
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="boost_end_in_past"
            )
    if not await runtime.api.update_boost_charge(
        device_id,
        "BOOST",
        target_percentage=call.data.get(ATTR_TARGET_PERCENTAGE),
        end_time=end_time,
    ):
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="boost_charge_failed"
        )
    await runtime.coordinator.async_request_refresh()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEVICE_PREFERENCES,
        _async_set_device_preferences,
        schema=SET_DEVICE_PREFERENCES_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOST_CHARGE,
        _async_boost_charge,
        schema=BOOST_CHARGE_SCHEMA,
    )

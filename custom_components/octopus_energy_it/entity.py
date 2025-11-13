"""Shared helpers for Octopus Energy Italy entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


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

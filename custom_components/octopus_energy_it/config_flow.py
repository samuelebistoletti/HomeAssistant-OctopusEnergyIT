"""Config flow for Octopus Energy Italy integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .octopus_energy_it import (
    OctopusEnergyIT,
    OctopusEnergyITAuthError,
    OctopusEnergyITConnectionError,
)

_LOGGER = logging.getLogger(__name__)

_CREDENTIALS_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)


async def validate_credentials(
    hass: HomeAssistant, email: str, password: str
) -> tuple[bool, str | None, dict | None]:
    """Validate the credentials; return ``(valid, error_key, first_account)``."""
    octopus_api = OctopusEnergyIT(email, password, async_get_clientsession(hass))
    try:
        await octopus_api.authenticate()
        accounts = await octopus_api.fetch_accounts_with_initial_data()
    except OctopusEnergyITAuthError:
        return False, "invalid_auth", None
    except OctopusEnergyITConnectionError:
        return False, "cannot_connect", None
    except Exception:
        _LOGGER.exception("Unexpected error while validating credentials")
        return False, "unknown", None

    if not accounts:
        return False, "no_accounts", None
    return True, None, accounts[0]


def _unique_id(email: str) -> str:
    """Return the config entry unique ID for an Octopus login."""
    return email.strip().lower()


class OctopusEnergyITConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Octopus Energy Italy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(_unique_id(email))
            self._abort_if_unique_id_configured()

            valid, error, account_data = await validate_credentials(
                self.hass, email, user_input[CONF_PASSWORD]
            )
            if valid:
                return self.async_create_entry(
                    title=f"Octopus Energy Italy ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        "account_data": account_data,
                    },
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="user", data_schema=_CREDENTIALS_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start reauthentication after the API rejected the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for the new password of the configured account."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        email = entry.data[CONF_EMAIL]

        if user_input is not None:
            valid, error, _account = await validate_credentials(
                self.hass, email, user_input[CONF_PASSWORD]
            )
            if valid:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    reason="reauth_successful",
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": email},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change the credentials of an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        current_email = entry.data.get(CONF_EMAIL, "")

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(_unique_id(email))
            # Entries created before unique IDs existed have none: allow them
            # to switch login; otherwise the email must stay the same account.
            if entry.unique_id is not None:
                self._abort_if_unique_id_mismatch(reason="wrong_account")

            valid, error, account_data = await validate_credentials(
                self.hass, email, user_input[CONF_PASSWORD]
            )
            if valid:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        "account_data": account_data,
                    },
                    title=f"Octopus Energy Italy ({email})",
                    reason="reconfigure_successful",
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"current_email": current_email},
        )

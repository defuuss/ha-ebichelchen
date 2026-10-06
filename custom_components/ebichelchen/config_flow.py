"""UI login, authorized student selection, reauthentication and polling options."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import create_client
from .api import (
    AccessDenied,
    CannotConnect,
    EbichelchenError,
    InvalidAuth,
    UnsupportedAuth,
    UnsupportedRole,
)
from .const import CONF_REFRESH, CONF_STUDENTS, DEFAULT_REFRESH, DOMAIN


def credentials_schema(username: str = "", reauth: bool = False):
    fields = {
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
    if not reauth:
        fields = {vol.Required(CONF_USERNAME, default=username): str, **fields}
    return vol.Schema(fields)


def error_key(err: EbichelchenError) -> str:
    if isinstance(err, UnsupportedAuth):
        return "unsupported_auth"
    if isinstance(err, InvalidAuth):
        return "invalid_auth"
    if isinstance(err, CannotConnect):
        return "cannot_connect"
    if isinstance(err, UnsupportedRole):
        return "unsupported_role"
    if isinstance(err, AccessDenied):
        return "access_denied"
    return "invalid_response"


async def validate_credentials(username, password):
    session, client = create_client(username, password)
    try:
        return await client.account()
    finally:
        await session.close()


class EbichelchenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an IAM account without copying cookies or writing YAML."""

    VERSION = 1

    def __init__(self):
        self._credentials = {}
        self._students = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            if not username or not user_input[CONF_PASSWORD]:
                errors["base"] = "invalid_auth"
            else:
                try:
                    account_id, self._students = await validate_credentials(
                        username, user_input[CONF_PASSWORD]
                    )
                except EbichelchenError as err:
                    errors["base"] = error_key(err)
                else:
                    await self.async_set_unique_id(account_id)
                    self._abort_if_unique_id_configured()
                    if not self._students:
                        return self.async_abort(reason="no_students")
                    self._credentials = {
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    return await self.async_step_students()
        return self.async_show_form(
            step_id="user",
            data_schema=credentials_schema((user_input or {}).get(CONF_USERNAME, "")),
            errors=errors,
        )

    async def async_step_students(self, user_input=None):
        errors = {}
        if user_input is not None:
            chosen = user_input[CONF_STUDENTS]
            if not chosen or any(student not in self._students for student in chosen):
                errors["base"] = "select_students"
            else:
                return self.async_create_entry(
                    title="eBichelchen",
                    data={
                        **self._credentials,
                        CONF_STUDENTS: {s: self._students[s] for s in chosen},
                    },
                    options={CONF_REFRESH: user_input[CONF_REFRESH]},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_STUDENTS, default=list(self._students)): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": s, "label": name} for s, name in self._students.items()],
                        multiple=True,
                    )
                ),
                vol.Required(CONF_REFRESH, default=DEFAULT_REFRESH): vol.All(
                    vol.Coerce(int), vol.Range(min=15, max=1440)
                ),
            }
        )
        return self.async_show_form(step_id="students", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            try:
                account_id, students = await validate_credentials(
                    entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except EbichelchenError as err:
                errors["base"] = error_key(err)
            else:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_mismatch()
                if any(s not in students for s in entry.data[CONF_STUDENTS]):
                    errors["base"] = "access_denied"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                    )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=credentials_schema(reauth=True), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EbichelchenOptionsFlow()


class EbichelchenOptionsFlow(config_entries.OptionsFlow):
    """Expose the refresh interval in the integration's Configure dialog."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFRESH,
                        default=self.config_entry.options.get(CONF_REFRESH, DEFAULT_REFRESH),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440))
                }
            ),
        )

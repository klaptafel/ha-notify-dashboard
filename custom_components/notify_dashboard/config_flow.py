"""Config flow for Notify Dashboard.

Only handles the integration config (mirror_dismiss_to) via the UI. The
`notify.dashboard` service itself keeps running through YAML (`notify: -
platform: notify_dashboard`) — that's a limitation of the legacy notify
platform itself, not something a config entry can fix (see design doc
section 1.1 / the HA architecture discussion #1041 about it).
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_MIRROR_DISMISS_TO, DOMAIN, NOTIFY_ENTITY_DOMAIN


def _mirror_dismiss_schema(default: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_MIRROR_DISMISS_TO, default=default): selector.selector(
                {"entity": {"multiple": True, "filter": {"domain": NOTIFY_ENTITY_DOMAIN}}}
            )
        }
    )


class NotifyDashboardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Notify Dashboard."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "NotifyDashboardOptionsFlow":
        return NotifyDashboardOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        # One instance is enough — multiple config entries wouldn't add anything.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Notify Dashboard", data={}, options=user_input)

        return self.async_show_form(step_id="user", data_schema=_mirror_dismiss_schema([]))


class NotifyDashboardOptionsFlow(config_entries.OptionsFlow):
    """Lets mirror_dismiss_to be changed later via 'Configure'.

    Note: no own __init__ that sets self.config_entry — recent HA versions
    make that a read-only property that the config_entries module already
    populates before async_step_init is called. Assigning it yourself raises
    'property has no setter'.
    """

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_MIRROR_DISMISS_TO, [])
        return self.async_show_form(step_id="init", data_schema=_mirror_dismiss_schema(current))

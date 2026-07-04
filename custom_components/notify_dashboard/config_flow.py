"""Config flow for Notify Dashboard.

Regelt alleen de integratie-config (mirror_dismiss_to) via de UI. De
`notify.dashboard`-service zelf blijft via YAML lopen (`notify: - platform:
notify_dashboard`) — dat is een beperking van het legacy notify-platform
zelf, niet iets wat via een config entry op te lossen is (zie ontwerpdocument
sectie 1.1 / de HA architecture-discussie #1041 daarover).
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
        # Eén instantie is genoeg — meerdere config entries voegen niets toe.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Notify Dashboard", data={}, options=user_input)

        return self.async_show_form(step_id="user", data_schema=_mirror_dismiss_schema([]))


class NotifyDashboardOptionsFlow(config_entries.OptionsFlow):
    """Laat mirror_dismiss_to later aanpassen via 'Configureren'.

    Let op: geen eigen __init__ die self.config_entry zet — recente HA-versies
    maken dat een read-only property die de config_entries-module zelf al
    invult vóór async_step_init wordt aangeroepen. Zelf toewijzen geeft
    'property has no setter'.
    """

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_MIRROR_DISMISS_TO, [])
        return self.async_show_form(step_id="init", data_schema=_mirror_dismiss_schema(current))

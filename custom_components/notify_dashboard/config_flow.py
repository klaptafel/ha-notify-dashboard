"""Config flow for Notify Dashboard.

Only handles the integration config (mirror_dismiss_to) via the UI. The
`notify.dashboard` service itself keeps running through YAML (`notify: -
platform: notify_dashboard`) — that's a limitation of the legacy notify
platform itself, not something a config entry can fix: legacy notify
services are set up via async_setup_platform straight from YAML, entirely
outside the config-entry lifecycle, so a config entry has nothing to hook
into to replace that registration. See notify.py's docstring and
home-assistant/architecture discussion #1041 for why the config-entry-
friendly replacement (NotifyEntity) exists but isn't usable here.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_MIRROR_DISMISS_TO,
    DOMAIN,
    NOTIFY_ENTITY_DOMAIN,
    RESERVED_NOTIFY_SERVICES,
    validate_mirror_target,
)


def _mirror_dismiss_options(hass: HomeAssistant) -> list[dict[str, str]]:
    """List every valid mirror_dismiss_to target: both notify *entities*
    (modern NotifyEntity-based integrations, dispatched via the generic
    notify.send_message action) and legacy notify *services* — a service
    registered directly under the notify domain, with no entity at all, the
    only way a YAML-defined `notify: - platform: group` (or any other
    BaseNotificationService-based integration, including this one) can be
    reached. An entity selector alone can never show the latter — they
    aren't entities, so they'd never appear there regardless of anything
    else (confirmed: this isn't fixed by restarting HA either).

    Entity ids always contain a dot (`notify.xxx`); legacy service names
    never do (`xxx`) — is_mirror_entity in const.py is the shared rule
    __init__.py's dispatch later uses to tell them apart.
    """
    entity_options = [
        {"value": entity_id, "label": entity_id}
        for entity_id in sorted(hass.states.async_entity_ids(NOTIFY_ENTITY_DOMAIN))
    ]
    service_options = [
        {"value": service, "label": f"{service} (notify group/service)"}
        for service in sorted(hass.services.async_services().get(NOTIFY_ENTITY_DOMAIN, {}))
        if service not in RESERVED_NOTIFY_SERVICES
    ]
    return entity_options + service_options


def _mirror_dismiss_schema(hass: HomeAssistant, default: list[str]) -> vol.Schema:
    # Deliberately just the selector, no vol.All(..., [validate_mirror_target])
    # wrapping — that shape validates fine on submit, but HA's
    # voluptuous_serialize.convert() (used to send the form itself to the
    # frontend on every render, not just on submit) has no case for a bare
    # list-of-callables and raises "Unable to convert schema" for it,
    # breaking the flow with a 500 before a user can even see the form.
    # validate_mirror_target instead runs by hand in the step methods below.
    return vol.Schema(
        {
            vol.Optional(CONF_MIRROR_DISMISS_TO, default=default): selector.selector(
                {
                    "select": {
                        "options": _mirror_dismiss_options(hass),
                        "multiple": True,
                        "custom_value": True,
                        "mode": "dropdown",
                    }
                }
            )
        }
    )


def _invalid_mirror_targets(values: list[str]) -> bool:
    """True if any entry fails validate_mirror_target.

    custom_value on the selector above lets a user type something not in
    the dropdown (e.g. a target that isn't set up yet) — but the selector
    itself validates nothing about *what* was typed, so this still needs to
    run by hand on submit, same rules as the YAML path in __init__.py's
    CONFIG_SCHEMA (confirmed empirically: the select selector passes
    arbitrary strings through unchanged).
    """
    for value in values:
        try:
            validate_mirror_target(value)
        except vol.Invalid:
            return True
    return False


class NotifyDashboardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Notify Dashboard."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "NotifyDashboardOptionsFlow":
        return NotifyDashboardOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # One instance is enough — multiple config entries wouldn't add anything.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            if _invalid_mirror_targets(user_input.get(CONF_MIRROR_DISMISS_TO, [])):
                errors["base"] = "invalid_mirror_target"
            else:
                return self.async_create_entry(title="Notify Dashboard", data={}, options=user_input)

        default = user_input.get(CONF_MIRROR_DISMISS_TO, []) if user_input else []
        return self.async_show_form(
            step_id="user", data_schema=_mirror_dismiss_schema(self.hass, default), errors=errors
        )


class NotifyDashboardOptionsFlow(config_entries.OptionsFlow):
    """Lets mirror_dismiss_to be changed later via 'Configure'.

    Note: no own __init__ that sets self.config_entry — recent HA versions
    make that a read-only property that the config_entries module already
    populates before async_step_init is called. Assigning it yourself raises
    'property has no setter'.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if _invalid_mirror_targets(user_input.get(CONF_MIRROR_DISMISS_TO, [])):
                errors["base"] = "invalid_mirror_target"
            else:
                return self.async_create_entry(title="", data=user_input)

        current = (
            user_input.get(CONF_MIRROR_DISMISS_TO, [])
            if user_input
            else self.config_entry.options.get(CONF_MIRROR_DISMISS_TO, [])
        )
        return self.async_show_form(
            step_id="init", data_schema=_mirror_dismiss_schema(self.hass, current), errors=errors
        )

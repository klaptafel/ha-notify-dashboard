"""Tests for the config and options flows.

Instantiates the flow classes directly instead of going through
hass.config_entries.flow.async_init()/options.async_init(): those go
through the full flow manager, which first ensures the domain's component
(and its manifest dependencies, here http + frontend) is set up. frontend
needs the separate hass_frontend package, which isn't installable in this
environment (see conftest.py's hass_http/frontend_extra_js_urls docstrings
for the same root cause). None of that setup is relevant to what these
flows actually do, so bypassing it is a faithful, narrower unit test.
"""
from __future__ import annotations

import voluptuous_serialize
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.notify_dashboard.config_flow import (
    NotifyDashboardConfigFlow,
    NotifyDashboardOptionsFlow,
    _invalid_mirror_targets,
    _mirror_dismiss_options,
    _mirror_dismiss_schema,
)
from custom_components.notify_dashboard.const import CONF_MIRROR_DISMISS_TO, DOMAIN


def _make_config_flow(hass) -> NotifyDashboardConfigFlow:
    flow = NotifyDashboardConfigFlow()
    flow.hass = hass
    return flow


def _make_options_flow(hass, entry: MockConfigEntry) -> NotifyDashboardOptionsFlow:
    flow = NotifyDashboardOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    return flow


def test_async_get_options_flow_returns_options_flow():
    entry = MockConfigEntry(domain=DOMAIN, options={})
    result = NotifyDashboardConfigFlow.async_get_options_flow(entry)
    assert isinstance(result, NotifyDashboardOptionsFlow)


# --- _mirror_dismiss_options: both notify entities and legacy notify
# services/groups should be selectable (see the const.py comment on
# RESERVED_NOTIFY_SERVICES for why send_message itself is excluded) ---


def test_mirror_dismiss_options_includes_entities_and_raw_services(hass):
    hass.states.async_set("notify.mobile_app_pixel", "unknown")
    async_mock_service(hass, "notify", "family_notifications")

    values = {opt["value"] for opt in _mirror_dismiss_options(hass)}
    assert "notify.mobile_app_pixel" in values
    assert "family_notifications" in values


def test_mirror_dismiss_options_excludes_send_message(hass):
    async_mock_service(hass, "notify", "send_message")
    values = {opt["value"] for opt in _mirror_dismiss_options(hass)}
    assert "send_message" not in values


# --- _mirror_dismiss_schema: deliberately just the raw selector, no
# vol.All(..., [validate_mirror_target]) wrapping: that shape used to
# validate fine on submit but broke voluptuous_serialize.convert() (used to
# send the form to the frontend on every render), producing a real 500 the
# moment anyone opened the config or options flow. validate_mirror_target
# now runs by hand via _invalid_mirror_targets in the step methods instead;
# see test_mirror_dismiss_schema_is_serializable below for the regression
# test that would have caught the original bug. ---


def test_mirror_dismiss_schema_accepts_entity_and_raw_service(hass):
    schema = _mirror_dismiss_schema(hass, [])
    result = schema(
        {CONF_MIRROR_DISMISS_TO: ["notify.mobile_app_pixel", "family_notifications"]}
    )
    assert result[CONF_MIRROR_DISMISS_TO] == [
        "notify.mobile_app_pixel",
        "family_notifications",
    ]


def test_mirror_dismiss_schema_is_serializable(hass):
    """Regression test: HA calls voluptuous_serialize.convert() on the
    schema every time a flow step is rendered (not just on submit); a
    schema that only validates correctly but can't be serialized still
    breaks the flow with a 500 before a user ever sees the form."""
    schema = _mirror_dismiss_schema(hass, [])
    voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)


def test_invalid_mirror_targets_accepts_entity_and_raw_service():
    assert _invalid_mirror_targets(["notify.mobile_app_pixel", "family_notifications"]) is False


def test_invalid_mirror_targets_rejects_wrong_domain():
    assert _invalid_mirror_targets(["sensor.wrong_domain"]) is True


async def test_user_flow_shows_form(hass):
    flow = _make_config_flow(hass)
    result = await flow.async_step_user()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_entry(hass):
    flow = _make_config_flow(hass)
    result = await flow.async_step_user({CONF_MIRROR_DISMISS_TO: ["notify.mobile_app"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Notify Dashboard"
    assert result["data"] == {}
    assert result["options"] == {CONF_MIRROR_DISMISS_TO: ["notify.mobile_app"]}


async def test_user_flow_reshows_form_with_error_on_invalid_target(hass):
    flow = _make_config_flow(hass)
    result = await flow.async_step_user({CONF_MIRROR_DISMISS_TO: ["sensor.wrong_domain"]})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_mirror_target"}

    # The invalid value is preserved so the user doesn't have to retype it.
    schema_defaults = {
        key.schema: key.default() for key in result["data_schema"].schema if hasattr(key, "default")
    }
    assert schema_defaults[CONF_MIRROR_DISMISS_TO] == ["sensor.wrong_domain"]


async def test_user_flow_aborts_if_already_configured(hass):
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)

    flow = _make_config_flow(hass)
    result = await flow.async_step_user()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_shows_form_prefilled_with_current_value(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_MIRROR_DISMISS_TO: ["notify.mobile_app"]}
    )
    entry.add_to_hass(hass)

    flow = _make_options_flow(hass, entry)
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    schema_defaults = {
        key.schema: key.default() for key in result["data_schema"].schema if hasattr(key, "default")
    }
    assert schema_defaults[CONF_MIRROR_DISMISS_TO] == ["notify.mobile_app"]


async def test_options_flow_updates_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)

    flow = _make_options_flow(hass, entry)
    result = await flow.async_step_init({CONF_MIRROR_DISMISS_TO: ["notify.mobile_app"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == ""
    assert result["data"] == {CONF_MIRROR_DISMISS_TO: ["notify.mobile_app"]}


async def test_options_flow_reshows_form_with_error_on_invalid_target(hass):
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)

    flow = _make_options_flow(hass, entry)
    result = await flow.async_step_init({CONF_MIRROR_DISMISS_TO: ["sensor.wrong_domain"]})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"base": "invalid_mirror_target"}

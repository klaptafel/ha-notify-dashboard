"""Tests for the config and options flows.

Instantiates the flow classes directly instead of going through
hass.config_entries.flow.async_init()/options.async_init() — those go
through the full flow manager, which first ensures the domain's component
(and its manifest dependencies, here http + frontend) is set up. frontend
needs the separate hass_frontend package, which isn't installable in this
environment (see conftest.py's hass_http/frontend_extra_js_urls docstrings
for the same root cause). None of that setup is relevant to what these
flows actually do, so bypassing it is a faithful, narrower unit test.
"""
from __future__ import annotations

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notify_dashboard.config_flow import (
    NotifyDashboardConfigFlow,
    NotifyDashboardOptionsFlow,
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

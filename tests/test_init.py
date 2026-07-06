"""Tests for the integration's setup wiring (async_setup / async_setup_entry /
async_unload_entry / the Lovelace resource registration).

Service *behavior* (dismiss/dismiss_all/fire_action bodies) lives in
test_services.py — this file is only about how everything gets wired up.
"""
from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notify_dashboard import (
    CONFIG_SCHEMA,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.notify_dashboard.const import (
    DOMAIN,
    SERVICE_DISMISS,
    SERVICE_DISMISS_ALL,
    SERVICE_FIRE_ACTION,
)


async def test_setup_registers_store_services_and_discovery(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    result = await async_setup(hass, {})
    assert result is True

    assert hass.data[DOMAIN]["mirror_dismiss_to"] == []
    assert hass.data[DOMAIN]["store"] is not None

    assert hass.services.has_service(DOMAIN, SERVICE_DISMISS)
    assert hass.services.has_service(DOMAIN, SERVICE_DISMISS_ALL)
    assert hass.services.has_service(DOMAIN, SERVICE_FIRE_ACTION)

    assert no_discovery == [("sensor", DOMAIN, {})]


async def test_setup_yaml_config_sets_mirror_dismiss_to(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    await async_setup(hass, {DOMAIN: {"mirror_dismiss_to": ["notify.mobile_app"]}})
    assert hass.data[DOMAIN]["mirror_dismiss_to"] == ["notify.mobile_app"]


async def test_setup_entry_sets_mirror_dismiss_to_from_options(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    entry = MockConfigEntry(
        domain=DOMAIN, options={"mirror_dismiss_to": ["notify.mobile_app"]}
    )
    entry.add_to_hass(hass)

    result = await async_setup_entry(hass, entry)
    assert result is True
    assert hass.data[DOMAIN]["mirror_dismiss_to"] == ["notify.mobile_app"]


async def test_dual_setup_yaml_then_entry_is_idempotent(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    await async_setup(hass, {})
    store_before = hass.data[DOMAIN]["store"]

    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)
    await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN]["store"] is store_before


async def test_dual_setup_entry_then_yaml_is_idempotent(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)
    await async_setup_entry(hass, entry)
    store_before = hass.data[DOMAIN]["store"]

    await async_setup(hass, {})

    assert hass.data[DOMAIN]["store"] is store_before


async def test_yaml_alongside_config_entry_warns_and_entry_wins(
    hass, hass_http, frontend_extra_js_urls, no_discovery, caplog
):
    entry = MockConfigEntry(
        domain=DOMAIN, options={"mirror_dismiss_to": ["notify.from_entry"]}
    )
    entry.add_to_hass(hass)
    await async_setup_entry(hass, entry)

    await async_setup(hass, {DOMAIN: {"mirror_dismiss_to": ["notify.from_yaml"]}})

    assert "take precedence" in caplog.text
    assert hass.data[DOMAIN]["mirror_dismiss_to"] == ["notify.from_entry"]


async def test_unload_entry_clears_mirror_dismiss_to(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    entry = MockConfigEntry(
        domain=DOMAIN, options={"mirror_dismiss_to": ["notify.mobile_app"]}
    )
    entry.add_to_hass(hass)
    await async_setup_entry(hass, entry)

    result = await async_unload_entry(hass, entry)
    assert result is True
    assert hass.data[DOMAIN]["mirror_dismiss_to"] == []


async def test_options_update_reloads_mirror_dismiss_to(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)
    await async_setup_entry(hass, entry)

    hass.config_entries.async_update_entry(
        entry, options={"mirror_dismiss_to": ["notify.mobile_app"]}
    )
    await hass.async_block_till_done()

    assert hass.data[DOMAIN]["mirror_dismiss_to"] == ["notify.mobile_app"]


# --- Lovelace resource registration ---


async def test_lovelace_yaml_mode_adds_extra_js_url(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    await async_setup(hass, {})
    await hass.async_block_till_done()

    assert len(frontend_extra_js_urls) == 1
    (url,) = frontend_extra_js_urls
    assert url.startswith("/notify_dashboard_frontend/notify-dashboard-card.js?v=")


async def test_lovelace_storage_mode_creates_item(
    hass, hass_http, fake_lovelace_storage, no_discovery
):
    await async_setup(hass, {})
    await hass.async_block_till_done()

    items = fake_lovelace_storage.resources.async_items()
    assert len(items) == 1
    assert items[0]["url"].startswith("/notify_dashboard_frontend/notify-dashboard-card.js?v=")
    assert items[0]["res_type"] == "module"


async def test_lovelace_storage_mode_updates_existing_item_on_version_change(
    hass, hass_http, fake_lovelace_storage, no_discovery
):
    fake_lovelace_storage.resources.items.append(
        {
            "id": "existing",
            "res_type": "module",
            "url": "/notify_dashboard_frontend/notify-dashboard-card.js?v=0.0.1",
        }
    )

    await async_setup(hass, {})
    await hass.async_block_till_done()

    items = fake_lovelace_storage.resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "existing"
    assert not items[0]["url"].endswith("v=0.0.1")


async def test_lovelace_storage_mode_leaves_up_to_date_item_untouched(
    hass, hass_http, fake_lovelace_storage, no_discovery
):
    from homeassistant.loader import async_get_integration

    integration = await async_get_integration(hass, DOMAIN)
    current_url = (
        f"/notify_dashboard_frontend/notify-dashboard-card.js?v={integration.version}"
    )
    fake_lovelace_storage.resources.items.append(
        {"id": "existing", "res_type": "module", "url": current_url}
    )

    await async_setup(hass, {})
    await hass.async_block_till_done()

    items = fake_lovelace_storage.resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "existing"
    assert items[0]["url"] == current_url


async def test_lovelace_registration_waits_for_started_event_when_not_running(
    hass, hass_http, frontend_extra_js_urls, no_discovery
):
    hass.set_state(CoreState.not_running)

    await async_setup(hass, {})
    await hass.async_block_till_done()
    assert len(frontend_extra_js_urls) == 0

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert len(frontend_extra_js_urls) == 1


# --- CONFIG_SCHEMA: mirror_dismiss_to accepts both notify entity ids and
# bare legacy notify service names (e.g. a YAML `notify: - platform: group`,
# which has no entity at all — see config_flow.py's _mirror_dismiss_options
# for the full reasoning) ---


def test_config_schema_accepts_entity_and_raw_service_mirror_targets():
    result = CONFIG_SCHEMA(
        {
            DOMAIN: {
                "mirror_dismiss_to": ["notify.mobile_app_pixel", "family_notifications"]
            }
        }
    )
    assert result[DOMAIN]["mirror_dismiss_to"] == [
        "notify.mobile_app_pixel",
        "family_notifications",
    ]


def test_config_schema_rejects_non_notify_entity_mirror_target():
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA({DOMAIN: {"mirror_dismiss_to": ["sensor.not_a_notify_entity"]}})

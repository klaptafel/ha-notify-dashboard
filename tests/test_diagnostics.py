"""Tests for diagnostics.py — aggregates only, never notification content."""
from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notify_dashboard.const import DOMAIN
from custom_components.notify_dashboard.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_empty_store(hass, loaded_store):
    hass.data[DOMAIN] = {"store": loaded_store, "mirror_dismiss_to": []}
    entry = MockConfigEntry(domain=DOMAIN, options={})

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config"]["mirror_dismiss_to"] == []
    assert result["notifications"] == {
        "count": 0,
        "persistent_count": 0,
        "oldest_created_at": None,
        "newest_created_at": None,
    }
    assert result["live_activities"] == {
        "count": 0,
        "oldest_updated_at": None,
        "newest_updated_at": None,
    }
    assert result["dismissed"] == {"count": 0, "newest_dismissed_at": None}


async def test_diagnostics_reports_aggregates_not_content(hass, loaded_store):
    hass.data[DOMAIN] = {
        "store": loaded_store,
        "mirror_dismiss_to": ["notify.mobile_app_pixel"],
    }
    await loaded_store.async_add_notification("Secret title", "Secret body", {"tag": "a"})
    await loaded_store.async_add_notification(
        "T2", "M2", {"tag": "b", "persistent": True}
    )
    await loaded_store.async_upsert_live_activity("T3", "M3", {"tag": "job1", "live_update": True})
    await loaded_store.async_dismiss(loaded_store.data["items"][-1]["id"])

    result = await async_get_config_entry_diagnostics(
        hass, MockConfigEntry(domain=DOMAIN, options={})
    )

    assert result["config"]["mirror_dismiss_to"] == ["notify.mobile_app_pixel"]
    assert result["notifications"]["count"] == 1
    assert result["notifications"]["persistent_count"] == 1
    assert result["live_activities"]["count"] == 1
    assert result["notifications"]["oldest_created_at"] is not None
    assert result["notifications"]["newest_created_at"] is not None
    assert result["live_activities"]["oldest_updated_at"] is not None
    assert result["live_activities"]["newest_updated_at"] is not None
    assert result["dismissed"]["count"] == 1
    assert result["dismissed"]["newest_dismissed_at"] is not None

    # The whole point of this file: never leak actual content.
    serialized = str(result)
    assert "Secret title" not in serialized
    assert "Secret body" not in serialized

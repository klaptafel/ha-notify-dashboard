"""Tests for the three registered services (dismiss / dismiss_all /
fire_action) and the mirror_dismiss_to forwarding they trigger.

Setup wiring itself (async_setup / async_setup_entry / Lovelace resource
registration) is covered in test_init.py — this file only exercises the
service handler bodies defined inside _async_ensure_core.
"""
from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.notify_dashboard import async_setup
from custom_components.notify_dashboard.const import (
    ATTR_ACTION,
    ATTR_ACTION_DATA,
    ATTR_ID,
    ATTR_TAG,
    DOMAIN,
    EVENT_NOTIFICATION_ACTION,
    SERVICE_DISMISS,
    SERVICE_DISMISS_ALL,
    SERVICE_FIRE_ACTION,
)


@pytest.fixture(autouse=True)
async def _setup(hass, hass_http, frontend_extra_js_urls, no_discovery):
    await async_setup(hass, {})
    await hass.async_block_till_done()


@pytest.fixture
def store(hass):
    return hass.data[DOMAIN]["store"]


# --- dismiss ---


async def test_dismiss_removes_notification(hass, store):
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["notifications"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    assert store.data["notifications"] == []


async def test_dismiss_unknown_id_raises_service_validation_error(hass):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_DISMISS, {ATTR_ID: "does-not-exist"}, blocking=True
        )


async def test_dismiss_persistent_raises_service_validation_error(hass, store):
    await store.async_add_notification("T", "M", {"tag": "t1", "persistent": True})
    item_id = store.data["notifications"][0]["id"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
        )


async def test_dismiss_without_mirror_targets_does_not_call_notify(
    hass, store, mock_notify_target
):
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["notifications"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    assert len(mock_notify_target) == 0


async def test_dismiss_with_mirror_targets_forwards_clear_notification(
    hass, store, mock_notify_target
):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["notifications"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(mock_notify_target) == 1
    call = mock_notify_target[0]
    assert call.data["message"] == "clear_notification"
    assert call.data["data"]["tag"] == "t1"


async def test_dismiss_without_tag_does_not_forward(hass, store, mock_notify_target):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {})
    item_id = store.data["notifications"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(mock_notify_target) == 0


async def test_dismiss_mirror_forward_failure_does_not_break_dismiss(hass, store):
    # No "notify.send_message" service registered at all (unlike the
    # mock_notify_target-using tests above) — simulates a mirror_dismiss_to
    # target that no longer exists. The best-effort forward must be
    # swallowed by _clear_one's try/except, without affecting the dismiss
    # itself.
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["notifications"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert store.data["notifications"] == []


async def test_dismiss_all_clears_and_keeps_persistent(hass, store):
    await store.async_add_notification("T", "M", {"tag": "a"})
    await store.async_add_notification("T", "M", {"tag": "b", "persistent": True})

    await hass.services.async_call(DOMAIN, SERVICE_DISMISS_ALL, {}, blocking=True)

    remaining_tags = {n["tag"] for n in store.data["notifications"]}
    assert remaining_tags == {"b"}


async def test_dismiss_all_forwards_cleared_tags_to_mirror_targets(
    hass, store, mock_notify_target
):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "a"})
    await store.async_add_notification("T", "M", {"tag": "b"})

    await hass.services.async_call(DOMAIN, SERVICE_DISMISS_ALL, {}, blocking=True)
    await hass.async_block_till_done()

    forwarded_tags = {call.data["data"]["tag"] for call in mock_notify_target}
    assert forwarded_tags == {"a", "b"}


async def test_dismiss_all_without_mirror_targets_does_not_call_notify(
    hass, store, mock_notify_target
):
    await store.async_add_notification("T", "M", {"tag": "a"})
    await hass.services.async_call(DOMAIN, SERVICE_DISMISS_ALL, {}, blocking=True)
    await hass.async_block_till_done()
    assert len(mock_notify_target) == 0


# --- fire_action ---


async def test_fire_action_minimal_payload_omits_optional_keys(hass):
    events = async_capture_events(hass, EVENT_NOTIFICATION_ACTION)

    await hass.services.async_call(
        DOMAIN, SERVICE_FIRE_ACTION, {ATTR_ACTION: "OPEN"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {ATTR_ACTION: "OPEN"}
    assert ATTR_TAG not in events[0].data
    assert ATTR_ACTION_DATA not in events[0].data


async def test_fire_action_includes_tag_and_action_data_when_present(hass):
    events = async_capture_events(hass, EVENT_NOTIFICATION_ACTION)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_FIRE_ACTION,
        {ATTR_ACTION: "OPEN", ATTR_TAG: "job1", ATTR_ACTION_DATA: {"foo": "bar"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        ATTR_ACTION: "OPEN",
        ATTR_TAG: "job1",
        ATTR_ACTION_DATA: {"foo": "bar"},
    }

"""Tests for the three registered services (dismiss / dismiss_all /
fire_action) and the mirror_dismiss_to forwarding they trigger.

Setup wiring itself (async_setup / async_setup_entry / Lovelace resource
registration) is covered in test_init.py — this file only exercises the
service handler bodies defined inside _async_ensure_core.
"""
from __future__ import annotations

import time

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

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
from custom_components.notify_dashboard.store import is_active


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
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    assert not is_active(store.data["items"][0])


async def test_dismiss_unknown_id_raises_service_validation_error(hass):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_DISMISS, {ATTR_ID: "does-not-exist"}, blocking=True
        )


async def test_dismiss_persistent_raises_service_validation_error(hass, store):
    await store.async_add_notification("T", "M", {"tag": "t1", "persistent": True})
    item_id = store.data["items"][0]["id"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
        )


async def test_dismiss_without_mirror_targets_does_not_call_notify(
    hass, store, mock_notify_target
):
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    assert len(mock_notify_target) == 0


async def test_dismiss_with_mirror_targets_forwards_clear_notification(
    hass, store, mock_notify_target
):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

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
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(mock_notify_target) == 0


async def test_dismiss_mirror_forward_failure_does_not_break_dismiss(hass, store):
    # Entity exists (so the missing-target issue check passes) but no
    # "notify.send_message" service is registered at all — simulates a
    # target that exists but fails to actually handle the call. The
    # best-effort forward must be swallowed by _clear_one's try/except,
    # without affecting the dismiss itself, and without creating a repair
    # issue (that's reserved for the target-doesn't-exist case).
    hass.states.async_set("notify.mobile_app", "unknown")
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert not is_active(store.data["items"][0])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_notify.mobile_app") is None


async def test_dismiss_missing_mirror_target_creates_repair_issue(hass, store):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_notify.mobile_app")
    assert issue is not None
    assert issue.translation_key == "missing_mirror_target"
    assert issue.translation_placeholders == {"entity_id": "notify.mobile_app"}


async def test_dismiss_mirror_target_reappearing_clears_repair_issue(
    hass, store, mock_notify_target
):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]

    # First: target missing, dismiss creates the issue.
    hass.states.async_remove("notify.mobile_app")
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]
    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_notify.mobile_app") is not None

    # Then: target exists again (e.g. companion app reinstalled) — the next
    # dismiss should self-heal by deleting the stale issue.
    hass.states.async_set("notify.mobile_app", "unknown")
    await store.async_add_notification("T", "M", {"tag": "t2"})
    item_id = store.data["items"][0]["id"]
    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_notify.mobile_app") is None


async def test_dismiss_all_clears_and_keeps_persistent(hass, store):
    await store.async_add_notification("T", "M", {"tag": "a"})
    await store.async_add_notification("T", "M", {"tag": "b", "persistent": True})

    await hass.services.async_call(DOMAIN, SERVICE_DISMISS_ALL, {}, blocking=True)

    active_tags = {n["tag"] for n in store.data["items"] if is_active(n)}
    assert active_tags == {"b"}


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


# --- mirror_dismiss_to: raw legacy notify services (e.g. a YAML
# `notify: - platform: group`), not just notify entities ---


async def test_dismiss_forwards_to_raw_notify_service(hass, store):
    group_calls = async_mock_service(hass, "notify", "family_notifications")
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["family_notifications"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(group_calls) == 1
    assert group_calls[0].data["message"] == "clear_notification"
    assert group_calls[0].data["data"]["tag"] == "t1"


async def test_dismiss_raw_service_forward_failure_does_not_break_dismiss(hass, store):
    # Registered (passes the has_service check, no repair issue) with a
    # schema our clear_notification payload can't satisfy — schema
    # validation raises synchronously as part of the call itself, even with
    # blocking=False (unlike an exception raised from inside the handler,
    # which runs as a background task and wouldn't be caught here at all).
    # The best-effort forward must be swallowed regardless, without
    # affecting the dismiss itself.
    async def _flaky_handler(call):
        pass

    hass.services.async_register(
        "notify",
        "flaky_group",
        _flaky_handler,
        schema=vol.Schema({vol.Required("must_have_this"): str}),
    )
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["flaky_group"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert not is_active(store.data["items"][0])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_flaky_group") is None


async def test_dismiss_missing_raw_service_creates_repair_issue(hass, store):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["nonexistent_group"]
    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]

    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_nonexistent_group")
    assert issue is not None
    assert issue.translation_placeholders == {"entity_id": "nonexistent_group"}


async def test_dismiss_raw_service_reappearing_clears_repair_issue(hass, store):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["family_notifications"]

    await store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = store.data["items"][0]["id"]
    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_family_notifications")
        is not None
    )

    async_mock_service(hass, "notify", "family_notifications")
    await store.async_add_notification("T2", "M2", {"tag": "t2"})
    item_id = store.data["items"][0]["id"]
    await hass.services.async_call(
        DOMAIN, SERVICE_DISMISS, {ATTR_ID: item_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, "missing_mirror_target_family_notifications")
        is None
    )


# --- automatic expiry (timeout/capacity) also forwards mirror_dismiss_to ---


async def test_expired_notification_forwards_mirror_dismiss(hass, store, mock_notify_target):
    hass.data[DOMAIN]["mirror_dismiss_to"] = ["notify.mobile_app"]
    await store.async_add_notification("T", "M", {"tag": "expiring", "timeout": 1})
    store.data["items"][0]["created_at"] = time.time() - 100

    # Any subsequent store write runs cleanup first, discovering the
    # now-expired entry above — same as an explicit dismiss would.
    await store.async_add_notification("T2", "M2", {})
    await hass.async_block_till_done()

    assert len(mock_notify_target) == 1
    assert mock_notify_target[0].data["data"]["tag"] == "expiring"


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

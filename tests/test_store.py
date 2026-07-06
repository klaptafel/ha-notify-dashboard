"""Tests for NotifyDashboardStore — the integration's core business logic."""
from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_dashboard.const import (
    LIVE_ACTIVITY_STALE_HOURS,
    MAX_AGE_DAYS,
    MAX_NOTIFICATIONS,
    STORAGE_KEY,
)
from custom_components.notify_dashboard.store import (
    CLEANUP_INTERVAL,
    NotificationNotDismissableError,
    NotificationNotFoundError,
    NotifyDashboardStore,
)


async def test_store_loads_empty(hass):
    store = NotifyDashboardStore(hass)
    await store.async_load()
    assert store.data == {"notifications": [], "live_activities": {}}
    store._unsub_periodic_cleanup()


async def test_store_restores_persisted_data(hass, hass_storage):
    now = time.time()
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "notifications": [
                {
                    "id": "abc",
                    "tag": "t1",
                    "group": None,
                    "title": "T",
                    "message": "M",
                    "data": {},
                    "created_at": now,
                    "updated_at": now,
                    "timeout": None,
                }
            ],
            "live_activities": {},
        },
    }
    store = NotifyDashboardStore(hass)
    await store.async_load()
    assert len(store.data["notifications"]) == 1
    assert store.data["notifications"][0]["id"] == "abc"
    store._unsub_periodic_cleanup()


async def test_load_runs_cleanup_immediately(hass, hass_storage):
    """Already-expired persisted data should be gone right after async_load,
    not just after the next periodic tick."""
    expired_at = time.time() - (MAX_AGE_DAYS * 86400 + 10)
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "notifications": [
                {
                    "id": "old",
                    "tag": None,
                    "group": None,
                    "title": "T",
                    "message": "M",
                    "data": {},
                    "created_at": expired_at,
                    "updated_at": expired_at,
                    "timeout": None,
                }
            ],
            "live_activities": {},
        },
    }
    store = NotifyDashboardStore(hass)
    await store.async_load()
    assert store.data["notifications"] == []
    store._unsub_periodic_cleanup()


# --- async_add_notification ---


async def test_add_notification_tag_replace(loaded_store):
    await loaded_store.async_add_notification("T1", "M1", {"tag": "dishwasher"})
    await loaded_store.async_add_notification("T2", "M2", {"tag": "dishwasher"})
    notifications = loaded_store.data["notifications"]
    assert len(notifications) == 1
    assert notifications[0]["message"] == "M2"


async def test_add_notification_newest_first(loaded_store):
    await loaded_store.async_add_notification("T1", "M1", {})
    await loaded_store.async_add_notification("T2", "M2", {})
    messages = [n["message"] for n in loaded_store.data["notifications"]]
    assert messages == ["M2", "M1"]


async def test_add_notification_hard_cap(loaded_store):
    for i in range(MAX_NOTIFICATIONS + 5):
        await loaded_store.async_add_notification(f"T{i}", f"M{i}", {})
    notifications = loaded_store.data["notifications"]
    assert len(notifications) == MAX_NOTIFICATIONS
    # Newest-first, so the survivors are the highest-numbered (most recent).
    assert notifications[0]["message"] == f"M{MAX_NOTIFICATIONS + 4}"
    assert notifications[-1]["message"] == "M5"


# --- async_upsert_live_activity ---


async def test_upsert_live_activity_requires_tag(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "M", {})
    assert loaded_store.data["live_activities"] == {}


async def test_upsert_live_activity_replaces_in_place(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "10%", {"tag": "job1", "progress": 10})
    await loaded_store.async_upsert_live_activity("T", "90%", {"tag": "job1", "progress": 90})
    assert len(loaded_store.data["live_activities"]) == 1
    assert loaded_store.data["live_activities"]["job1"]["message"] == "90%"


async def test_upsert_live_activity_progress_minus_one_is_not_special(loaded_store):
    """progress: -1 isn't a documented companion-app sentinel (confirmed
    against the actual docs — the real way to end a live activity is
    clear_notification + tag, see async_clear_by_tag) — it's stored as
    ordinary data like any other progress value, not treated as "done"."""
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "job1", "progress": -1})
    assert "job1" in loaded_store.data["live_activities"]
    assert loaded_store.data["live_activities"]["job1"]["data"]["progress"] == -1


# --- async_clear_by_tag ---


async def test_clear_by_tag_removes_both_kinds(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "shared"})
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "shared"})
    await loaded_store.async_clear_by_tag("shared")
    assert loaded_store.data["notifications"] == []
    assert loaded_store.data["live_activities"] == {}


async def test_clear_by_tag_forwards_removed_notification(hass):
    on_removed = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_removed)
    await store.async_load()
    try:
        await store.async_add_notification("T", "M", {"tag": "t1"})
        on_removed.reset_mock()  # the add itself never removes anything
        await store.async_clear_by_tag("t1")
        on_removed.assert_awaited_once_with(["t1"])
    finally:
        store._unsub_periodic_cleanup()


async def test_clear_by_tag_forwards_removed_live_activity(hass):
    on_removed = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_removed)
    await store.async_load()
    try:
        await store.async_upsert_live_activity("T", "M", {"tag": "job1"})
        on_removed.reset_mock()
        await store.async_clear_by_tag("job1")
        on_removed.assert_awaited_once_with(["job1"])
    finally:
        store._unsub_periodic_cleanup()


async def test_clear_by_tag_does_not_forward_when_nothing_matched(hass):
    on_removed = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_removed)
    await store.async_load()
    try:
        await store.async_clear_by_tag("does-not-exist")
        on_removed.assert_not_awaited()
    finally:
        store._unsub_periodic_cleanup()


# --- async_dismiss ---


async def test_dismiss_notification(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = loaded_store.data["notifications"][0]["id"]
    dismissed = await loaded_store.async_dismiss(item_id)
    assert dismissed["id"] == item_id
    assert loaded_store.data["notifications"] == []


async def test_dismiss_persistent_notification_raises(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1", "persistent": True})
    item_id = loaded_store.data["notifications"][0]["id"]
    try:
        await loaded_store.async_dismiss(item_id)
        assert False, "expected NotificationNotDismissableError"
    except NotificationNotDismissableError:
        pass
    assert len(loaded_store.data["notifications"]) == 1


async def test_dismiss_unknown_id_raises(loaded_store):
    try:
        await loaded_store.async_dismiss("does-not-exist")
        assert False, "expected NotificationNotFoundError"
    except NotificationNotFoundError:
        pass


async def test_dismiss_live_activity_by_tag(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "job1"})
    dismissed = await loaded_store.async_dismiss("job1")
    assert dismissed["tag"] == "job1"
    assert "job1" not in loaded_store.data["live_activities"]


# --- async_dismiss_all_notifications ---


async def test_dismiss_all_keeps_persistent_returns_cleared(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "a"})
    await loaded_store.async_add_notification("T", "M", {"tag": "b", "persistent": True})
    cleared = await loaded_store.async_dismiss_all_notifications()
    assert {item["tag"] for item in cleared} == {"a"}
    remaining_tags = {n["tag"] for n in loaded_store.data["notifications"]}
    assert remaining_tags == {"b"}


# --- expiry math (_cleanup) — no clock patching needed, timestamps precomputed ---


async def test_cleanup_expires_by_per_item_timeout(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1", "timeout": 100})
    notif = loaded_store.data["notifications"][0]
    notif["created_at"] = time.time() - 200  # older than its own 100s timeout
    loaded_store._cleanup()
    assert loaded_store.data["notifications"] == []


async def test_cleanup_expires_by_max_age_days_when_no_timeout(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    notif = loaded_store.data["notifications"][0]
    notif["created_at"] = time.time() - (MAX_AGE_DAYS * 86400 + 10)
    loaded_store._cleanup()
    assert loaded_store.data["notifications"] == []


async def test_cleanup_expires_stale_live_activity(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "job1"})
    loaded_store.data["live_activities"]["job1"]["updated_at"] = time.time() - (
        LIVE_ACTIVITY_STALE_HOURS * 3600 + 10
    )
    loaded_store._cleanup()
    assert loaded_store.data["live_activities"] == {}


# --- periodic cleanup timer — needs both clocks frozen (time.time() AND dt_util.utcnow()) ---


async def test_periodic_cleanup_fires_and_saves(hass):
    with freeze_time(dt_util.utcnow()) as freezer:
        store = NotifyDashboardStore(hass)
        await store.async_load()
        try:
            await store.async_add_notification("T", "M", {"tag": "t1", "timeout": 5})
            # Advance past both the item's own timeout and the periodic interval.
            freezer.tick(timedelta(seconds=10))
            freezer.tick(CLEANUP_INTERVAL)
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            assert store.data["notifications"] == []
        finally:
            store._unsub_periodic_cleanup()


async def test_periodic_cleanup_noop_when_nothing_expired(hass):
    with freeze_time(dt_util.utcnow()) as freezer:
        store = NotifyDashboardStore(hass)
        await store.async_load()
        try:
            await store.async_add_notification("T", "M", {"tag": "t1"})  # no timeout, far from expiry
            before = list(store.data["notifications"])
            freezer.tick(CLEANUP_INTERVAL)
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            assert store.data["notifications"] == before
        finally:
            store._unsub_periodic_cleanup()


async def test_start_periodic_cleanup_is_idempotent(hass):
    store = NotifyDashboardStore(hass)
    await store.async_load()
    first_unsub = store._unsub_periodic_cleanup
    store._start_periodic_cleanup()
    assert store._unsub_periodic_cleanup is first_unsub
    store._unsub_periodic_cleanup()


# --- on_removed — mirror_dismiss_to forwarding for automatic expiry ---
# (a notification that times out disappears from the dashboard exactly
# like an explicit dismiss does, so it should get the same treatment)


async def test_on_expired_called_for_timeout_expiry(hass):
    on_expired = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_expired)
    await store.async_load()
    try:
        await store.async_add_notification("T", "M", {"tag": "t1", "timeout": 100})
        store.data["notifications"][0]["created_at"] = time.time() - 200
        # Any subsequent write runs _cleanup() first, discovering the
        # now-expired entry above.
        await store.async_add_notification("T2", "M2", {})
        on_expired.assert_awaited_once_with(["t1"])
    finally:
        store._unsub_periodic_cleanup()


async def test_on_expired_called_for_hard_cap_trim(hass):
    on_expired = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_expired)
    await store.async_load()
    try:
        await store.async_add_notification("T", "M", {"tag": "oldest"})
        for i in range(MAX_NOTIFICATIONS):
            await store.async_add_notification(f"T{i}", f"M{i}", {})
        on_expired.assert_awaited_once_with(["oldest"])
    finally:
        store._unsub_periodic_cleanup()


async def test_on_expired_called_for_live_activity_staleness(hass):
    on_expired = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_expired)
    await store.async_load()
    try:
        await store.async_upsert_live_activity("T", "M", {"tag": "job1"})
        store.data["live_activities"]["job1"]["updated_at"] = time.time() - (
            LIVE_ACTIVITY_STALE_HOURS * 3600 + 10
        )
        await store.async_add_notification("T2", "M2", {})
        on_expired.assert_awaited_once_with(["job1"])
    finally:
        store._unsub_periodic_cleanup()


async def test_on_expired_not_called_when_nothing_expired(hass):
    on_expired = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_expired)
    await store.async_load()
    try:
        await store.async_add_notification("T", "M", {"tag": "t1"})
        on_expired.assert_not_awaited()
    finally:
        store._unsub_periodic_cleanup()


async def test_on_expired_not_called_for_untagged_expiry(hass):
    on_expired = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_expired)
    await store.async_load()
    try:
        await store.async_add_notification("T", "M", {"timeout": 100})
        store.data["notifications"][0]["created_at"] = time.time() - 200
        await store.async_add_notification("T2", "M2", {})
        on_expired.assert_not_awaited()
    finally:
        store._unsub_periodic_cleanup()


async def test_on_expired_not_called_during_async_load_startup_cleanup(hass, hass_storage):
    """The callback's caller (hass.data[DOMAIN]) isn't populated yet at
    this point in real setup, so async_load's own cleanup pass must not
    invoke it — only later writes/the periodic timer should."""
    expired_at = time.time() - (MAX_AGE_DAYS * 86400 + 10)
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "notifications": [
                {
                    "id": "old",
                    "tag": "t1",
                    "group": None,
                    "title": "T",
                    "message": "M",
                    "data": {},
                    "created_at": expired_at,
                    "updated_at": expired_at,
                    "timeout": None,
                }
            ],
            "live_activities": {},
        },
    }
    on_expired = AsyncMock()
    store = NotifyDashboardStore(hass, on_removed=on_expired)
    await store.async_load()
    try:
        assert store.data["notifications"] == []
        on_expired.assert_not_awaited()
    finally:
        store._unsub_periodic_cleanup()


async def test_on_expired_called_from_periodic_timer(hass):
    on_expired = AsyncMock()
    with freeze_time(dt_util.utcnow()) as freezer:
        store = NotifyDashboardStore(hass, on_removed=on_expired)
        await store.async_load()
        try:
            await store.async_add_notification("T", "M", {"tag": "t1", "timeout": 5})
            freezer.tick(timedelta(seconds=10))
            freezer.tick(CLEANUP_INTERVAL)
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            on_expired.assert_awaited_once_with(["t1"])
        finally:
            store._unsub_periodic_cleanup()

"""Tests for NotifyDashboardStore — the integration's core business logic."""
from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_dashboard.const import (
    DISMISS_REASON_CLEAR_NOTIFICATION,
    DISMISS_REASON_DISMISS,
    DISMISS_REASON_DISMISS_ALL,
    DISMISS_REASON_STALE,
    DISMISS_REASON_TIMEOUT,
    LIVE_ACTIVITY_STALE_HOURS,
    MAX_AGE_DAYS,
    MAX_ITEMS,
    STORAGE_KEY,
)
from custom_components.notify_dashboard.store import (
    CLEANUP_INTERVAL,
    NotificationNotDismissableError,
    NotificationNotFoundError,
    NotifyDashboardStore,
    is_active,
)


async def test_store_loads_empty(hass):
    store = NotifyDashboardStore(hass)
    await store.async_load()
    assert store.data == {"items": []}
    store._unsub_periodic_cleanup()


async def test_store_restores_persisted_data(hass, hass_storage):
    now = time.time()
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "items": [
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
                    "dismissed_at": None,
                    "dismiss_reason": None,
                }
            ]
        },
    }
    store = NotifyDashboardStore(hass)
    await store.async_load()
    assert len(store.data["items"]) == 1
    assert store.data["items"][0]["id"] == "abc"
    store._unsub_periodic_cleanup()


async def test_store_discards_pre_unification_data_instead_of_crashing(hass, hass_storage):
    """The old notifications/live_activities/dismissed shape (from a
    version that was never actually released) has no "items" key at all —
    async_load must not crash on it, just start fresh."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {"notifications": [{"id": "old"}], "live_activities": {}, "dismissed": []},
    }
    store = NotifyDashboardStore(hass)
    await store.async_load()
    assert store.data == {"items": []}
    store._unsub_periodic_cleanup()


async def test_load_runs_cleanup_immediately(hass, hass_storage):
    """Already-expired persisted data should be dismissed right after
    async_load, not just after the next periodic tick."""
    expired_at = time.time() - (MAX_AGE_DAYS * 86400 + 10)
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "items": [
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
                    "dismissed_at": None,
                    "dismiss_reason": None,
                }
            ]
        },
    }
    store = NotifyDashboardStore(hass)
    await store.async_load()
    entry = store.data["items"][0]
    assert entry["dismissed_at"] is not None
    assert entry["dismiss_reason"] == DISMISS_REASON_TIMEOUT
    store._unsub_periodic_cleanup()


# --- async_add_notification ---


async def test_add_notification_tag_replace(loaded_store):
    await loaded_store.async_add_notification("T1", "M1", {"tag": "dishwasher"})
    await loaded_store.async_add_notification("T2", "M2", {"tag": "dishwasher"})
    items = loaded_store.data["items"]
    assert len(items) == 1
    assert items[0]["message"] == "M2"


async def test_add_notification_newest_first(loaded_store):
    await loaded_store.async_add_notification("T1", "M1", {})
    await loaded_store.async_add_notification("T2", "M2", {})
    messages = [n["message"] for n in loaded_store.data["items"]]
    assert messages == ["M2", "M1"]


async def test_add_notification_does_not_replace_dismissed_entry_with_same_tag(loaded_store):
    """Tag-replace only ever touches a currently-active entry — an old,
    already-dismissed entry with the same tag stays in history untouched,
    it's just not the one that gets replaced."""
    await loaded_store.async_add_notification("T1", "M1", {"tag": "dishwasher"})
    await loaded_store.async_dismiss(loaded_store.data["items"][0]["id"])
    await loaded_store.async_add_notification("T2", "M2", {"tag": "dishwasher"})
    items = loaded_store.data["items"]
    assert len(items) == 2
    assert items[0]["message"] == "M2"
    assert is_active(items[0])
    assert items[1]["message"] == "M1"
    assert not is_active(items[1])


async def test_add_notification_hard_cap(loaded_store):
    for i in range(MAX_ITEMS + 5):
        await loaded_store.async_add_notification(f"T{i}", f"M{i}", {"tag": f"t{i}"})
    items = loaded_store.data["items"]
    assert len(items) == MAX_ITEMS
    # Newest-first, so the survivors are the highest-numbered (most recent).
    assert items[0]["message"] == f"M{MAX_ITEMS + 4}"
    assert items[-1]["message"] == "M5"


# --- async_upsert_live_activity ---


async def test_upsert_live_activity_requires_tag(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "M", {"live_update": True})
    assert loaded_store.data["items"] == []


async def test_upsert_live_activity_replaces_in_place(loaded_store):
    await loaded_store.async_upsert_live_activity(
        "T", "10%", {"tag": "job1", "live_update": True, "progress": 10}
    )
    await loaded_store.async_upsert_live_activity(
        "T", "90%", {"tag": "job1", "live_update": True, "progress": 90}
    )
    items = loaded_store.data["items"]
    assert len(items) == 1
    assert items[0]["message"] == "90%"


async def test_upsert_live_activity_preserves_created_at_across_updates(loaded_store):
    await loaded_store.async_upsert_live_activity(
        "T", "10%", {"tag": "job1", "live_update": True, "progress": 10}
    )
    first_created_at = loaded_store.data["items"][0]["created_at"]
    await loaded_store.async_upsert_live_activity(
        "T", "90%", {"tag": "job1", "live_update": True, "progress": 90}
    )
    assert loaded_store.data["items"][0]["created_at"] == first_created_at


async def test_upsert_live_activity_progress_minus_one_is_not_special(loaded_store):
    """progress: -1 isn't a documented companion-app sentinel (confirmed
    against the actual docs — the real way to end a live activity is
    clear_notification + tag, see async_clear_by_tag) — it's stored as
    ordinary data like any other progress value, not treated as "done"."""
    await loaded_store.async_upsert_live_activity(
        "T", "M", {"tag": "job1", "live_update": True, "progress": -1}
    )
    entry = loaded_store.data["items"][0]
    assert entry["data"]["progress"] == -1
    assert is_active(entry)


# --- async_clear_by_tag ---


async def test_clear_by_tag_dismisses_matching_active_entry(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "shared"})
    await loaded_store.async_clear_by_tag("shared")
    entry = loaded_store.data["items"][0]
    assert not is_active(entry)
    assert entry["dismiss_reason"] == DISMISS_REASON_CLEAR_NOTIFICATION


async def test_clear_by_tag_forwards_removed_notification(loaded_store_factory):
    on_removed = AsyncMock()
    store = await loaded_store_factory(on_removed=on_removed)
    await store.async_add_notification("T", "M", {"tag": "t1"})
    on_removed.reset_mock()  # the add itself never removes anything
    await store.async_clear_by_tag("t1")
    on_removed.assert_awaited_once_with(["t1"])


async def test_clear_by_tag_forwards_removed_live_activity(loaded_store_factory):
    on_removed = AsyncMock()
    store = await loaded_store_factory(on_removed=on_removed)
    await store.async_upsert_live_activity("T", "M", {"tag": "job1", "live_update": True})
    on_removed.reset_mock()
    await store.async_clear_by_tag("job1")
    on_removed.assert_awaited_once_with(["job1"])


async def test_clear_by_tag_does_not_forward_when_nothing_matched(loaded_store_factory):
    on_removed = AsyncMock()
    store = await loaded_store_factory(on_removed=on_removed)
    await store.async_clear_by_tag("does-not-exist")
    on_removed.assert_not_awaited()


async def test_clear_by_tag_does_not_forward_for_already_dismissed_entry(loaded_store_factory):
    on_removed = AsyncMock()
    store = await loaded_store_factory(on_removed=on_removed)
    await store.async_add_notification("T", "M", {"tag": "t1"})
    await store.async_dismiss(store.data["items"][0]["id"])
    on_removed.reset_mock()
    await store.async_clear_by_tag("t1")
    on_removed.assert_not_awaited()


# --- async_dismiss ---


async def test_dismiss_notification(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = loaded_store.data["items"][0]["id"]
    dismissed = await loaded_store.async_dismiss(item_id)
    assert dismissed["id"] == item_id
    assert not is_active(loaded_store.data["items"][0])


async def test_dismiss_persistent_notification_raises(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1", "persistent": True})
    item_id = loaded_store.data["items"][0]["id"]
    try:
        await loaded_store.async_dismiss(item_id)
        assert False, "expected NotificationNotDismissableError"
    except NotificationNotDismissableError:
        pass
    assert is_active(loaded_store.data["items"][0])


async def test_dismiss_persistent_live_activity_still_dismissable(loaded_store):
    """persistent only blocks manual dismiss for notifications — a live
    activity stays dismissable via the close button regardless."""
    await loaded_store.async_upsert_live_activity(
        "T", "M", {"tag": "job1", "live_update": True, "persistent": True}
    )
    dismissed = await loaded_store.async_dismiss("job1")
    assert dismissed["tag"] == "job1"
    assert not is_active(loaded_store.data["items"][0])


async def test_dismiss_unknown_id_raises(loaded_store):
    try:
        await loaded_store.async_dismiss("does-not-exist")
        assert False, "expected NotificationNotFoundError"
    except NotificationNotFoundError:
        pass


async def test_dismiss_already_dismissed_id_raises(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    item_id = loaded_store.data["items"][0]["id"]
    await loaded_store.async_dismiss(item_id)
    try:
        await loaded_store.async_dismiss(item_id)
        assert False, "expected NotificationNotFoundError"
    except NotificationNotFoundError:
        pass


async def test_dismiss_live_activity_by_tag(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "job1", "live_update": True})
    dismissed = await loaded_store.async_dismiss("job1")
    assert dismissed["tag"] == "job1"
    assert not is_active(loaded_store.data["items"][0])


# --- async_dismiss_all_notifications ---


async def test_dismiss_all_keeps_persistent_returns_cleared(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "a"})
    await loaded_store.async_add_notification("T", "M", {"tag": "b", "persistent": True})
    cleared = await loaded_store.async_dismiss_all_notifications()
    assert {item["tag"] for item in cleared} == {"a"}
    active_tags = {i["tag"] for i in loaded_store.data["items"] if is_active(i)}
    assert active_tags == {"b"}


async def test_dismiss_all_leaves_live_activities_untouched(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "a"})
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "job1", "live_update": True})
    await loaded_store.async_dismiss_all_notifications()
    active_tags = {i["tag"] for i in loaded_store.data["items"] if is_active(i)}
    assert active_tags == {"job1"}


# --- expiry math (_cleanup) — no clock patching needed, timestamps precomputed ---


async def test_cleanup_expires_by_per_item_timeout(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1", "timeout": 100})
    entry = loaded_store.data["items"][0]
    entry["created_at"] = time.time() - 200  # older than its own 100s timeout
    loaded_store._cleanup()
    assert not is_active(loaded_store.data["items"][0])
    assert loaded_store.data["items"][0]["dismiss_reason"] == DISMISS_REASON_TIMEOUT


async def test_cleanup_expires_by_max_age_days_when_no_timeout(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    entry = loaded_store.data["items"][0]
    entry["created_at"] = time.time() - (MAX_AGE_DAYS * 86400 + 10)
    loaded_store._cleanup()
    assert not is_active(loaded_store.data["items"][0])


async def test_cleanup_expires_stale_live_activity(loaded_store):
    await loaded_store.async_upsert_live_activity("T", "M", {"tag": "job1", "live_update": True})
    loaded_store.data["items"][0]["updated_at"] = time.time() - (
        LIVE_ACTIVITY_STALE_HOURS * 3600 + 10
    )
    loaded_store._cleanup()
    entry = loaded_store.data["items"][0]
    assert not is_active(entry)
    assert entry["dismiss_reason"] == DISMISS_REASON_STALE


async def test_cleanup_hard_cap_purges_dismissed_entry(loaded_store):
    """The MAX_ITEMS cap is the one thing that actually drops an entry
    outright. Here the oldest entry is already dismissed, so it's exactly
    who _apply_cap would pick anyway — see the next test for a case where
    preferring dismissed entries actually changes the outcome."""
    await loaded_store.async_add_notification("T", "M", {"tag": "oldest"})
    await loaded_store.async_dismiss(loaded_store.data["items"][0]["id"])
    for i in range(MAX_ITEMS):
        await loaded_store.async_add_notification(f"T{i}", f"M{i}", {"tag": f"t{i}"})
    tags = [i["tag"] for i in loaded_store.data["items"]]
    assert "oldest" not in tags
    assert len(loaded_store.data["items"]) == MAX_ITEMS


async def test_cleanup_hard_cap_prefers_evicting_dismissed_over_active(loaded_store):
    """A dismissed entry gets evicted before an active one, even when the
    active entry is positionally older — active state is protected as long
    as there's a dismissed entry available to sacrifice instead."""
    await loaded_store.async_add_notification("T", "M", {"tag": "old_active"})
    await loaded_store.async_add_notification("T", "M", {"tag": "recent_dismissed"})
    await loaded_store.async_dismiss(loaded_store.data["items"][0]["id"])  # dismisses recent_dismissed
    for i in range(MAX_ITEMS - 1):
        await loaded_store.async_add_notification(f"T{i}", f"M{i}", {"tag": f"t{i}"})

    tags = [i["tag"] for i in loaded_store.data["items"]]
    assert "old_active" in tags  # protected: still active, and a dismissed victim existed
    assert "recent_dismissed" not in tags  # evicted instead, despite being newer
    assert len(loaded_store.data["items"]) == MAX_ITEMS


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
            assert not is_active(store.data["items"][0])
        finally:
            store._unsub_periodic_cleanup()


async def test_periodic_cleanup_noop_when_nothing_expired(hass):
    with freeze_time(dt_util.utcnow()) as freezer:
        store = NotifyDashboardStore(hass)
        await store.async_load()
        try:
            await store.async_add_notification("T", "M", {"tag": "t1"})  # no timeout, far from expiry
            before = list(store.data["items"])
            freezer.tick(CLEANUP_INTERVAL)
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            assert store.data["items"] == before
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


async def test_on_expired_called_for_timeout_expiry(loaded_store_factory):
    on_expired = AsyncMock()
    store = await loaded_store_factory(on_removed=on_expired)
    await store.async_add_notification("T", "M", {"tag": "t1", "timeout": 100})
    store.data["items"][0]["created_at"] = time.time() - 200
    # Any subsequent write runs _cleanup() first, discovering the
    # now-expired entry above.
    await store.async_add_notification("T2", "M2", {})
    on_expired.assert_awaited_once_with(["t1"])


async def test_on_expired_called_for_hard_cap_trim(loaded_store_factory):
    on_expired = AsyncMock()
    store = await loaded_store_factory(on_removed=on_expired)
    await store.async_add_notification("T", "M", {"tag": "oldest"})
    for i in range(MAX_ITEMS):
        await store.async_add_notification(f"T{i}", f"M{i}", {})
    on_expired.assert_awaited_once_with(["oldest"])


async def test_on_expired_called_for_live_activity_staleness(loaded_store_factory):
    on_expired = AsyncMock()
    store = await loaded_store_factory(on_removed=on_expired)
    await store.async_upsert_live_activity("T", "M", {"tag": "job1", "live_update": True})
    store.data["items"][0]["updated_at"] = time.time() - (LIVE_ACTIVITY_STALE_HOURS * 3600 + 10)
    await store.async_add_notification("T2", "M2", {})
    on_expired.assert_awaited_once_with(["job1"])


async def test_on_expired_not_called_when_nothing_expired(loaded_store_factory):
    on_expired = AsyncMock()
    store = await loaded_store_factory(on_removed=on_expired)
    await store.async_add_notification("T", "M", {"tag": "t1"})
    on_expired.assert_not_awaited()


async def test_on_expired_not_called_for_untagged_expiry(loaded_store_factory):
    on_expired = AsyncMock()
    store = await loaded_store_factory(on_removed=on_expired)
    await store.async_add_notification("T", "M", {"timeout": 100})
    store.data["items"][0]["created_at"] = time.time() - 200
    await store.async_add_notification("T2", "M2", {})
    on_expired.assert_not_awaited()


async def test_on_expired_not_called_during_async_load_startup_cleanup(
    hass_storage, loaded_store_factory
):
    """The callback's caller (hass.data[DOMAIN]) isn't populated yet at
    this point in real setup, so async_load's own cleanup pass must not
    invoke it — only later writes/the periodic timer should."""
    expired_at = time.time() - (MAX_AGE_DAYS * 86400 + 10)
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "items": [
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
                    "dismissed_at": None,
                    "dismiss_reason": None,
                }
            ]
        },
    }
    on_expired = AsyncMock()
    store = await loaded_store_factory(on_removed=on_expired)
    assert not is_active(store.data["items"][0])
    on_expired.assert_not_awaited()


async def test_on_expired_called_from_periodic_timer(hass, loaded_store_factory):
    on_expired = AsyncMock()
    with freeze_time(dt_util.utcnow()) as freezer:
        store = await loaded_store_factory(on_removed=on_expired)
        await store.async_add_notification("T", "M", {"tag": "t1", "timeout": 5})
        freezer.tick(timedelta(seconds=10))
        freezer.tick(CLEANUP_INTERVAL)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        on_expired.assert_awaited_once_with(["t1"])


# --- dismissed history — items stay in the list after dismissal, flagged
# via dismissed_at/dismiss_reason instead of being removed ---


async def test_dismiss_records_reason_and_timestamp(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1", "group": "g1"})
    item_id = loaded_store.data["items"][0]["id"]
    await loaded_store.async_dismiss(item_id)
    entry = loaded_store.data["items"][0]
    assert entry["tag"] == "t1"
    assert entry["group"] == "g1"
    assert entry["dismiss_reason"] == DISMISS_REASON_DISMISS
    assert isinstance(entry["dismissed_at"], float)


async def test_dismiss_all_records_dismiss_all_reason(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "a"})
    await loaded_store.async_add_notification("T", "M", {"tag": "b", "persistent": True})
    await loaded_store.async_dismiss_all_notifications()
    reasons = {
        e["tag"]: e["dismiss_reason"] for e in loaded_store.data["items"] if not is_active(e)
    }
    assert reasons == {"a": DISMISS_REASON_DISMISS_ALL}


async def test_clear_by_tag_records_clear_notification_reason_for_both_kinds(loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "notif"})
    await loaded_store.async_upsert_live_activity(
        "T", "M", {"tag": "activity", "live_update": True}
    )
    await loaded_store.async_clear_by_tag("notif")
    await loaded_store.async_clear_by_tag("activity")
    reasons = {e["tag"]: e["dismiss_reason"] for e in loaded_store.data["items"]}
    assert reasons == {
        "notif": DISMISS_REASON_CLEAR_NOTIFICATION,
        "activity": DISMISS_REASON_CLEAR_NOTIFICATION,
    }


async def test_dismissed_entries_stay_newest_first_by_original_position(loaded_store):
    """Dismissing flips fields in place — it doesn't reposition the entry,
    so list order still reflects when it was created/last updated, not when
    it happened to get dismissed."""
    await loaded_store.async_add_notification("T1", "M1", {"tag": "a"})
    await loaded_store.async_add_notification("T2", "M2", {"tag": "b"})
    # Dismiss the OLDER one (b is newer, at index 0; a is older, at index 1).
    await loaded_store.async_dismiss(loaded_store.data["items"][1]["id"])
    tags = [i["tag"] for i in loaded_store.data["items"]]
    assert tags == ["b", "a"]

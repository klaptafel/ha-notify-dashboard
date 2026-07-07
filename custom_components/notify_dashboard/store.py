"""Persistent storage for Notify Dashboard.

One list of Entry items — notifications and live activities together,
told apart by data["live_update"] (the same field the companion app itself
uses, not a separate "kind" label we'd have to keep in sync). Dismissing
(by any means — the close button, clear_notification, timeout, live-
activity staleness) never removes an entry outright: it sets
dismissed_at/dismiss_reason and leaves it in place, so the sensor can
still show recent history. The only thing that actually drops an entry is
the total MAX_ITEMS cap — oldest first, active or dismissed, once there
are simply too many.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    DISMISS_REASON_CLEAR_NOTIFICATION,
    DISMISS_REASON_DISMISS,
    DISMISS_REASON_DISMISS_ALL,
    DISMISS_REASON_STALE,
    DISMISS_REASON_TIMEOUT,
    LIVE_ACTIVITY_STALE_HOURS,
    MAX_AGE_DAYS,
    MAX_ITEMS,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

CLEANUP_INTERVAL = timedelta(seconds=15)


class Entry(TypedDict):
    """A single dashboard item — a notification or a live activity
    (is_live_update tells them apart), active or dismissed (dismissed_at
    is None while active). Kept in the list after dismissal so the sensor
    can show recent history; only the MAX_ITEMS cap ever drops one outright.

    tag/group/timeout are deliberately *not* fields here even though every
    entry has them in practice — they're always in `data` already (the
    companion-app payload itself), so a second top-level copy would be
    pure duplication (same reasoning as is_live_update/is_persistent below,
    just for entries instead of dismiss reasons). Use entry_tag/entry_group/
    entry_timeout to read them.
    """

    id: str
    title: str | None
    message: str
    data: dict[str, Any]
    created_at: float
    updated_at: float
    dismissed_at: float | None
    dismiss_reason: str | None


class NotifyDashboardStoreData(TypedDict):
    """Shape persisted to/restored from the HA Store."""

    items: list[Entry]


class NotificationNotFoundError(Exception):
    """No *active* notification or live activity found with this id."""


class NotificationNotDismissableError(Exception):
    """Item exists, but may not be dismissed manually.

    Applies only to persistent-marked notifications — never to live
    activities, which stay dismissable via the same close button
    regardless of `persistent` (a deliberate, pre-existing asymmetry: a
    live activity's own lifecycle is normally ended via clear_notification,
    but the manual close button always works too).
    """


def entry_tag(entry: Entry) -> str | None:
    return entry["data"].get("tag")


def entry_group(entry: Entry) -> str | None:
    return entry["data"].get("group")


def entry_timeout(entry: Entry) -> float | None:
    return entry["data"].get("timeout")


def is_live_update(entry: Entry) -> bool:
    """Same field the companion app itself uses to mark a live activity —
    no separate "kind" concept invented on top of it."""
    return bool(entry["data"].get("live_update"))


def is_persistent(entry: Entry) -> bool:
    """persistent only blocks manual dismiss for notifications — a live
    activity stays dismissable via the close button regardless, so that
    exception lives here rather than being re-derived at each call site."""
    return not is_live_update(entry) and bool(entry["data"].get("persistent"))


def is_active(entry: Entry) -> bool:
    return entry["dismissed_at"] is None


class NotifyDashboardStore:
    """Wraps a single HA Store holding every notification/live activity,
    active and recently-dismissed, in one recency-capped list."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_removed: Callable[[list[str]], Awaitable[None]] | None = None,
    ) -> None:
        self.hass = hass
        self._store: Store[NotifyDashboardStoreData] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: NotifyDashboardStoreData = {"items": []}
        self._unsub_periodic_cleanup: CALLBACK_TYPE | None = None
        # Called with the tags of anything that stops being active, by any
        # means — dismiss/dismiss_all, automatic cleanup (age/timeout
        # expiry, live-activity staleness, the MAX_ITEMS hard cap — see
        # _cleanup), and an explicit clear_notification sent straight to
        # notify.dashboard (see async_clear_by_tag). One mechanism for all
        # of them, since they all disappear from the dashboard exactly like
        # each other and need the same mirror-forwarding treatment. Not
        # invoked from async_load()'s startup cleanup: hass.data[DOMAIN]
        # (which the caller's callback needs) isn't populated yet then.
        self._on_removed = on_removed

    @property
    def data(self) -> NotifyDashboardStoreData:
        return self._data

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored and "items" in stored:
            self._data = stored
        # else: either genuinely empty, or persisted under the old
        # notifications/live_activities/dismissed shape from a version that
        # was never actually released — starting fresh instead of writing
        # migration logic for a schema nobody depends on.
        self._cleanup()
        self._start_periodic_cleanup()

    def _start_periodic_cleanup(self) -> None:
        """Cleans up expired items without needing a write for it —
        otherwise an expired notification would just stay visible until
        something else happens to get saved."""
        if self._unsub_periodic_cleanup is not None:
            return

        async def _periodic(_now: datetime) -> None:
            expired_tags, anything_changed = self._cleanup()
            if anything_changed:
                await self._store.async_save(self._data)
                async_dispatcher_send(self.hass, SIGNAL_UPDATE)
            await self._notify_removed(expired_tags)

        self._unsub_periodic_cleanup = async_track_time_interval(self.hass, _periodic, CLEANUP_INTERVAL)

    async def _async_save(self) -> None:
        expired_tags, _ = self._cleanup()
        await self._store.async_save(self._data)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        await self._notify_removed(expired_tags)

    async def _notify_removed(self, tags: list[str]) -> None:
        if tags and self._on_removed:
            await self._on_removed(tags)

    def _find_active_by_tag(self, tag: str) -> Entry | None:
        return next(
            (e for e in self._data["items"] if entry_tag(e) == tag and is_active(e)), None
        )

    def _cleanup(self) -> tuple[list[str], bool]:
        """Dismiss (in place) anything past its own expiry, then hard-purge
        down to MAX_ITEMS via _apply_cap.

        Returns (changed_tags, anything_changed). changed_tags is only the
        subset of touched entries that had a tag — the only thing
        mirror_dismiss_to forwarding (tag-keyed) can act on. anything_changed
        reflects every mutation regardless of tag: an *untagged* notification
        timing out still needs a save + dispatcher signal, or it only ever
        stops showing after something else happens to trigger an update
        (confirmed: this was a real bug — the periodic timer used to gate
        the save/dispatch on changed_tags being non-empty).
        """
        now = time.time()
        max_age = MAX_AGE_DAYS * 86400
        stale_after = LIVE_ACTIVITY_STALE_HOURS * 3600
        changed_tags: list[str] = []
        anything_changed = False

        for entry in self._data["items"]:
            if not is_active(entry):
                continue
            if is_live_update(entry):
                expired = now - entry["updated_at"] >= stale_after
                reason = DISMISS_REASON_STALE
            else:
                timeout = entry_timeout(entry)
                expires_at = entry["created_at"] + timeout if timeout else entry["created_at"] + max_age
                expired = now >= expires_at
                reason = DISMISS_REASON_TIMEOUT
            if expired:
                entry["dismissed_at"] = now
                entry["dismiss_reason"] = reason
                anything_changed = True
                if tag := entry_tag(entry):
                    changed_tags.append(tag)

        cap_tags, cap_changed = self._apply_cap()
        changed_tags.extend(cap_tags)
        return changed_tags, anything_changed or cap_changed

    def _apply_cap(self) -> tuple[list[str], bool]:
        """Hard-purge down to MAX_ITEMS — the one and only place an entry
        actually leaves the list outright.

        Prefers evicting already-dismissed entries (oldest first) over
        active ones — active items are the actually relevant state,
        dismissed ones are just a nice-to-have history. Active entries are
        only evicted once there aren't enough dismissed ones left to make
        room. Returns (evicted_tags, anything_evicted) — evicted_tags is
        only the still-active, tagged subset (for mirror_dismiss_to);
        anything_evicted covers every eviction regardless of tag/state.
        """
        items = self._data["items"]
        overflow = len(items) - MAX_ITEMS
        if overflow <= 0:
            return [], False

        # items is newest-first, so within each bucket built by iterating it
        # in order, the tail is already "oldest of that kind" — no separate
        # reverse pass needed.
        dismissed: list[Entry] = []
        active: list[Entry] = []
        for entry in items:
            (dismissed if not is_active(entry) else active).append(entry)

        to_evict = dismissed[-overflow:]
        still_needed = overflow - len(to_evict)
        if still_needed > 0:
            to_evict += active[-still_needed:]

        evict_ids = {e["id"] for e in to_evict}
        evicted_tags = [tag for e in to_evict if is_active(e) and (tag := entry_tag(e))]
        self._data["items"] = [e for e in items if e["id"] not in evict_ids]
        return evicted_tags, bool(to_evict)

    async def async_add_notification(
        self, title: str | None, message: str, data: dict[str, Any]
    ) -> None:
        tag = data.get("tag")
        now = time.time()
        if tag:
            # Tag-replace = full replacement, no field merge — only ever
            # replaces a currently-active entry (whatever kind); an old,
            # already-dismissed entry with the same tag stays in history.
            existing = self._find_active_by_tag(tag)
            if existing is not None:
                self._data["items"].remove(existing)
        entry: Entry = {
            "id": str(uuid.uuid4()),
            "title": title,
            "message": message,
            "data": data,
            "created_at": now,
            "updated_at": now,
            "dismissed_at": None,
            "dismiss_reason": None,
        }
        self._data["items"].insert(0, entry)
        await self._async_save()

    async def async_upsert_live_activity(
        self, title: str | None, message: str, data: dict[str, Any]
    ) -> None:
        """Ending a live activity isn't a special progress value — checked
        against the actual companion-app docs, the documented way to end
        one is the exact same mechanism as a regular notification:
        clear_notification + tag (see async_clear_by_tag)."""
        tag = data.get("tag")
        if not tag:
            return  # Without a tag we can't track/update a live activity.
        # is_live_update() is the sole kind discriminator everywhere else in
        # the store — guarantee it's actually true for anything reaching
        # the store through this method, rather than trusting every caller
        # to have already set it (in practice notify.py always does, since
        # that's its own routing condition, but this removes the footgun).
        data = {**data, "live_update": True}
        now = time.time()
        existing = self._find_active_by_tag(tag)
        created_at = existing["created_at"] if existing is not None else now
        if existing is not None:
            self._data["items"].remove(existing)
        entry: Entry = {
            "id": tag,
            "title": title,
            "message": message,
            "data": data,
            "created_at": created_at,
            "updated_at": now,
            "dismissed_at": None,
            "dismiss_reason": None,
        }
        self._data["items"].insert(0, entry)
        await self._async_save()

    async def async_clear_by_tag(self, tag: str) -> None:
        """The companion-app-style clear_notification command, routed here
        from notify.py — the documented way to end both a regular
        notification and a live activity sharing the same tag. Reports the
        tag for mirror-forwarding only when something was actually active —
        a clear_notification for a tag that was never here (or already
        inactive) shouldn't create a phantom forward.
        """
        entry = self._find_active_by_tag(tag)
        if entry is not None:
            entry["dismissed_at"] = time.time()
            entry["dismiss_reason"] = DISMISS_REASON_CLEAR_NOTIFICATION
        await self._async_save()
        if entry is not None:
            await self._notify_removed([tag])

    async def async_dismiss(self, item_id: str) -> Entry:
        """Dismiss a notification or a live activity, based on id.

        For notifications, id is a uuid; for live activities, id equals the
        tag. Persistent-marked notifications can't be dismissed
        (NotificationNotDismissableError) — live activities always can,
        regardless of `persistent`. An unknown or already-inactive id
        raises NotificationNotFoundError — the caller (the dismiss service)
        translates that into a clear error message instead of silently
        doing nothing.
        """
        match = next(
            (e for e in self._data["items"] if e["id"] == item_id and is_active(e)), None
        )
        if match is None:
            raise NotificationNotFoundError(item_id)
        if is_persistent(match):
            raise NotificationNotDismissableError(item_id)

        match["dismissed_at"] = time.time()
        match["dismiss_reason"] = DISMISS_REASON_DISMISS
        await self._async_save()
        if tag := entry_tag(match):
            await self._notify_removed([tag])
        return match

    async def async_dismiss_all_notifications(self) -> list[Entry]:
        """Dismiss all active, non-persistent, non-live-update entries —
        live activities are left untouched (same as before).

        Returns the newly-dismissed items — same shape as async_dismiss.
        """
        now = time.time()
        cleared = []
        for entry in self._data["items"]:
            if not is_active(entry) or is_live_update(entry) or is_persistent(entry):
                continue
            entry["dismissed_at"] = now
            entry["dismiss_reason"] = DISMISS_REASON_DISMISS_ALL
            cleared.append(entry)
        await self._async_save()
        tags = [tag for item in cleared if (tag := entry_tag(item))]
        await self._notify_removed(tags)
        return cleared

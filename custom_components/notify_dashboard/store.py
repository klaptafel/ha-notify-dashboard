"""Persistent storage for Notify Dashboard.

Keeps two collections (see design doc):
- notifications: discrete alerts, tag-replace = full replacement, expire
  after their own `timeout` or otherwise after MAX_AGE_DAYS, hard capped at
  MAX_NOTIFICATIONS.
- live_activities: keyed by tag, always 1 current state, expires after
  LIVE_ACTIVITY_STALE_HOURS without an update (pushed back on every update).
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
    DISMISS_REASON_CAPACITY,
    DISMISS_REASON_CLEAR_NOTIFICATION,
    DISMISS_REASON_DISMISS,
    DISMISS_REASON_DISMISS_ALL,
    DISMISS_REASON_STALE,
    DISMISS_REASON_TIMEOUT,
    LIVE_ACTIVITY_STALE_HOURS,
    MAX_AGE_DAYS,
    MAX_DISMISSED,
    MAX_NOTIFICATIONS,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

CLEANUP_INTERVAL = timedelta(seconds=15)


class NotificationEntry(TypedDict):
    """A single discrete notification, as stored and as sent to the sensor."""

    id: str
    tag: str | None
    group: str | None
    title: str | None
    message: str
    data: dict[str, Any]
    created_at: float
    updated_at: float
    timeout: float | None


class LiveActivityEntry(TypedDict):
    """A live activity's current state, keyed by tag in the store."""

    id: str
    tag: str
    title: str | None
    message: str
    data: dict[str, Any]
    updated_at: float


class DismissedEntry(TypedDict):
    """A record of something that left the store, for the sensor's history.

    Deliberately lean (no message, no full data dict) — enough to recognize
    *what* was dismissed and *why*, not a second full copy of its content.
    `live_update` is the same field the companion app itself uses to mark a
    live activity — no separate "kind" concept invented on top of it.
    `reason` is always one of the DISMISS_REASON_* constants.
    """

    id: str
    tag: str | None
    group: str | None
    title: str | None
    live_update: bool
    reason: str
    dismissed_at: float


class NotifyDashboardStoreData(TypedDict):
    """Shape persisted to/restored from the HA Store."""

    notifications: list[NotificationEntry]
    live_activities: dict[str, LiveActivityEntry]
    dismissed: list[DismissedEntry]


class NotificationNotFoundError(Exception):
    """No notification or live activity found with this id."""


class NotificationNotDismissableError(Exception):
    """Item exists, but may not be dismissed manually.

    Applies only to persistent-marked notifications. Live activities ARE
    dismissable this way (same close button as a regular notification) —
    that's a deliberate choice, separate from how clear_notification
    already handles ending them on their own (see async_clear_by_tag).
    """


def is_persistent(entry: NotificationEntry) -> bool:
    return bool(entry.get("data", {}).get("persistent"))


def live_activities_list(data: NotifyDashboardStoreData) -> list[LiveActivityEntry]:
    """live_activities is keyed by tag internally, but every consumer
    (sensor attributes, diagnostics) wants it as a plain list — shared here
    instead of each one re-deriving list(data["live_activities"].values())."""
    return list(data["live_activities"].values())


class NotifyDashboardStore:
    """Wraps a single HA Store holding notifications + live_activities."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_removed: Callable[[list[str]], Awaitable[None]] | None = None,
    ) -> None:
        self.hass = hass
        self._store: Store[NotifyDashboardStoreData] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: NotifyDashboardStoreData = {
            "notifications": [],
            "live_activities": {},
            "dismissed": [],
        }
        self._unsub_periodic_cleanup: CALLBACK_TYPE | None = None
        # Called with the tags of anything that leaves the store, by any
        # means — dismiss/dismiss_all, automatic cleanup (age/timeout
        # expiry, live-activity staleness, the MAX_NOTIFICATIONS hard cap —
        # see _cleanup), and an explicit clear_notification sent straight to
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
        if stored:
            # dismissed is new — a store saved before it existed won't have
            # the key at all, and self._data is read as NotifyDashboardStoreData
            # elsewhere without a .get() fallback.
            stored.setdefault("dismissed", [])
            self._data = stored
        self._cleanup()
        self._start_periodic_cleanup()

    def _start_periodic_cleanup(self) -> None:
        """Cleans up expired items without needing a write for it —
        otherwise an expired notification would just stay visible until
        something else happens to get saved."""
        if self._unsub_periodic_cleanup is not None:
            return

        async def _periodic(_now: datetime) -> None:
            before = (len(self._data["notifications"]), len(self._data["live_activities"]))
            expired_tags = self._cleanup()
            after = (len(self._data["notifications"]), len(self._data["live_activities"]))
            if before != after:
                await self._store.async_save(self._data)
                async_dispatcher_send(self.hass, SIGNAL_UPDATE)
            await self._notify_removed(expired_tags)

        self._unsub_periodic_cleanup = async_track_time_interval(self.hass, _periodic, CLEANUP_INTERVAL)

    async def _async_save(self) -> None:
        expired_tags = self._cleanup()
        await self._store.async_save(self._data)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        await self._notify_removed(expired_tags)

    async def _notify_removed(self, tags: list[str]) -> None:
        if tags and self._on_removed:
            await self._on_removed(tags)

    def _cleanup(self) -> list[str]:
        """Remove expired notifications and stale live activities.

        Returns the tags of anything actually removed — see _on_removed.
        """
        now = time.time()
        max_age = MAX_AGE_DAYS * 86400
        stale_after = LIVE_ACTIVITY_STALE_HOURS * 3600

        kept = []
        expired_tags: list[str] = []
        for item in self._data["notifications"]:
            timeout = item.get("timeout")
            expires_at = item["created_at"] + timeout if timeout else item["created_at"] + max_age
            if now < expires_at:
                kept.append(item)
            else:
                self._record_dismissed(
                    id=item["id"],
                    tag=item.get("tag"),
                    title=item.get("title"),
                    data=item.get("data", {}),
                    reason=DISMISS_REASON_TIMEOUT,
                )
                if tag := item.get("tag"):
                    expired_tags.append(tag)
        # Already newest-first (insert(0, ...) on add) — no resort needed.
        # Hard ceiling — oldest goes first, regardless of age (spam safety
        # net) — capacity-trimmed notifications disappear from the
        # dashboard exactly the same way age-expired ones do, so they get
        # the same mirror-forwarding treatment.
        for item in kept[MAX_NOTIFICATIONS:]:
            self._record_dismissed(
                id=item["id"],
                tag=item.get("tag"),
                title=item.get("title"),
                data=item.get("data", {}),
                reason=DISMISS_REASON_CAPACITY,
            )
            if tag := item.get("tag"):
                expired_tags.append(tag)
        self._data["notifications"] = kept[:MAX_NOTIFICATIONS]

        live = self._data["live_activities"]
        still_live: dict[str, LiveActivityEntry] = {}
        for tag, activity in live.items():
            if now - activity["updated_at"] < stale_after:
                still_live[tag] = activity
            else:
                self._record_dismissed(
                    id=activity["id"],
                    tag=activity.get("tag"),
                    title=activity.get("title"),
                    data=activity.get("data", {}),
                    reason=DISMISS_REASON_STALE,
                )
                expired_tags.append(tag)
        self._data["live_activities"] = still_live

        return expired_tags

    def _remove_notifications_by_tag(self, tag: str) -> None:
        self._data["notifications"] = [
            n for n in self._data["notifications"] if n.get("tag") != tag
        ]

    def _record_dismissed(
        self,
        *,
        id: str,
        tag: str | None,
        title: str | None,
        data: dict[str, Any],
        reason: str,
    ) -> None:
        """Append to the dismissed-history log, newest-first, capped at
        MAX_DISMISSED — called from every removal path, right before the
        item itself is actually dropped (its content is otherwise gone).

        group/live_update are read straight from the item's own stored
        `data` dict rather than passed in separately — both NotificationEntry
        and LiveActivityEntry already carry it, so there's no need for a
        second, independently-tracked notion of "what kind is this."
        """
        entry: DismissedEntry = {
            "id": id,
            "tag": tag,
            "group": data.get("group"),
            "title": title,
            "live_update": bool(data.get("live_update")),
            "reason": reason,
            "dismissed_at": time.time(),
        }
        self._data["dismissed"].insert(0, entry)
        self._data["dismissed"] = self._data["dismissed"][:MAX_DISMISSED]

    async def async_add_notification(
        self, title: str | None, message: str, data: dict[str, Any]
    ) -> None:
        tag = data.get("tag")
        now = time.time()
        entry: NotificationEntry = {
            "id": str(uuid.uuid4()),
            "tag": tag,
            "group": data.get("group"),
            "title": title,
            "message": message,
            "data": data,
            "created_at": now,
            "updated_at": now,
            "timeout": data.get("timeout"),
        }
        if tag:
            # Tag-replace = full replacement, no field merge (option 1).
            self._remove_notifications_by_tag(tag)
        self._data["notifications"].insert(0, entry)
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
        self._data["live_activities"][tag] = {
            "id": tag,
            "tag": tag,
            "title": title,
            "message": message,
            "data": data,
            "updated_at": time.time(),
        }
        await self._async_save()

    async def async_clear_by_tag(self, tag: str) -> None:
        """The companion-app-style clear_notification command, routed here
        from notify.py — the documented way to end both a regular
        notification and a live activity. Reports the tag for mirror-
        forwarding only when something was actually removed — a
        clear_notification for a tag that was never here (or already gone)
        shouldn't create a phantom forward.
        """
        matched_notification = next(
            (n for n in self._data["notifications"] if n.get("tag") == tag), None
        )
        matched_activity = self._data["live_activities"].get(tag)
        if matched_notification is not None:
            self._record_dismissed(
                id=matched_notification["id"],
                tag=tag,
                title=matched_notification.get("title"),
                data=matched_notification.get("data", {}),
                reason=DISMISS_REASON_CLEAR_NOTIFICATION,
            )
        if matched_activity is not None:
            self._record_dismissed(
                id=matched_activity["id"],
                tag=tag,
                title=matched_activity.get("title"),
                data=matched_activity.get("data", {}),
                reason=DISMISS_REASON_CLEAR_NOTIFICATION,
            )
        self._remove_notifications_by_tag(tag)
        self._data["live_activities"].pop(tag, None)
        await self._async_save()
        if matched_notification is not None or matched_activity is not None:
            await self._notify_removed([tag])

    async def async_dismiss(self, item_id: str) -> NotificationEntry | LiveActivityEntry:
        """Remove a notification or a live activity, based on id.

        For notifications, id is a uuid; for live activities, id equals the
        tag. Persistent-marked notifications can't be dismissed
        (NotificationNotDismissableError); an unknown id raises
        NotificationNotFoundError — the caller (the dismiss service)
        translates that into a clear error message instead of silently
        doing nothing.
        """
        notifications = self._data["notifications"]
        match = next((n for n in notifications if n["id"] == item_id), None)
        if match is not None:
            if is_persistent(match):
                raise NotificationNotDismissableError(item_id)
            notifications.remove(match)
            self._record_dismissed(
                id=match["id"],
                tag=match.get("tag"),
                title=match.get("title"),
                data=match.get("data", {}),
                reason=DISMISS_REASON_DISMISS,
            )
            await self._async_save()
            if tag := match.get("tag"):
                await self._notify_removed([tag])
            return match

        if item_id in self._data["live_activities"]:
            item = self._data["live_activities"].pop(item_id)
            self._record_dismissed(
                id=item["id"],
                tag=item.get("tag"),
                title=item.get("title"),
                data=item.get("data", {}),
                reason=DISMISS_REASON_DISMISS,
            )
            await self._async_save()
            await self._notify_removed([item["tag"]])
            return item

        raise NotificationNotFoundError(item_id)

    async def async_dismiss_all_notifications(self) -> list[NotificationEntry]:
        """Remove all non-persistent notifications.

        Returns the removed items — same shape as async_dismiss.
        """
        kept = []
        cleared = []
        for n in self._data["notifications"]:
            if is_persistent(n):
                kept.append(n)
            else:
                cleared.append(n)
        self._data["notifications"] = kept
        for item in cleared:
            self._record_dismissed(
                id=item["id"],
                tag=item.get("tag"),
                title=item.get("title"),
                data=item.get("data", {}),
                reason=DISMISS_REASON_DISMISS_ALL,
            )
        await self._async_save()
        tags = [tag for item in cleared if (tag := item.get("tag"))]
        await self._notify_removed(tags)
        return cleared

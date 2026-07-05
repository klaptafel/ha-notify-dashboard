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
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    LIVE_ACTIVITY_STALE_HOURS,
    MAX_AGE_DAYS,
    MAX_NOTIFICATIONS,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

CLEANUP_INTERVAL = timedelta(seconds=15)


class NotificationNotFoundError(Exception):
    """No notification or live activity found with this id."""


class NotificationNotDismissableError(Exception):
    """Item exists, but may not be dismissed manually.

    Applies only to persistent-marked notifications. Live activities ARE
    dismissable this way (same close button as a regular notification) —
    that's a deliberate choice, separate from how clear_notification/
    progress: -1 already handle ending them on their own.
    """


class NotifyDashboardStore:
    """Wraps a single HA Store holding notifications + live_activities."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {"notifications": [], "live_activities": {}}
        self._unsub_periodic_cleanup = None

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self._data = stored
        self._cleanup()
        self._start_periodic_cleanup()

    def _start_periodic_cleanup(self) -> None:
        """Cleans up expired items without needing a write for it —
        otherwise an expired notification would just stay visible until
        something else happens to get saved."""
        if self._unsub_periodic_cleanup is not None:
            return

        async def _periodic(_now) -> None:
            before = (len(self._data["notifications"]), len(self._data["live_activities"]))
            self._cleanup()
            after = (len(self._data["notifications"]), len(self._data["live_activities"]))
            if before != after:
                await self._store.async_save(self._data)
                async_dispatcher_send(self.hass, SIGNAL_UPDATE)

        self._unsub_periodic_cleanup = async_track_time_interval(self.hass, _periodic, CLEANUP_INTERVAL)

    async def _async_save(self) -> None:
        self._cleanup()
        await self._store.async_save(self._data)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    def _cleanup(self) -> None:
        """Remove expired notifications and stale live activities."""
        now = time.time()
        max_age = MAX_AGE_DAYS * 86400
        stale_after = LIVE_ACTIVITY_STALE_HOURS * 3600

        kept = []
        for item in self._data["notifications"]:
            timeout = item.get("timeout")
            expires_at = item["created_at"] + timeout if timeout else item["created_at"] + max_age
            if now < expires_at:
                kept.append(item)
        # Already newest-first (insert(0, ...) on add) — no resort needed.
        # Hard ceiling — oldest goes first, regardless of age (spam safety net).
        self._data["notifications"] = kept[:MAX_NOTIFICATIONS]

        live = self._data["live_activities"]
        self._data["live_activities"] = {
            tag: item for tag, item in live.items() if now - item["updated_at"] < stale_after
        }

    def _remove_notifications_by_tag(self, tag: str) -> None:
        self._data["notifications"] = [
            n for n in self._data["notifications"] if n.get("tag") != tag
        ]

    async def async_add_notification(self, title: str | None, message: str, data: dict) -> None:
        tag = data.get("tag")
        now = time.time()
        entry = {
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

    async def async_upsert_live_activity(self, title: str | None, message: str, data: dict) -> None:
        tag = data.get("tag")
        if not tag:
            return  # Without a tag we can't track/update a live activity.
        now = time.time()
        # progress: -1 = explicit "done" signal, same effect as clear_notification.
        if data.get("progress") == -1:
            self._data["live_activities"].pop(tag, None)
        else:
            self._data["live_activities"][tag] = {
                "id": tag,
                "tag": tag,
                "title": title,
                "message": message,
                "data": data,
                "updated_at": now,
            }
        await self._async_save()

    async def async_clear_by_tag(self, tag: str) -> None:
        self._remove_notifications_by_tag(tag)
        self._data["live_activities"].pop(tag, None)
        await self._async_save()

    async def async_dismiss(self, item_id: str) -> dict:
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
            if match.get("data", {}).get("persistent"):
                raise NotificationNotDismissableError(item_id)
            notifications.remove(match)
            await self._async_save()
            return match

        if item_id in self._data["live_activities"]:
            item = self._data["live_activities"].pop(item_id)
            await self._async_save()
            return item

        raise NotificationNotFoundError(item_id)

    async def async_dismiss_all_notifications(self) -> list[dict]:
        """Remove all non-persistent notifications.

        Returns the removed items — same shape as async_dismiss — so the
        caller can apply mirror_dismiss_to to them just like a single
        dismiss, now for the bulk variant too.
        """
        kept = []
        cleared = []
        for n in self._data["notifications"]:
            if n.get("data", {}).get("persistent"):
                kept.append(n)
            else:
                cleared.append(n)
        self._data["notifications"] = kept
        await self._async_save()
        return cleared

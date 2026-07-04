"""Persistent storage for Notify Dashboard.

Houdt twee collecties bij (zie ontwerpdocument):
- notifications: discrete meldingen, tag-replace = volledige vervanging,
  verlopen na eigen `timeout` of anders na MAX_AGE_DAYS, hard capped op
  MAX_NOTIFICATIONS.
- live_activities: keyed op tag, altijd 1 actuele state, verlopen na
  LIVE_ACTIVITY_STALE_HOURS zonder update (schuift op bij elke update).
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
        """Ruimt verlopen items op zonder dat daar een schrijfactie voor nodig
        is — anders blijft een verlopen melding gewoon zichtbaar staan tot
        er toevallig weer iets anders wordt opgeslagen."""
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
        """Verwijder verlopen notifications en stale live activities."""
        now = time.time()
        max_age = MAX_AGE_DAYS * 86400
        stale_after = LIVE_ACTIVITY_STALE_HOURS * 3600

        kept = []
        for item in self._data["notifications"]:
            timeout = item.get("timeout")
            expires_at = item["created_at"] + timeout if timeout else item["created_at"] + max_age
            if now < expires_at:
                kept.append(item)
        # Hard plafond — oudste eruit, ongeacht leeftijd (spam-vangnet).
        kept.sort(key=lambda i: i["created_at"], reverse=True)
        self._data["notifications"] = kept[:MAX_NOTIFICATIONS]

        live = self._data["live_activities"]
        self._data["live_activities"] = {
            tag: item for tag, item in live.items() if now - item["updated_at"] < stale_after
        }

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
            # Tag-replace = volledige vervanging, geen veld-merge (optie 1).
            self._data["notifications"] = [
                n for n in self._data["notifications"] if n.get("tag") != tag
            ]
        self._data["notifications"].insert(0, entry)
        await self._async_save()

    async def async_upsert_live_activity(self, title: str | None, message: str, data: dict) -> None:
        tag = data.get("tag")
        if not tag:
            return  # Zonder tag kunnen we geen live activity bijhouden/updaten.
        now = time.time()
        # progress: -1 = expliciet "klaar"-signaal, zelfde effect als clear_notification.
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
        self._data["notifications"] = [
            n for n in self._data["notifications"] if n.get("tag") != tag
        ]
        self._data["live_activities"].pop(tag, None)
        await self._async_save()

    async def async_dismiss(self, item_id: str) -> dict | None:
        """Verwijder een notification óf een live activity, op basis van id.

        Voor notifications is id een uuid; voor live activities is id gelijk
        aan de tag (zie async_upsert_live_activity). Gebruiker kan dus beide
        gewoon wegklikken — alleen `persistent: true` blokkeert dit nog
        (uitsluitend van toepassing op notifications).
        """
        for n in self._data["notifications"]:
            if n["id"] == item_id and not n.get("data", {}).get("persistent"):
                self._data["notifications"] = [
                    x for x in self._data["notifications"] if x["id"] != item_id
                ]
                await self._async_save()
                return n

        if item_id in self._data["live_activities"]:
            item = self._data["live_activities"].pop(item_id)
            await self._async_save()
            return item

        return None

    async def async_dismiss_all_notifications(self) -> None:
        self._data["notifications"] = [
            n for n in self._data["notifications"] if n.get("data", {}).get("persistent")
        ]
        await self._async_save()

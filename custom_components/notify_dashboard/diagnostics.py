"""Diagnostics support for Notify Dashboard.

Reports config + aggregate counts/timestamps only — deliberately never the
actual title/message/data content of notifications or live activities.
Diagnostics downloads are a live, user-facing feature (Settings > Devices &
Services > integration > "Download diagnostics") that people commonly paste
into public GitHub issues; notification/live-activity content is arbitrary
user- or companion-app-authored data with no fixed field list to redact, so
omitting it entirely (rather than trying to redact it) is the only safe
default.
"""
from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import get_domain_data
from .store import Entry, is_active, is_live_update, is_persistent


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    domain_data = get_domain_data(hass)
    items = domain_data["store"].data["items"]

    # Single pass — these three buckets are mutually exclusive by
    # construction (is_active x is_live_update), so no need to filter the
    # same list three separate times.
    notifications: list[Entry] = []
    live_activities: list[Entry] = []
    dismissed: list[Entry] = []
    for item in items:
        if not is_active(item):
            dismissed.append(item)
        elif is_live_update(item):
            live_activities.append(item)
        else:
            notifications.append(item)

    return {
        "config": {
            "mirror_dismiss_to": domain_data["mirror_dismiss_to"],
        },
        "notifications": {
            "count": len(notifications),
            "persistent_count": sum(1 for n in notifications if is_persistent(n)),
            "oldest_created_at": min(
                (n["created_at"] for n in notifications), default=None
            ),
            "newest_created_at": max(
                (n["created_at"] for n in notifications), default=None
            ),
        },
        "live_activities": {
            "count": len(live_activities),
            "oldest_updated_at": min(
                (a["updated_at"] for a in live_activities), default=None
            ),
            "newest_updated_at": max(
                (a["updated_at"] for a in live_activities), default=None
            ),
        },
        "dismissed": {
            "count": len(dismissed),
            # dismissed only ever holds entries where is_active() is False,
            # i.e. dismissed_at is guaranteed set — the cast just tells the
            # type checker what's already true at runtime, not a real check.
            "newest_dismissed_at": max(
                (cast(float, d["dismissed_at"]) for d in dismissed), default=None
            ),
        },
    }

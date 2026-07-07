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

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import get_domain_data
from .store import is_persistent, live_activities_list


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    domain_data = get_domain_data(hass)
    store_data = domain_data["store"].data
    notifications = store_data["notifications"]
    live_activities = live_activities_list(store_data)

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
            "count": len(store_data["dismissed"]),
            "newest_dismissed_at": max(
                (d["dismissed_at"] for d in store_data["dismissed"]), default=None
            ),
        },
    }

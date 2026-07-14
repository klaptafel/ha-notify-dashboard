"""Constants for Notify Dashboard."""
from __future__ import annotations

from homeassistant.helpers import config_validation as cv

DOMAIN = "notify_dashboard"

# Config
CONF_MIRROR_DISMISS_TO = "mirror_dismiss_to"
# Only entity domain allowed for mirror_dismiss_to: shared between the
# YAML validation (__init__.py) and the UI selector (config_flow.py).
NOTIFY_ENTITY_DOMAIN = "notify"
# mirror_dismiss_to targets can be a notify *entity* (dispatched via the
# generic notify.send_message action) or a legacy notify *service*, e.g. a
# YAML `notify: - platform: group`, which registers a raw service with no
# entity at all. send_message itself is the generic dispatch mechanism, not
# a real target: it always needs its own target selector, so it's excluded
# from the raw-service picker in config_flow.py.
RESERVED_NOTIFY_SERVICES = {"send_message"}


def is_mirror_entity(target: str) -> bool:
    """Entity ids always contain a dot (`notify.xxx`); legacy service names
    never do (`xxx`): the one rule __init__.py's dispatch, this module's
    own validator below, and config_flow.py's picker all share to tell the
    two kinds of mirror_dismiss_to target apart."""
    return "." in target


def validate_mirror_target(value: str) -> str:
    """A mirror_dismiss_to entry is either a notify entity id or a bare
    legacy notify service name (e.g. "family_notifications" from a YAML
    `notify: - platform: group`, that one has no entity at all). Shared
    by __init__.py's CONFIG_SCHEMA (the YAML path) and config_flow.py's
    options/config flow schema (the UI path): both need the exact same
    rule, not just the same intent independently reimplemented.
    """
    if is_mirror_entity(value):
        return cv.entity_domain(NOTIFY_ENTITY_DOMAIN)(cv.entity_id(value))
    return cv.slug(value)

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.notifications"

# Retention. One unified cap across active + dismissed entries
# (store.py's Entry), replacing what used to be three
# separate limits (a notification cap, a live-activity staleness window,
# and a separate dismissed-log cap). Already-dismissed entries are evicted
# first (oldest first); active entries are only dropped once there aren't
# enough dismissed ones left to make room; see store.py's _apply_cap.
MAX_ITEMS = 50
MAX_AGE_DAYS = 30
LIVE_ACTIVITY_STALE_HOURS = 8

# Dismiss reasons (store.py's Entry.dismiss_reason): shared constants so
# store.py/tests all use the same literal strings instead of independently
# retyping them. No separate "kind" concept: whether an entry is a live
# activity is just its own live_update flag, read straight from the data
# it already carries.
DISMISS_REASON_DISMISS = "dismiss"
DISMISS_REASON_DISMISS_ALL = "dismiss_all"
DISMISS_REASON_CLEAR_NOTIFICATION = "clear_notification"
DISMISS_REASON_TIMEOUT = "timeout"
DISMISS_REASON_STALE = "stale"

# Command messages that must never be shown as content
COMMAND_MESSAGES = {"clear_notification", "TTS", "delete_alert", "remove_channel"}

# Events / signals
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
SIGNAL_UPDATE = f"{DOMAIN}_update"

# Services
SERVICE_DISMISS = "dismiss"
SERVICE_DISMISS_ALL = "dismiss_all"
SERVICE_FIRE_ACTION = "fire_action"
ATTR_ID = "id"
ATTR_ACTION = "action"
ATTR_ACTION_DATA = "action_data"
ATTR_TAG = "tag"

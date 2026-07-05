"""Constants for Notify Dashboard."""

DOMAIN = "notify_dashboard"

# Config
CONF_MIRROR_DISMISS_TO = "mirror_dismiss_to"
# Enige entity-domain toegestaan voor mirror_dismiss_to — gedeeld tussen de
# YAML-validatie (__init__.py) en de UI-selector (config_flow.py).
NOTIFY_ENTITY_DOMAIN = "notify"

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.notifications"

# Retentie (zie ontwerpdocument, punt 7)
MAX_NOTIFICATIONS = 100
MAX_AGE_DAYS = 30
LIVE_ACTIVITY_STALE_HOURS = 8

# Commando-berichten die nooit als content getoond mogen worden
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

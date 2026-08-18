"""Sensor that exposes the notify_dashboard data to the frontend card.

The card reads this entity's `items` attribute: one list holding every
notification/live activity, active and recently-dismissed alike (see
store.py). Updates reactively via a dispatcher signal as soon as the store
changes, no polling.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import device_info, get_domain_data
from .const import DOMAIN, SIGNAL_UPDATE
from .store import is_active


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Notify Dashboard sensor -- forwarded from __init__.py's
    own async_setup_entry, not the legacy discovery-platform setup this
    used to be (found live, 2026-08-18: Home Assistant warns that an
    entity attaching a device with no config entry behind it will stop
    working in 2027.8.0). No dependency on `entry` itself beyond HA's own
    plumbing requiring it -- device_info()/get_domain_data() still read
    hass.data[DOMAIN], set up once by _async_ensure_core regardless of
    which path (YAML or the config entry) triggered it."""
    async_add_entities([NotifyDashboardSensor(hass)])


class NotifyDashboardSensor(SensorEntity):
    """Exposes the unified item list as an attribute for the card."""

    _attr_has_entity_name = True
    # None, not the "dashboard" translation_key's own "Notify Dashboard"
    # name -- now that this entity has a device (see __init__.py's own
    # device_info(), added 2026-08-07), it's that device's only entity, so
    # this is the device's own unnamed "main feature" entity, same pattern
    # ha-update-manager's own switch.py already uses (that entity's own
    # comment has the full reasoning: has_entity_name=True + _attr_name=None
    # + translation_key kept purely for icons.json's own lookup is safe,
    # confirmed against Entity._name_internal's real source). Without this,
    # the entity's own translated name ("Notify Dashboard") would read as a
    # redundant "Notify Dashboard Notify Dashboard" wherever HA shows the
    # full device+entity name.
    _attr_translation_key = "dashboard"
    _attr_name = None
    _attr_unique_id = f"{DOMAIN}_sensor"
    _attr_should_poll = False
    # `items` is meant to be read live off the state machine by the card,
    # never persisted -- it's the raw companion-app/automation payload for
    # up to MAX_ITEMS (50) entries, which comfortably exceeds the recorder's
    # 16KB-per-attribute-set limit in normal use ("State attributes ...
    # exceed maximum size of 16384 bytes"). Excluding it from recording is
    # the correct fix, not shrinking MAX_ITEMS or trimming payload fields --
    # this data was never meant for history/long-term-stats in the first
    # place.
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._attr_device_info = device_info(hass)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        store = get_domain_data(self.hass)["store"]
        items = store.data["items"]
        # The state itself is "how many things need attention now": active
        # count, not the historical total (dismissed entries stick around
        # in `items` for a while, but shouldn't inflate the headline number).
        self._attr_native_value = sum(1 for item in items if is_active(item))
        # Shallow per-item copy, not a live reference: store.py mutates
        # entries in place (dismissed_at, insert/remove on the same list)
        # rather than replacing them. HA's state machine only pushes a
        # state_changed event to the frontend when `old_state.attributes ==
        # new_attributes` is False (see core.py's async_set_internal): if we
        # handed it the live store list, that "old" snapshot would drift in
        # sync with every later mutation (same object), making the
        # comparison always come back equal and silently suppressing the
        # update whenever the active count itself didn't also change. A
        # fresh dict per item keeps the previous snapshot's top-level fields
        # (dismissed_at included) frozen, so the comparison is real -- a
        # full deepcopy isn't needed for that, since `data` (each entry's
        # nested companion-app/automation payload) is only ever set once at
        # creation and never mutated afterward, so sharing it by reference
        # across snapshots is safe.
        self._attr_extra_state_attributes = {"items": [dict(item) for item in items]}
        self.async_write_ha_state()

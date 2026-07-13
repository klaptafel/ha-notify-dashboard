"""Sensor that exposes the notify_dashboard data to the frontend card.

The card reads this entity's `items` attribute — one list holding every
notification/live activity, active and recently-dismissed alike (see
store.py). Updates reactively via a dispatcher signal as soon as the store
changes — no polling.
"""
from __future__ import annotations

import copy

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_domain_data
from .const import DOMAIN, SIGNAL_UPDATE
from .store import is_active


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Notify Dashboard sensor."""
    async_add_entities([NotifyDashboardSensor(hass)])


class NotifyDashboardSensor(SensorEntity):
    """Exposes the unified item list as an attribute for the card."""

    _attr_has_entity_name = True
    _attr_translation_key = "dashboard"
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

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        store = get_domain_data(self.hass)["store"]
        items = store.data["items"]
        # The state itself is "how many things need attention now" — active
        # count, not the historical total (dismissed entries stick around
        # in `items` for a while, but shouldn't inflate the headline number).
        self._attr_native_value = sum(1 for item in items if is_active(item))
        # deepcopy, not a live reference: store.py mutates entries in place
        # (dismissed_at, insert/remove on the same list) rather than
        # replacing them. HA's state machine only pushes a state_changed
        # event to the frontend when `old_state.attributes == new_attributes`
        # is False (see core.py's async_set_internal) — if we handed it the
        # live store list, that "old" snapshot would drift in sync with
        # every later mutation (same object), making the comparison always
        # come back equal and silently suppressing the update whenever the
        # active count itself didn't also change. A fresh copy each time
        # keeps the previous snapshot frozen, so the comparison is real.
        self._attr_extra_state_attributes = {"items": copy.deepcopy(items)}
        self.async_write_ha_state()

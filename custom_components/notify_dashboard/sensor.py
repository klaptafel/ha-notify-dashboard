"""Sensor die de notify_dashboard-data blootstelt aan de frontend-card.

De card leest deze entity's attributen (notifications / live_activities).
Update reactief via dispatcher-signal zodra de store wijzigt — geen polling.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Notify Dashboard sensor."""
    async_add_entities([NotifyDashboardSensor(hass)])


class NotifyDashboardSensor(SensorEntity):
    """Exposes notifications + live_activities as attributes for the card."""

    _attr_has_entity_name = True
    _attr_translation_key = "dashboard"
    _attr_unique_id = f"{DOMAIN}_sensor"
    _attr_icon = "mdi:bell-outline"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        store = self.hass.data[DOMAIN]["store"]
        data = store.data
        notifications = data["notifications"]
        live_activities = list(data["live_activities"].values())
        self._attr_native_value = len(notifications) + len(live_activities)
        self._attr_extra_state_attributes = {
            "notifications": notifications,
            "live_activities": live_activities,
        }
        self.async_write_ha_state()

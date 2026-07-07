"""Tests for NotifyDashboardSensor.

Attaches the entity to a real EntityPlatform directly (needed so
has_entity_name/translation_key resolution works — that requires
self.platform to be set, which only a real platform attach provides) rather
than going through async_setup_component("sensor", ...). The latter would
pull in notify_dashboard's full manifest dependency chain (http, frontend),
and `frontend` requires the separate `hass_frontend` package which isn't
installable here — irrelevant to what this file actually tests anyway.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.notify_dashboard.const import DOMAIN, SIGNAL_UPDATE
from custom_components.notify_dashboard.sensor import (
    NotifyDashboardSensor,
    async_setup_platform,
)


async def _add_sensor(hass) -> NotifyDashboardSensor:
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="sensor",
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )

    entities: list[NotifyDashboardSensor] = []

    def add_entities(new_entities, update_before_add=False):
        entities.extend(new_entities)

    await async_setup_platform(hass, {}, add_entities)
    await platform.async_add_entities(entities)
    return entities[0]


async def test_setup_platform_adds_one_sensor(hass):
    entities = []

    def add_entities(new_entities, update_before_add=False):
        entities.extend(new_entities)

    await async_setup_platform(hass, {}, add_entities)
    assert len(entities) == 1
    assert isinstance(entities[0], NotifyDashboardSensor)


async def test_sensor_entity_attrs(hass, loaded_store):
    hass.data[DOMAIN] = {"store": loaded_store}
    sensor = await _add_sensor(hass)
    assert sensor.unique_id == f"{DOMAIN}_sensor"
    assert sensor.has_entity_name is True
    assert sensor.should_poll is False


async def test_sensor_populates_state_on_add(hass, loaded_store):
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    hass.data[DOMAIN] = {"store": loaded_store}

    sensor = await _add_sensor(hass)
    state = hass.states.get(sensor.entity_id)
    assert state.state == "1"
    assert len(state.attributes["items"]) == 1
    assert state.attributes["items"][0]["tag"] == "t1"


async def test_sensor_state_counts_active_only_not_dismissed(hass, loaded_store):
    """native_value is "how many things need attention now" — dismissed
    entries stick around in `items` for history, but shouldn't inflate it."""
    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    await loaded_store.async_dismiss(loaded_store.data["items"][0]["id"])
    hass.data[DOMAIN] = {"store": loaded_store}

    sensor = await _add_sensor(hass)
    state = hass.states.get(sensor.entity_id)
    assert state.state == "0"
    assert len(state.attributes["items"]) == 1  # still present, just inactive
    assert state.attributes["items"][0]["dismissed_at"] is not None


async def test_sensor_updates_reactively_via_dispatcher(hass, loaded_store):
    hass.data[DOMAIN] = {"store": loaded_store}
    sensor = await _add_sensor(hass)
    assert hass.states.get(sensor.entity_id).state == "0"

    await loaded_store.async_add_notification("T", "M", {"tag": "t1"})
    assert hass.states.get(sensor.entity_id).state == "1"


async def test_sensor_no_update_without_signal(hass, loaded_store):
    """Without a dispatcher signal (or initial add), state must not change —
    should_poll is False, so nothing should refresh it on its own."""
    hass.data[DOMAIN] = {"store": loaded_store}
    sensor = await _add_sensor(hass)
    assert hass.states.get(sensor.entity_id).state == "0"

    # Mutate the store WITHOUT going through a method that dispatches.
    loaded_store.data["items"].append({"id": "x", "dismissed_at": None})
    assert hass.states.get(sensor.entity_id).state == "0"  # stale until a signal fires

    async_dispatcher_send(hass, SIGNAL_UPDATE)
    assert hass.states.get(sensor.entity_id).state == "1"

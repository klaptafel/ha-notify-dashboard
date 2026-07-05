"""The Notify Dashboard integration.

Two independent setup paths come together here:
- YAML (`notify_dashboard:` config key) — still supported for anyone who
  prefers to keep everything in YAML, and for the mandatory `notify: -
  platform: notify_dashboard` line (which can't go through a config entry
  anyway, see config_flow.py).
- Config entry (added via the UI) — only handles `mirror_dismiss_to`,
  adjustable via "Configure" without a restart.

The core (store, services, frontend, sensor) is only ever set up once,
regardless of which path comes first.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TypedDict, cast

import voluptuous as vol
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_ACTION,
    ATTR_ACTION_DATA,
    ATTR_ID,
    ATTR_TAG,
    CONF_MIRROR_DISMISS_TO,
    DOMAIN,
    EVENT_NOTIFICATION_ACTION,
    NOTIFY_ENTITY_DOMAIN,
    SERVICE_DISMISS,
    SERVICE_DISMISS_ALL,
    SERVICE_FIRE_ACTION,
)
from .store import (
    NotificationNotDismissableError,
    NotificationNotFoundError,
    NotifyDashboardStore,
)

_LOGGER = logging.getLogger(__name__)


class NotifyDashboardData(TypedDict):
    """Shape of hass.data[DOMAIN] — runtime_data is exempt (see
    quality_scale.yaml): the legacy notify platform this integration relies
    on never receives a ConfigEntry, so there's no entry to hang typed
    runtime_data off in the first place."""

    store: NotifyDashboardStore
    mirror_dismiss_to: list[str]


def get_domain_data(hass: HomeAssistant) -> NotifyDashboardData:
    """Typed accessor for hass.data[DOMAIN] — one cast at the Any/typed
    boundary here, real key/type checking at every call site using this."""
    return cast(NotifyDashboardData, hass.data[DOMAIN])


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_MIRROR_DISMISS_TO, default=[]): vol.All(
                    cv.ensure_list, [vol.All(cv.entity_id, cv.entity_domain(NOTIFY_ENTITY_DOMAIN))]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

FRONTEND_URL_BASE = "/notify_dashboard_frontend"

DISMISS_SCHEMA = vol.Schema({vol.Required(ATTR_ID): cv.string})

FIRE_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ACTION): cv.string,
        vol.Optional(ATTR_TAG): cv.string,
        vol.Optional(ATTR_ACTION_DATA): dict,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML (`notify_dashboard:` key) — optional."""
    await _async_ensure_core(hass, config)

    yaml_conf = config.get(DOMAIN, {})
    if yaml_conf:
        if hass.config_entries.async_entries(DOMAIN):
            _LOGGER.warning(
                "Found both the YAML key 'notify_dashboard:' and a config "
                "entry — the settings from 'Configure' in the UI take "
                "precedence. Remove the YAML key to get rid of this warning."
            )
        else:
            get_domain_data(hass)["mirror_dismiss_to"] = yaml_conf.get(CONF_MIRROR_DISMISS_TO, [])

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up via the UI (config entry) — handles mirror_dismiss_to."""
    await _async_ensure_core(hass, {})

    get_domain_data(hass)["mirror_dismiss_to"] = entry.options.get(CONF_MIRROR_DISMISS_TO, [])

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove the config entry — the core (store/services/frontend) stays in
    place as long as the YAML platform line (`notify: - platform:
    notify_dashboard`) is still active; that can't be cleaned up separately
    from this entry."""
    get_domain_data(hass)["mirror_dismiss_to"] = []
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload mirror_dismiss_to as soon as the options change via 'Configure'."""
    get_domain_data(hass)["mirror_dismiss_to"] = entry.options.get(CONF_MIRROR_DISMISS_TO, [])


async def _async_ensure_core(hass: HomeAssistant, config: ConfigType) -> None:
    """Set up the store, services, frontend, and sensor exactly once —
    idempotent, regardless of whether YAML or the config entry arrives first."""
    if DOMAIN in hass.data:
        return

    store = NotifyDashboardStore(hass)
    await store.async_load()

    data: NotifyDashboardData = {
        "store": store,
        "mirror_dismiss_to": [],
    }
    hass.data[DOMAIN] = data

    # Serve the card/badge JS from the integration itself.
    frontend_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(frontend_path), cache_headers=False)]
    )

    # Wait until HA is fully started before registering the Lovelace
    # resource — otherwise hass.data["lovelace"] (the storage collection)
    # sometimes doesn't exist yet, which caused exactly the random
    # "Configuration error" behavior (a race condition, not consistently
    # reproducible).
    async def _register_resource(_event: Event | None = None) -> None:
        await _async_register_lovelace_resource(hass)

    if hass.is_running:
        hass.async_create_task(_register_resource())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_resource)

    hass.async_create_task(
        discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )

    async def handle_dismiss(call: ServiceCall) -> None:
        item_id = call.data[ATTR_ID]
        try:
            item = await store.async_dismiss(item_id)
        except NotificationNotFoundError as err:
            raise ServiceValidationError(
                f"No notification found with id '{item_id}'"
            ) from err
        except NotificationNotDismissableError as err:
            raise ServiceValidationError(
                f"'{item_id}' can't be dismissed — this notification is persistent"
            ) from err

        tag = item.get("tag")
        if tag and get_domain_data(hass)["mirror_dismiss_to"]:
            await _async_mirror_clear(hass, tag)

    async def handle_dismiss_all(call: ServiceCall) -> None:
        cleared = await store.async_dismiss_all_notifications()
        if get_domain_data(hass)["mirror_dismiss_to"]:
            tags = [tag for item in cleared if (tag := item.get("tag"))]
            await asyncio.gather(*(_async_mirror_clear(hass, tag) for tag in tags))

    async def handle_fire_action(call: ServiceCall) -> None:
        # Fires hass.bus.async_fire server-side instead of letting the card
        # itself call the fire_event websocket action — that one requires
        # @require_admin in HA core, so it would silently fail for non-admin
        # dashboard viewers (e.g. a kiosk tablet on a restricted account). A
        # regular service call like this one doesn't have that restriction.
        event_data = {ATTR_ACTION: call.data[ATTR_ACTION]}
        if ATTR_TAG in call.data:
            event_data[ATTR_TAG] = call.data[ATTR_TAG]
        if ATTR_ACTION_DATA in call.data:
            event_data[ATTR_ACTION_DATA] = call.data[ATTR_ACTION_DATA]
        hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, event_data)

    hass.services.async_register(DOMAIN, SERVICE_DISMISS, handle_dismiss, schema=DISMISS_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISMISS_ALL, handle_dismiss_all)
    hass.services.async_register(
        DOMAIN, SERVICE_FIRE_ACTION, handle_fire_action, schema=FIRE_ACTION_SCHEMA
    )


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register the card as a real Lovelace resource (storage mode).

    The URL includes a `?v=<integration-version>` cache buster: without it
    the browser (or a service worker) keeps using the old JS after every
    update, as happened when a long-fixed bug still seemed to show "old"
    behavior. On a version change, the existing resource gets updated
    instead of creating a duplicate.

    NOTE — there is an open core bug (home-assistant/core#165767, reported
    March 2026): if an integration calls resources.async_create_item()
    before the existing resources have been loaded, that overwrites the
    entire stored resource list with just the new item — so all of the
    user's other resources are lost. We explicitly prevent this by calling
    async_load() ourselves first (exactly the fix suggested in the issue
    itself), so the existing data is already in memory before we add
    anything.
    """
    integration = await async_get_integration(hass, DOMAIN)
    base_path = f"{FRONTEND_URL_BASE}/notify-dashboard-card.js"
    url = f"{base_path}?v={integration.version}"

    lovelace_data = hass.data.get("lovelace")
    if not lovelace_data or getattr(lovelace_data, "resource_mode", None) != "storage":
        # YAML-mode dashboards don't have a storage resources collection —
        # add_extra_js_url remains the only option there.
        frontend.add_extra_js_url(hass, url)
        return

    resources = lovelace_data.resources
    await resources.async_load()  # safety net against core#165767

    existing = next(
        (item for item in resources.async_items() if item["url"].split("?")[0] == base_path),
        None,
    )
    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": url})
    elif existing["url"] != url:
        await resources.async_update_item(existing["id"], {"res_type": "module", "url": url})


async def _async_mirror_clear(hass: HomeAssistant, tag: str) -> None:
    """Send clear_notification to the mirror_dismiss_to targets.

    Uses the generic `notify.send_message` action with the chosen entity as
    the target, not a separate service per entity name — modern notify
    entities (like the one the companion app uses these days) run through
    that one shared endpoint, not through their own service per device.
    Targets are independent of each other, so fire them in parallel instead
    of waiting on each one in turn.
    """

    async def _clear_one(entity_id: str) -> None:
        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"message": "clear_notification", "data": {"tag": tag}},
                target={"entity_id": entity_id},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not forward clear_notification to %s", entity_id)

    await asyncio.gather(
        *(_clear_one(entity_id) for entity_id in get_domain_data(hass)["mirror_dismiss_to"])
    )

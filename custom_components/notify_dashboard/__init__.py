"""The Notify Dashboard integration.

Two independent setup paths come together here:
- YAML (`notify_dashboard:` config key): still supported for anyone who
  prefers to keep everything in YAML, and for the mandatory `notify: -
  platform: notify_dashboard` line (which can't go through a config entry
  anyway, see config_flow.py).
- Config entry (added via the UI): handles `mirror_dismiss_to`, adjustable
  via "Configure" without a restart, and (since 2026-08-18) is now also the
  only way the sensor gets set up -- Home Assistant now warns (and will
  stop allowing entirely in 2027.8.0) an entity attaching a device with no
  config entry behind it, which the sensor's own discovery-platform setup
  could never provide. The sensor simply doesn't exist for a YAML-only
  setup with no config entry at all; add the integration via the UI to get
  it (no migration path back-filled for that case, direct user feedback).

The core (store, services, frontend) is still only ever set up once,
regardless of which path comes first -- only the sensor now specifically
requires the config entry path.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TypedDict, cast

import voluptuous as vol
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
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
    SERVICE_DISMISS,
    SERVICE_DISMISS_ALL,
    SERVICE_FIRE_ACTION,
    is_mirror_entity,
    validate_mirror_target,
)
from .store import (
    NotificationNotDismissableError,
    NotificationNotFoundError,
    NotifyDashboardStore,
)

_LOGGER = logging.getLogger(__name__)


class NotifyDashboardData(TypedDict):
    """Shape of hass.data[DOMAIN]: runtime_data is exempt (see
    quality_scale.yaml): the legacy notify platform this integration relies
    on never receives a ConfigEntry, so there's no entry to hang typed
    runtime_data off in the first place."""

    store: NotifyDashboardStore
    mirror_dismiss_to: list[str]
    # manifest.json's own version/documentation, fetched once in
    # _async_ensure_core -- sensor.py's own device_info() below reads these
    # for the device info page's own software version and "Visit" link.
    sw_version: str
    configuration_url: str | None


def get_domain_data(hass: HomeAssistant) -> NotifyDashboardData:
    """Typed accessor for hass.data[DOMAIN]: one cast at the Any/typed
    boundary here, real key/type checking at every call site using this."""
    return cast(NotifyDashboardData, hass.data[DOMAIN])


def device_info(hass: HomeAssistant) -> DeviceInfo:
    """The single virtual device every entity this integration creates
    attaches to -- direct user feedback (cross-project), 2026-08-07, wanting
    this same device-info block (including the "Visit" link) across every
    integration, not just newer ones. entry_type=SERVICE: no physical
    hardware, same reasoning as ha-update-manager's own device.py.
    configuration_url points at the GitHub repo (manifest.json's own
    `documentation` field) rather than an internal HA path: unlike
    ha-update-manager, this integration has no sidebar panel of its own to
    link to instead."""
    domain_data = get_domain_data(hass)
    return DeviceInfo(
        identifiers={(DOMAIN, DOMAIN)},
        name="Notify Dashboard",
        manufacturer="Notify Dashboard",
        entry_type=DeviceEntryType.SERVICE,
        sw_version=domain_data["sw_version"],
        configuration_url=domain_data["configuration_url"],
    )


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_MIRROR_DISMISS_TO, default=[]): vol.All(
                    cv.ensure_list, [validate_mirror_target]
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
    """Set up via YAML (`notify_dashboard:` key): optional."""
    await _async_ensure_core(hass)

    yaml_conf = config.get(DOMAIN, {})
    if yaml_conf:
        if hass.config_entries.async_entries(DOMAIN):
            _LOGGER.warning(
                "Found both the YAML key 'notify_dashboard:' and a config "
                "entry: the settings from 'Configure' in the UI take "
                "precedence. Remove the YAML key to get rid of this warning."
            )
        else:
            get_domain_data(hass)["mirror_dismiss_to"] = yaml_conf.get(CONF_MIRROR_DISMISS_TO, [])

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up via the UI (config entry): handles mirror_dismiss_to, and
    (since 2026-08-18) is now the only path that creates the sensor -- see
    this module's own docstring for why."""
    await _async_ensure_core(hass)

    get_domain_data(hass)["mirror_dismiss_to"] = entry.options.get(CONF_MIRROR_DISMISS_TO, [])

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove the config entry: the core (store/services/frontend) stays in
    place as long as the YAML platform line (`notify: - platform:
    notify_dashboard`) is still active; that can't be cleaned up separately
    from this entry. The sensor, forwarded to only from this exact entry
    (see async_setup_entry above), is unloaded here instead."""
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor"]):
        return False
    get_domain_data(hass)["mirror_dismiss_to"] = []
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload mirror_dismiss_to as soon as the options change via 'Configure'."""
    get_domain_data(hass)["mirror_dismiss_to"] = entry.options.get(CONF_MIRROR_DISMISS_TO, [])


async def _async_ensure_core(hass: HomeAssistant) -> None:
    """Set up the store, services, and frontend exactly once: idempotent,
    regardless of whether YAML or the config entry arrives first. The
    sensor is deliberately not part of this anymore (see this module's own
    docstring) -- it's forwarded to only from async_setup_entry, since it
    needs a real config entry to attach its device to."""
    if DOMAIN in hass.data:
        return

    async def _on_removed(tags: list[str]) -> None:
        # A notification that times out/gets capacity-trimmed, or that's
        # cleared via a clear_notification command sent straight to
        # notify.dashboard, disappears from the dashboard exactly like an
        # explicit dismiss: it should clear the phone notification too,
        # not leave it behind. Safe to reference get_domain_data(hass) here
        # despite hass.data[DOMAIN] not existing yet at this exact point in
        # _async_ensure_core: this callback only actually runs later (from
        # the periodic cleanup timer or a subsequent store write), by which
        # time setup has finished.
        if get_domain_data(hass)["mirror_dismiss_to"]:
            await asyncio.gather(*(_async_mirror_clear(hass, tag) for tag in tags))

    store = NotifyDashboardStore(hass, on_removed=_on_removed)
    # For device_info() above -- fetched once here (this whole function only
    # ever runs once, see its own docstring), not per-entity.
    integration = await async_get_integration(hass, DOMAIN)

    data: NotifyDashboardData = {
        "store": store,
        "mirror_dismiss_to": [],
        "sw_version": str(integration.version),
        "configuration_url": integration.documentation,
    }
    hass.data[DOMAIN] = data

    # Independent of each other (neither's result feeds the other); no
    # reason to await them one after the other on the setup path.
    frontend_path = Path(__file__).parent / "frontend"
    await asyncio.gather(
        store.async_load(),
        hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, str(frontend_path), cache_headers=False)]
        ),
    )

    # Wait until HA is fully started before registering the Lovelace
    # resource: otherwise hass.data["lovelace"] (the storage collection)
    # sometimes doesn't exist yet, which caused exactly the random
    # "Configuration error" behavior (a race condition, not consistently
    # reproducible).
    async def _register_resource(_event: Event | None = None) -> None:
        await _async_register_lovelace_resource(hass)

    if hass.is_running:
        hass.async_create_task(_register_resource())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_resource)

    async def handle_dismiss(call: ServiceCall) -> None:
        item_id = call.data[ATTR_ID]
        try:
            # Mirror-forwarding (if a tag's involved and mirror_dismiss_to is
            # configured) happens inside async_dismiss itself via the
            # on_removed callback set up above: same single mechanism used
            # for every other way an item can leave the store.
            await store.async_dismiss(item_id)
        except NotificationNotFoundError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="notification_not_found",
                translation_placeholders={"item_id": item_id},
            ) from err
        except NotificationNotDismissableError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="notification_not_dismissable",
                translation_placeholders={"item_id": item_id},
            ) from err

    async def handle_dismiss_all(call: ServiceCall) -> None:
        await store.async_dismiss_all_notifications()

    async def handle_fire_action(call: ServiceCall) -> None:
        # Fires hass.bus.async_fire server-side instead of letting the card
        # itself call the fire_event websocket action: that one requires
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


def _frontend_content_hash(path: Path) -> str:
    """A short hash of the card's own JS content, used as the cache buster
    below instead of the integration version: content-derived means it's
    physically impossible to ship a frontend change without the URL
    changing too, unlike a version string someone has to remember to bump
    for every edit (that discipline slipped at least once already, and
    produced exactly the "still shows old behavior after updating" reports
    this mechanism exists to prevent)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register the card as a real Lovelace resource (storage mode).

    The URL includes a `?v=<content-hash>` cache buster: without it the
    browser (or a service worker) keeps using the old JS after every
    update, as happened when a long-fixed bug still seemed to show "old"
    behavior. When the content changes, the existing resource gets updated
    instead of creating a duplicate.

    NOTE: there is an open core bug (home-assistant/core#165767, reported
    March 2026): if an integration calls resources.async_create_item()
    before the existing resources have been loaded, that overwrites the
    entire stored resource list with just the new item, so all of the
    user's other resources are lost. We explicitly prevent this by calling
    async_load() ourselves first (exactly the fix suggested in the issue
    itself), so the existing data is already in memory before we add
    anything.
    """
    frontend_js_path = Path(__file__).parent / "frontend" / "notify-dashboard-card.js"
    content_hash = await hass.async_add_executor_job(_frontend_content_hash, frontend_js_path)
    base_path = f"{FRONTEND_URL_BASE}/notify-dashboard-card.js"
    url = f"{base_path}?v={content_hash}"

    lovelace_data = hass.data.get("lovelace")
    if not lovelace_data or getattr(lovelace_data, "resource_mode", None) != "storage":
        # YAML-mode dashboards don't have a storage resources collection:
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


def _mirror_target_issue_id(target: str) -> str:
    return f"missing_mirror_target_{target}"


async def _async_mirror_clear(hass: HomeAssistant, tag: str) -> None:
    """Send clear_notification to the mirror_dismiss_to targets.

    Each target is either a notify *entity* (dispatched via the generic
    notify.send_message action + target: modern notify integrations, like
    the companion app these days, all run through that one shared endpoint
    instead of a service per device) or a legacy notify *service*, a
    service registered directly under the notify domain with no entity at
    all, the only way to reach e.g. a YAML `notify: - platform: group` (or
    any other BaseNotificationService-based integration, including this
    one). is_mirror_entity/validate_mirror_target/_mirror_dismiss_options
    establish the same rule this uses to tell them apart: an entity id
    always has a dot, a bare service name never does.
    Targets are independent of each other, so fire them in parallel instead
    of waiting on each one in turn.
    """

    async def _clear_one(target: str) -> None:
        issue_id = _mirror_target_issue_id(target)
        is_entity = is_mirror_entity(target)
        # A target service call with no matching entity/service just
        # silently does nothing (no exception): the try/except below can't
        # catch this case at all, so it's checked explicitly here.
        exists = (
            hass.states.get(target) is not None
            if is_entity
            else hass.services.has_service("notify", target)
        )
        if not exists:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_mirror_target",
                translation_placeholders={"entity_id": target},
            )
            return
        ir.async_delete_issue(hass, DOMAIN, issue_id)

        payload = {"message": "clear_notification", "data": {"tag": tag}}
        try:
            if is_entity:
                await hass.services.async_call(
                    "notify", "send_message", payload, target={"entity_id": target}, blocking=False
                )
            else:
                # The service name itself is the target here: a raw
                # legacy service call, not the entity-based target selector.
                await hass.services.async_call("notify", target, payload, blocking=False)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not forward clear_notification to %s", target)

    await asyncio.gather(
        *(_clear_one(target) for target in get_domain_data(hass)["mirror_dismiss_to"])
    )

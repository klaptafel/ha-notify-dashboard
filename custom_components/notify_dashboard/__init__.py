"""The Notify Dashboard integration.

Twee onafhankelijke setup-paden komen hier samen:
- YAML (`notify_dashboard:` config-key) — nog steeds ondersteund voor wie
  liever alles in YAML houdt, en voor de verplichte `notify: - platform:
  notify_dashboard`-regel (die kan sowieso niet via een config entry, zie
  config_flow.py).
- Config entry (via de UI toegevoegd) — regelt alleen `mirror_dismiss_to`,
  aanpasbaar via "Configureren" zonder herstart.

De kern (store, services, frontend, sensor) wordt maar één keer opgezet,
ongeacht welk pad als eerste langskomt.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, discovery
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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up via YAML (`notify_dashboard:` key) — optioneel."""
    await _async_ensure_core(hass, config)

    yaml_conf = config.get(DOMAIN, {})
    if yaml_conf:
        if hass.config_entries.async_entries(DOMAIN):
            _LOGGER.warning(
                "Zowel de YAML-sleutel 'notify_dashboard:' als een config entry "
                "gevonden — de instellingen via 'Configureren' in de UI hebben "
                "voorrang. Verwijder de YAML-sleutel om deze waarschuwing kwijt te raken."
            )
        else:
            hass.data[DOMAIN]["mirror_dismiss_to"] = yaml_conf.get(CONF_MIRROR_DISMISS_TO, [])

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up via de UI (config entry) — regelt mirror_dismiss_to."""
    await _async_ensure_core(hass, {})

    hass.data[DOMAIN]["mirror_dismiss_to"] = entry.options.get(CONF_MIRROR_DISMISS_TO, [])

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config entry verwijderen — de kern (store/services/frontend) blijft staan
    zolang de YAML-platform-regel (`notify: - platform: notify_dashboard`)
    nog actief is; die kan niet los van deze entry worden opgeruimd."""
    hass.data[DOMAIN]["mirror_dismiss_to"] = []
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Herlaad mirror_dismiss_to zodra de opties via 'Configureren' wijzigen."""
    hass.data[DOMAIN]["mirror_dismiss_to"] = entry.options.get(CONF_MIRROR_DISMISS_TO, [])


async def _async_ensure_core(hass: HomeAssistant, config: dict) -> None:
    """Zet store, services, frontend en sensor eenmalig op — idempotent,
    ongeacht of YAML of de config entry als eerste binnenkomt."""
    if DOMAIN in hass.data:
        return

    store = NotifyDashboardStore(hass)
    await store.async_load()

    hass.data[DOMAIN] = {
        "store": store,
        "mirror_dismiss_to": [],
    }

    # Serveer de card/badge-JS vanuit de integratie zelf.
    frontend_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(frontend_path), cache_headers=False)]
    )

    # Wachten tot HA volledig is opgestart voordat we de Lovelace-resource
    # registreren — anders bestaat hass.data["lovelace"] (storage-collectie)
    # soms nog niet, en dat gaf precies het willekeurige "Configuration
    # error"-gedrag (race condition, niet consistent reproduceerbaar).
    async def _register_resource(_event=None) -> None:
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
                f"Geen melding gevonden met id '{item_id}'"
            ) from err
        except NotificationNotDismissableError as err:
            raise ServiceValidationError(
                f"'{item_id}' kan niet gedismissed worden — deze notification is persistent"
            ) from err

        if item.get("tag") and hass.data[DOMAIN]["mirror_dismiss_to"]:
            await _async_mirror_clear(hass, item["tag"])

    async def handle_dismiss_all(call: ServiceCall) -> None:
        cleared = await store.async_dismiss_all_notifications()
        if hass.data[DOMAIN]["mirror_dismiss_to"]:
            tags = [item["tag"] for item in cleared if item.get("tag")]
            await asyncio.gather(*(_async_mirror_clear(hass, tag) for tag in tags))

    async def handle_fire_action(call: ServiceCall) -> None:
        # Vuurt hass.bus.async_fire server-side af i.p.v. de card zelf de
        # fire_event websocket-actie te laten aanroepen — die vereist
        # @require_admin in HA core, dus zou voor niet-admin dashboardgebruikers
        # (bv. een kiosk-tablet met een beperkt account) stil falen. Een gewone
        # service-aanroep zoals deze heeft die beperking niet.
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
    """Registreer de card als een echte Lovelace-resource (storage mode).

    De URL bevat een `?v=<integratie-versie>` cache-buster: zonder dat blijft
    de browser (of een service worker) na elke update de oude JS gebruiken,
    zoals bleek toen een allang gefixte regel toch nog "oud" gedrag leek te
    vertonen. Bij een versiewijziging wordt de bestaande resource bijgewerkt
    in plaats van een duplicaat aan te maken.

    LET OP — er is een open core-bug (home-assistant/core#165767, gemeld
    maart 2026): als een integratie resources.async_create_item() aanroept
    vóórdat de bestaande resources zijn geladen, overschrijft dat de hele
    opgeslagen resource-lijst met alleen het nieuwe item — dus alle andere
    resources van de gebruiker gaan verloren. We voorkomen dit expliciet
    door zelf eerst async_load() aan te roepen (exact de fix die in het
    issue zelf wordt voorgesteld), zodat de bestaande data al in geheugen
    staat vóórdat we iets toevoegen.
    """
    integration = await async_get_integration(hass, DOMAIN)
    base_path = f"{FRONTEND_URL_BASE}/notify-dashboard-card.js"
    url = f"{base_path}?v={integration.version}"

    lovelace_data = hass.data.get("lovelace")
    if not lovelace_data or getattr(lovelace_data, "resource_mode", None) != "storage":
        # YAML-mode dashboards hebben geen storage-resources-collectie —
        # daar blijft add_extra_js_url de enige optie.
        frontend.add_extra_js_url(hass, url)
        return

    resources = lovelace_data.resources
    await resources.async_load()  # veiligheidsnet tegen core#165767

    existing = next(
        (item for item in resources.async_items() if item["url"].split("?")[0] == base_path),
        None,
    )
    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": url})
    elif existing["url"] != url:
        await resources.async_update_item(existing["id"], {"res_type": "module", "url": url})


async def _async_mirror_clear(hass: HomeAssistant, tag: str) -> None:
    """Stuur clear_notification door naar de mirror_dismiss_to-targets.

    Gebruikt de generieke `notify.send_message`-actie met de gekozen entity
    als target, niet een losse service per entity-naam — moderne notify-
    entities (zoals de companion-app die tegenwoordig gebruikt) draaien
    via dat ene gedeelde endpoint, niet via een eigen service per apparaat.
    Targets zijn onafhankelijk van elkaar, dus parallel afvuren i.p.v. op
    elkaar te wachten.
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
            _LOGGER.warning("Kon clear_notification niet doorsturen naar %s", entity_id)

    await asyncio.gather(
        *(_clear_one(entity_id) for entity_id in hass.data[DOMAIN]["mirror_dismiss_to"])
    )

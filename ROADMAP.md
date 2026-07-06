# Roadmap

Internal notes on considered-but-not-yet-built features — not shown in
README.md on purpose (not user-facing commitments, just recorded intent so
context isn't lost between sessions).

## Multiple Notify Dashboard instances

**Goal**: separate, independent dashboards — e.g. `notify.dashboard_slaapkamer`
and `notify.dashboard_woonkamer` — each with its own notification history and
its own sensor, so a Lovelace card can be pointed at exactly one of them.

**Verdict: not blocked, just a real chunk of work.** Nothing here hits an
actual HA architectural wall (unlike, say, giving `NotifyEntity` a rich
`data` payload, which genuinely can't be done — see notify.py's docstring).
It's a deliberate, scoped refactor to schedule on its own, not something to
slip in incrementally.

**Current blocker**: everything is a hardcoded singleton, regardless of the
YAML `name:` on the legacy notify platform (that part is already free-form
today — `notify: - platform: notify_dashboard name: x` works now — the
problem is every such instance still shares one global store):

- `const.py`'s `STORAGE_KEY = f"{DOMAIN}.notifications"` — one shared
  `.storage` file for all instances.
- `sensor.py`'s `_attr_unique_id = f"{DOMAIN}_sensor"` — hardcoded, a second
  instance's sensor would collide.
- `hass.data[DOMAIN]` — one flat singleton dict, not keyed per entry.
- `config_flow.py`'s `_async_current_entries()` guard blocks a second config
  entry outright.
- `notify_dashboard.dismiss` / `dismiss_all` / `fire_action` are registered
  once, domain-wide (`hass.services.async_register(DOMAIN, ...)`) — with
  multiple stores, a service call needs to say *which* dashboard it targets.
  `notify-dashboard-card.js` would need to carry and pass that identifier on
  every dismiss/action-tap too — this touches the frontend, not just the
  backend.

`mirror_dismiss_to` is *not* on this list — it already lives in
`config_entry.options`, which is naturally per-entry.

**Feature parity is not a concern**: none of this touches the data model or
field handling. `tag`, `group`, `live_update`, `progress`, `actions`,
`color`, `chronometer`, everything in the README's field table — all of it
stays exactly as-is per instance. This refactor is purely about routing/
identity (which store an instance's data lands in), never about what fields
are understood or how they render.

**Resolved: the YAML↔config-entry matching mechanism.** `async_get_service
(hass, config, discovery_info)` (notify.py) receives the YAML config of that
specific platform instance, including its `name:` — so matching that name
against the readable identifier stored on each config entry (collected via
a new config-flow field) is enough to route a given YAML block to the right
entry's store. No config entry match → fall back to a default/global store
(preserves today's YAML-only-no-entry behavior). Not a mystery anymore, just
implementation.

**What would need to change** (roughly, in order):
1. Config flow gains a readable identifier field (e.g. "Dashboard name")
   collected on setup, used for the entry title and as the base for its
   unique_id/entity_id/storage key. Remove the single-instance abort.
2. `hass.data[DOMAIN]` becomes a dict keyed by `entry.entry_id`, each holding
   its own store; `_async_ensure_core`'s "run once globally" idempotency
   guard becomes "run once per entry."
3. `STORAGE_KEY` becomes per-entry (keyed by `entry.entry_id` or the
   slugified name) instead of one fixed string.
4. `notify.py`: match the YAML `name:` against stored entry identifiers to
   pick the right store (see above); fall back to a default store if no
   match.
5. `sensor.py`: unique_id/entity_id per entry, discovery_info carries which
   entry it belongs to.
6. `dismiss`/`dismiss_all`/`fire_action` services gain a way to target a
   specific entry/store; `notify-dashboard-card.js` needs to know its own
   entry identifier and pass it along on every such call.
7. Most of the test suite assumes a singleton store/`hass.data` shape today
   (conftest.py's `loaded_store`/`loaded_store_factory`, test_init.py,
   test_services.py, test_config_flow.py, test_sensor.py) — expect to touch
   most of it, not just add new cases.

### Related: device registry support

`quality_scale.yaml`'s `devices` rule is marked `exempt` today. Not an HA
architectural wall either, on closer inspection — just another artifact of
our own current setup code: `sensor.py`'s entity is *always* added via
`discovery.async_load_platform`, even when a config entry already exists,
because `_async_ensure_core` runs identically from both `async_setup`
(YAML) and `async_setup_entry`. HA's `EntityPlatform` only attaches a device
when `self.config_entry` is set (see
`homeassistant/helpers/entity_platform.py`), which only happens via
`async_forward_entry_setups` — never via discovery. Switching to
`async_forward_entry_setups` for the sensor whenever a config entry exists
(keeping discovery only as the fallback for a pure-YAML-without-entry setup)
would unlock this, independently of the notify service itself (which stays
legacy/YAML regardless — that part really is fixed). Worth doing in the
same pass as multi-instance, since both touch the same setup-path code.

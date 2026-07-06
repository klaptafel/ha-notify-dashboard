# Roadmap

Internal notes on considered-but-not-yet-built features — not shown in
README.md on purpose (not user-facing commitments, just recorded intent so
context isn't lost between sessions).

## Multiple Notify Dashboard instances

**Goal**: separate, independent dashboards — e.g. `notify.dashboard_slaapkamer`
and `notify.dashboard_woonkamer` — each with its own notification history and
its own sensor, so a Lovelace card can be pointed at exactly one of them.

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

`mirror_dismiss_to` is *not* on this list — it already lives in
`config_entry.options`, which is naturally per-entry.

**What would need to change**:
1. Config flow gains a readable identifier field (e.g. "Dashboard name")
   collected on setup, used for the entry title and as the base for its
   unique_id/entity_id/storage key.
2. `STORAGE_KEY` becomes per-entry (e.g. keyed by `entry.entry_id` or the
   slugified name) instead of one fixed string.
3. `sensor.py`'s unique_id/entity_id becomes per-entry, so
   `sensor.notify_dashboard_slaapkamer` etc. can coexist.
4. `hass.data[DOMAIN]` becomes a dict keyed by `entry.entry_id`, each
   holding its own store.
5. Remove the single-instance abort in `config_flow.py`.

**Open design question (the hard part)**: the YAML
`notify: - platform: notify_dashboard name: x` block has no inherent link to
a specific config entry today — there's exactly one store, so the link is
implicit. With multiple entries, something needs to map a given YAML
platform instance to the *matching* config entry's store — most likely by
matching the YAML `name:` against the readable identifier chosen in the
config entry. This matching mechanism, not the per-entry key-renaming
itself, is the real design work here.

**Why not start on this now**: there are no users yet, so breaking changes
are free — but that freedom doesn't expire by waiting. Pre-adapting pieces
of this now, before the matching mechanism above is actually designed,
risks doing it wrong and reworking it anyway once the real design lands.
Better to do the whole refactor in one clean pass, once actually committed
to building this feature.

### Related: device registry support (currently also blocked, same root cause)

`quality_scale.yaml`'s `devices` rule is marked `exempt` today, and it's not
just "not done yet" — it's currently **structurally impossible**:
`sensor.py`'s entity is added via `discovery.async_load_platform` (needed so
`notify.dashboard` keeps working from YAML alone, with no config entry at
all). HA's `EntityPlatform` only attaches a device to an entity when
`self.config_entry` is set (see
`homeassistant/helpers/entity_platform.py`), which only happens when a
platform is set up via `async_forward_entry_setups` — never via discovery,
regardless of whether a config entry additionally exists elsewhere. Setting
`device_info` today would just be silently ignored.

This is the same underlying constraint (the discovery-based, YAML-only-
compatible setup path) that blocks multi-instance support above. If/when
the setup architecture is reworked to support multiple instances, revisit
at the same time whether device registry attachment becomes possible too —
don't solve them separately.

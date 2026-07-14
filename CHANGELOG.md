# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/). Versions before 1.1.0 are not retroactively documented. See git history / GitHub releases for those.

## [Unreleased]

### Changed
- `store.py`'s `_async_save()` and the periodic cleanup's save/dispatch logic consolidated into one shared `_persist_after_cleanup()` helper; no behavior change.
- The card and editor classes' duplicated `_uiTr()` translation lookup consolidated into a shared `resolveUiTr()` helper.
- The editor's duplicated tags/groups filter-section markup consolidated into a shared `_renderFilterPair()` helper.
- `_renderRow()` (a ~320-line method) split into `_buildRowIcon`/`_buildRowContent`/`_appendDebugRow`/`_buildRowDismissArea`/`_buildRowActions`; no behavior change.
- `sensor.py`'s `native_value`/`extra_state_attributes` update now copies each item shallowly (`[dict(item) for item in items]`) instead of a full `copy.deepcopy()`; each item's nested `data` payload is only ever set once at creation and never mutated afterward, so a shallow per-item copy already preserves the frozen-snapshot guarantee the deepcopy was there for. No behavior change.
- Removed the unused `frontend/notify-dashboard-badge.js` design-note stub (a never-built, never-registered "Phase 2" idea); moved to this project's entry in the repo-wide `FUTURE.md` instead.

## [1.2.0] - 2026-07-13

Notifications now give a satisfying tap ripple when clicked, the card fits properly into Home Assistant's Sections dashboards, and rows are aligned more closely with the native Tile card look. Also fixes a background warning about oversized notification history clogging up your logbook, a bug where editor fields lost focus while typing, and a version-number mismatch between the integration and the card.

### Added
- `ha-ripple` tap feedback on the clickable notification icon, matching package-tracker-card's equivalent.
- `getGridOptions()` for the Sections dashboard view.
- Full config option table in the README.

### Changed
- `EDITOR_TRANSLATIONS`/`CARD_TRANSLATIONS` merged into a single `TRANSLATIONS` dict (resolved one key collision: the runtime dismiss-confirmation dialog is now `confirm_dismiss_prompt`, distinct from the editor's `confirm_dismiss` toggle label).
- Row layout, icon size, padding, and typography brought in line with Home Assistant's native Tile card, including a 1px alignment fix to match `ha-card`'s real border-box behavior.
- The action-button confirmation delay increased from 400ms to 1s.
- README title given an SEO-friendly subtitle (": Home Assistant notification dashboard integration"), matching the rest of this HACS collection.

### Fixed
- The integration's `manifest.json` version and the frontend card's own `CARD_VERSION` had drifted apart (1.1.4 vs 1.1.7): unified into a single version number going forward.
- Empty state now names the missing `entity:` when the configured sensor doesn't exist.
- `notify-dashboard-badge.js` translated from Dutch to English (base language).
- Removed leftover `[ND DEBUG]` diagnostic logging.
- Four code comments referenced "the design doc" for context that isn't in this repo (`notify.py`, `config_flow.py`, `const.py`, the frontend card): rewritten to explain the reasoning directly instead. One of them cited an untracked "architecture discussion #1041"; that's now a real link to [home-assistant/architecture#1041](https://github.com/home-assistant/architecture/discussions/1041), the discussion explaining why this integration deliberately uses the legacy `BaseNotificationService` instead of the newer `NotifyEntity` (which has no way to receive `data`/`target` at all).
- `sensor.notify_dashboard`'s `items` attribute (the full notification/live-activity list, up to `MAX_ITEMS` entries with their raw companion-app payloads) could exceed the recorder's 16KB-per-attribute-set limit, logging a warning and silently dropping the attributes from history every time it did. Marked `_unrecorded_attributes = frozenset({"items"})`: this data was only ever meant to be read live off the state machine by the card, never persisted to history/long-term statistics, so excluding it from recording is the correct fix rather than shrinking `MAX_ITEMS` or trimming payload fields.
- The editor's `setConfig()` used a single-use `_ownFire` boolean to recognize the echo of its own `config-changed` events, cleared by the *first* matching callback, but a second genuine echo (confirmed happening in the same editor pattern in other projects in this HACS collection) would slip through and trigger a destructive `_renderTab()` mid-edit. This editor had already worked around the *usual* symptom (focus loss while typing) by never re-rendering on plain `_fire()`, but the underlying flag itself remained fragile. Replaced with a content-based check: `_fire()` now remembers exactly what it last dispatched, and `setConfig()` compares the incoming config against that (via `deepEqual()`) instead of relying on a single-use flag.
- `getStubConfig()` spread the entire `CARD_DEFAULTS` object into a freshly-added card's initial config, writing every default setting into the YAML instead of just `entity:`. This initial config never goes through `stripDefaults()` (that only runs on later edits), so it was the one place defaults leaked into stored config verbatim. Now returns just `{ entity }`: the main card's `setConfig()` already merges `CARD_DEFAULTS` in at runtime, so nothing is lost.

### Quality Scale
- Self-assessed against Home Assistant's Integration Quality Scale: 31 done / 21 exempt / 0 todo (up from 30/21/1). `brands` reclassified from todo to done: since HA 2026.3 (Brands Proxy API) a local `brand/` folder is the current standard, not a `home-assistant/brands` submission: this project's `brand/` folder already has all four required/recommended files (`icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`). `brand/README.md` updated to reflect this.

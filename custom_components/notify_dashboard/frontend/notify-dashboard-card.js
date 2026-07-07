// notify-dashboard-card.js
// Lovelace card for the notify_dashboard integration.
// Reads sensor.notify_dashboard (attribute: items[] — notifications and
// live activities together, told apart by data.live_update; active and
// recently-dismissed entries alike, told apart by dismissed_at).
//
// Status: fase 1, including a visual editor (tab skeleton taken 1-to-1 from
// package-tracker-card: tab bar, ha-switch/ha-form rows, config-changed +
// _ownFire echo protection).
// Design decisions are implemented 1-to-1: no chevron/expand, always full
// text, dismiss button as the last feature, tap = navigate (not dismiss),
// tag-replace = full replacement (so no client-side merge needed — the
// backend already delivers complete entries).
//
// Fase 2, partially: progress bar (progress/progress_max, with percentage),
// chronometer/when, and critical_text (live activities only — shares the
// status bar chip slot with chronometer, which wins when both are set,
// same as the companion app). progress_indeterminate is picked up too.

const CARD_VERSION = '1.1.4-debug';

const CARD_DEFAULTS = {
  layout: 'single', // or: split
  content: ['live_activities', 'notifications'],
  group_order: 'live_first', // or: notifications_first / chronological
  filter_tags: [],
  filter_groups: [],
  filter_tags_exclude: [],
  filter_groups_exclude: [],
  max_items: 0, // 0 = no limit
  hide_when_empty: false,
  default_icon: 'mdi:bell-outline',
  default_icon_color: 'var(--primary-color)',
  confirm_dismiss: false,
  show_open_action: true,
  // YAML-only — deliberately not in the visual editor (see
  // NotifyDashboardCardEditor's header comment): this is a debugging aid,
  // not a real feature, so an editor field for it would just invite
  // permanently-on debug metadata nobody meant to keep. dismissed shows
  // recently-dismissed items too (faded, no close button, with a reason
  // chip) instead of hiding them like the card normally does.
  debug: { tag: false, group: false, timeout: false, dismissed: false },
};

const CARD_CSS = `
  :host {
    display: block;
    font-family: var(--ha-font-family-body, inherit);
    -webkit-font-smoothing: var(--ha-font-smoothing, auto);
  }
  :host(.hidden) { display: none !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }

  /* A low-opacity color-mix wash over the row background, not solid text/
     background: color is user-supplied and arbitrary, so a full-strength
     fill risks failing WCAG contrast against title/message text, which
     keeps using the theme's own --primary-text-color regardless. Mixing at
     a low percentage keeps it a subtle tint layered on top of the card's
     own background (rather than a flat replacement) so it still reads
     correctly over busy wallpapers and holds up in both light and dark
     themes. Transparent by default so rows without a color still look
     exactly like any other row. */
  .row {
    display: flex; flex-direction: column; padding: 12px 16px; gap: 14px;
    background: transparent;
  }
  .row + .row { border-top: 1px solid var(--divider-color, rgba(0,0,0,.06)); }
  /* debug.dismissed only — a recently-dismissed item shown as read-only
     history, not a live one. */
  .row-ghost { opacity: .5; }

  /* flex-start (not center): icon/dismiss must stay pinned to the top and
     never sink down when the message spans multiple lines. Short content
     (e.g. just a title) gets vertically centered instead via .content
     itself, see below. */
  .row-main { display: flex; align-items: flex-start; gap: 14px; }

  .icon-wrap {
    width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
  }
  .icon-wrap.clickable { cursor: pointer; -webkit-tap-highlight-color: transparent; }
  ha-icon { --mdc-icon-size: 20px; pointer-events: none; display: flex; }

  /* min-height matching .icon-wrap: for short content (no message) this
     clamps the box to 38px and justify-content centers the title within it,
     matching the icon. For longer content this has no effect — the box just
     grows along with it and everything stacks from the top, same as the
     icon. */
  .content {
    flex: 1; min-width: 0; min-height: 38px;
    display: flex; flex-direction: column; justify-content: center;
  }
  .content.clickable { cursor: pointer; }
  .title {
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.3);
  }
  /* Holds title + critical-text together as one line — see .critical-text
     below for why this has to be a single flex row instead of two
     independently positioned boxes. align-items: flex-start (not center)
     keeps critical-text pinned to title's *first* line if title wraps. */
  .header-line { display: flex; align-items: flex-start; gap: 8px; }
  .header-line > .title { flex: 1; min-width: 0; }
  .subtitle {
    font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--secondary-text-color); line-height: var(--ha-line-height-condensed, 1.3);
    margin-top: 2px;
  }
  /* Whenever title/critical_text are both absent, subtitle becomes
     .content's first child instead — it shouldn't carry the same top
     margin then as when it's following a title line above it. */
  .subtitle:first-child { margin-top: 0; }
  .message {
    font-size: var(--ha-font-size-s, 12px); color: var(--primary-text-color);
    line-height: var(--ha-line-height-condensed, 1.3); margin-top: 3px; white-space: pre-wrap;
  }
  .chronometer {
    /* The live timer replaces the message line entirely (same as iOS) — it
       needs to read as real content, not a small muted caption smaller
       than title/message. Size/weight carry that emphasis, not color:
       --primary-color is a theme accent with no contrast guarantee against
       the card surface (same reason data.color stays a decorative stripe,
       never text/background) — --primary-text-color is what HA themes
       actually keep legible here. */
    font-size: var(--ha-font-size-l, 20px); font-weight: var(--ha-font-weight-bold, 700);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.3);
    margin-top: 4px; font-variant-numeric: tabular-nums;
  }
  .timestamp {
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    margin-top: 3px;
  }
  /* debug metadata (tag/group/timeout) — same shape as package-tracker-card's
     .carrier row: plain inline icon+text pairs joined by a "·" separator, no
     pill/background/border-radius (confirmed directly against its actual
     source — no chip/pill class exists there at all). */
  .debug-row {
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    line-height: var(--ha-line-height-condensed, 1.3);
    margin-top: 4px; display: flex; align-items: center; gap: 3px; flex-wrap: wrap;
  }
  .debug-row ha-icon { --mdc-icon-size: 13px; flex-shrink: 0; }
  .debug-sep { margin: 0 2px; opacity: .5; }
  /* Lives *inside* .content's .header-line, next to title — not as a
     separate box next to .content in row-main. .content vertically centers
     short content against the 38px icon (min-height + justify-content:
     center, see .content's own comment), so a box outside of it can never
     reliably track where the first line actually ends up: with just one
     short line, that line sits centered partway down a 38px box, not flush
     at the top — a fixed "flush top" position elsewhere then drifts out of
     sync with it, worse still whenever title happens to be missing and the
     first line becomes something else entirely. Being on the same flex row
     as title fixes that structurally: critical-text now moves exactly
     wherever that line moves, whatever it is. margin-left: auto pushes it
     to the end of the row on its own, whether or not a title sibling with
     flex: 1 exists next to it. Capped width + wrapping (not truncation —
     this project never truncates, see the file header) so a long
     critical_text doesn't crowd out the title. */
  .critical-text {
    flex-shrink: 0; margin-left: auto; max-width: 96px; text-align: right;
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.3);
    overflow-wrap: break-word;
  }

  /* Reuses .icon-wrap for the exact box (38x38, round) — ha-icon-button
     internally forces a fixed ~48x48 touch target that ignores
     --mdc-icon-button-size, so it can never be made exactly equal to the
     main icon. */
  .row-dismiss {
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: background-color 150ms ease-in-out;
  }
  .row-dismiss:hover, .row-dismiss:focus-visible {
    background: color-mix(in srgb, var(--secondary-text-color) 15%, transparent);
  }
  .row-dismiss:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }

  .row-actions { display: flex; flex-direction: column; gap: 8px; margin-left: 52px; }
  .row-actions ha-control-button { width: 100%; }
  /* currentColor automatically follows the button's text color, including
     destructive (then red via --control-button-icon-color: var(--error-color)). */
  .action-spinner {
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid color-mix(in srgb, currentColor 25%, transparent);
    border-top-color: currentColor;
    animation: notify-dashboard-spin 0.8s linear infinite;
  }
  @keyframes notify-dashboard-spin { to { transform: rotate(360deg); } }

  /* Looks like an empty action feature that fills with notification_icon_color
     — same width as the action buttons, but deliberately shorter (14px vs the
     ~36-40px of ha-control-button). --control-button-border-radius (if
     ha-control-button actually sets it — confirmed against the real HA
     frontend source) takes precedence; the 5px fallback is deliberately
     smaller than the button radius itself and than half the height (7px) —
     otherwise the browser clamps it into a full pill/capsule shape regardless,
     instead of a light rounding. */
  .progress-wrap { display: flex; align-items: center; gap: 8px; }
  .progress-feature {
    position: relative;
    width: 100%; height: 14px; border-radius: var(--control-button-border-radius, 5px);
    background: color-mix(in srgb, var(--secondary-text-color) 12%, transparent);
    overflow: hidden;
  }
  .progress-wrap .progress-feature { flex: 1; width: auto; }
  .progress-fill { height: 100%; border-radius: inherit; transition: width 300ms ease-in-out; }
  /* progress_indeterminate: no known percentage, so a sliding segment
     instead of a width-based fill — same track/box as the regular bar. */
  .progress-fill.indeterminate {
    position: absolute; top: 0; height: 100%; width: 40%;
    transition: none;
    animation: notify-dashboard-indeterminate 1.4s ease-in-out infinite;
  }
  @keyframes notify-dashboard-indeterminate {
    0% { left: -40%; }
    100% { left: 100%; }
  }
  /* Same width as the dismiss button (.icon-wrap, 38px), text centered. */
  .progress-label {
    flex-shrink: 0; width: 38px; text-align: center;
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

  /* Without this, a row's straight left edge (where the color accent
     stripe paints) overhangs past ha-card's own rounded corners — visible
     on the first/last row in single layout, and on every row in split
     layout, since there each row gets its own fully-rounded card. ha-card
     doesn't clip its own children by default. */
  ha-card { overflow: hidden; }
  .split-wrapper { display: flex; flex-direction: column; gap: 8px; }
  .split-wrapper ha-card .row { border-top: none; }

  .empty {
    padding: 28px 16px; text-align: center; color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 12px);
    display: flex; flex-direction: column; align-items: center; gap: 8px;
  }
`;

// Taken 1-to-1 from package-tracker-card-editor: tab bar + srow rows
// (label/desc on the left, ha-switch or ha-form on the right).
const EDITOR_CSS = `
  :host { display: block; }
  ha-form { display: block; }
  .editor-card {
    border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden; background: var(--ha-card-background, var(--card-background-color, #fff));
  }
  .tab-bar { display: flex; border-bottom: 1px solid var(--divider-color); }
  .tab-btn {
    flex: 1; padding: 12px 4px; border: none; background: none; font-family: inherit;
    font-size: 13px; font-weight: 500; color: var(--secondary-text-color); cursor: pointer;
    border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color .15s, border-color .15s;
  }
  .tab-btn:hover { color: var(--primary-text-color); }
  .tab-btn.active { color: var(--primary-color); border-bottom-color: var(--primary-color); font-weight: 600; }
  .tab-content { padding: 16px; }
  .section-label {
    font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--secondary-text-color); margin: 24px 0 0;
  }
  .section-label:first-child { margin-top: 0; }
  .settings-group { margin-top: 8px; }
  .srow {
    display: flex; align-items: center; justify-content: space-between; min-height: 48px;
    padding: 4px 2px; border-bottom: 1px solid var(--divider-color); gap: 8px;
  }
  .settings-group .srow:last-child { border-bottom: none; }
  .srow-text { flex: 1; min-width: 0; }
  .srow-label { font-size: 14px; color: var(--primary-text-color); display: block; }
  .srow-desc { font-size: 12px; color: var(--secondary-text-color); display: block; margin-top: 1px; }
  .version-link {
    display: block; font-size: 11px; color: var(--secondary-text-color); text-decoration: none;
    text-align: center; padding: 10px 16px 12px; border-top: 1px solid var(--divider-color);
  }
  .version-link:hover { text-decoration: underline; }
  ha-switch { flex-shrink: 0; }
`;

// Same pattern as package-tracker-card: TRANSLATIONS[hass.language], with
// 'en' as the fallback for untranslated languages. English is the default;
// Dutch is supported as an additional language, not the other way around.
const EDITOR_TRANSLATIONS = {
  nl: {
    content_tab: 'Bron',
    filter_tab: 'Filter',
    appearance_tab: 'Weergave',
    source_section: 'Bron',
    content_section: 'Inhoud',
    appearance_section: 'Weergave',
    behaviour_section: 'Gedrag',
    entity: 'Entiteit',
    entity_desc: 'Moet de Notify Dashboard sensor zijn (meestal sensor.notify_dashboard)',
    live_activities: 'Live activities',
    notifications: 'Notifications',
    layout: 'Indeling',
    layout_single: 'Eén kaart',
    layout_split: 'Losse kaarten',
    max_items: 'Max. aantal items',
    max_items_desc: '0 = geen limiet',
    filter_tags_section: 'Tags',
    filter_groups_section: 'Groepen',
    filter_include: 'Alleen deze tonen',
    filter_exclude: 'Verbergen',
    filter_desc: 'Komma-gescheiden, leeg = alles',
    filter_exclude_desc: 'Komma-gescheiden; wint van het veld hierboven',
    hide_when_empty: 'Verberg kaart als leeg',
    confirm_dismiss: 'Bevestiging bij dismissen',
    show_open_action: 'Open-knop tonen',
    show_open_action_desc: 'Getoond bij een item met een url; opent die.',
  },
  en: {
    content_tab: 'Source',
    filter_tab: 'Filter',
    appearance_tab: 'Appearance',
    source_section: 'Source',
    content_section: 'Content',
    appearance_section: 'Appearance',
    behaviour_section: 'Behaviour',
    entity: 'Entity',
    entity_desc: 'Must be the Notify Dashboard sensor (usually sensor.notify_dashboard)',
    live_activities: 'Live activities',
    notifications: 'Notifications',
    layout: 'Layout',
    layout_single: 'Single card',
    layout_split: 'Split cards',
    max_items: 'Max. items',
    max_items_desc: '0 = no limit',
    filter_tags_section: 'Tags',
    filter_groups_section: 'Groups',
    filter_include: 'Only show these',
    filter_exclude: 'Hide these',
    filter_desc: 'Comma-separated, empty = all',
    filter_exclude_desc: 'Comma-separated; wins over the field above',
    hide_when_empty: 'Hide card when empty',
    confirm_dismiss: 'Confirm before dismissing',
    show_open_action: 'Show Open button',
    show_open_action_desc: 'Shown for any item with a url; opens it.',
  },
};

// Runtime card strings (not editor-only) — same fallback convention as
// EDITOR_TRANSLATIONS: English by default, Dutch as an additional language.
const CARD_TRANSLATIONS = {
  nl: {
    dismiss: 'Sluiten',
    empty: 'Geen meldingen',
    confirm_dismiss: 'Melding verwijderen?',
    just_now: 'Zojuist',
    minutes_ago: (n) => `${n}m geleden`,
    hours_ago: (n) => `${n}u geleden`,
    days_ago: (n) => `${n}d geleden`,
  },
  en: {
    dismiss: 'Dismiss',
    empty: 'No notifications',
    confirm_dismiss: 'Remove this notification?',
    just_now: 'Just now',
    minutes_ago: (n) => `${n}m ago`,
    hours_ago: (n) => `${n}h ago`,
    days_ago: (n) => `${n}d ago`,
  },
};

function formatRelativeTime(unixSeconds, uiTr) {
  const diff = Math.max(0, Date.now() / 1000 - unixSeconds);
  const minutes = Math.floor(diff / 60);
  if (minutes < 1) return uiTr.just_now;
  if (minutes < 60) return uiTr.minutes_ago(minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return uiTr.hours_ago(hours);
  return uiTr.days_ago(Math.floor(hours / 24));
}

function mk(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}

function mkIcon(icon, color) {
  const ico = document.createElement('ha-icon');
  ico.setAttribute('icon', icon || 'mdi:bell-outline');
  if (color) ico.style.color = color;
  return ico;
}

function matchesFilter(item, filterTags, filterGroups, excludeTags, excludeGroups) {
  const tag = item.data?.tag;
  const group = item.data?.group;
  if (filterTags.length && !filterTags.includes(tag)) return false;
  if (filterGroups.length && !filterGroups.includes(group)) return false;
  // Exclude wins over include — an explicit denylist entry should always
  // hide the item, even if it also happens to match the include list.
  if (excludeTags.length && excludeTags.includes(tag)) return false;
  if (excludeGroups.length && excludeGroups.includes(group)) return false;
  return true;
}

// Editor-only helpers (content-array toggles, filter_tags/filter_groups as
// comma-separated text instead of separate chips).
function toggleInArray(arr, value, include) {
  const set = new Set(arr);
  if (include) set.add(value);
  else set.delete(value);
  return [...set];
}

function splitCsv(value) {
  return (value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function deepEqual(a, b) {
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => deepEqual(v, b[i]));
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every((k) => deepEqual(a[k], b[k]));
  }
  return a === b;
}

// Only keep keys that differ from CARD_DEFAULTS (or have no default at all,
// e.g. `type`/`entity`) — _normalize merges every default into `_config` for
// internal rendering, but firing that whole merged object back would
// persist every untouched default into the saved YAML.
function stripDefaults(config) {
  const out = {};
  for (const [key, value] of Object.entries(config)) {
    if (key in CARD_DEFAULTS && deepEqual(value, CARD_DEFAULTS[key])) continue;
    out[key] = value;
  }
  return out;
}

class NotifyDashboardCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `<style>${CARD_CSS}</style><div id="root"></div>`;
    this._root = this.shadowRoot.getElementById('root');
    this._lastUpdated = null;
    this._built = false;
    // Rows (and their chronometer intervals) stay alive across renders,
    // keyed by _kind:id — a re-render only rebuilds what actually changed
    // in terms of updated_at/created_at, instead of tearing everything down
    // and rebuilding it. See _syncRows().
    this._rows = new Map();
    this._rowContainer = null;
    this._containerKind = null;
    // Lovelace can create this element and assign `.hass` before our own
    // module has finished loading/registering the class (the resource is
    // fetched as an ES module, which loads asynchronously) — that first
    // assignment lands as a plain own-property on the not-yet-upgraded
    // element, which then permanently shadows the `set hass()` accessor
    // below once upgrade completes. Every *later* `.hass = ...` from
    // Lovelace becomes a silent plain property write that never reaches
    // the setter again, so the card renders once (whatever hass happened
    // to be at upgrade time) and then never reactively updates — exactly
    // "looks right after a refresh, never updates live" symptom. Standard
    // fix: if that own property exists already, capture it, delete it, and
    // re-assign so it actually goes through the setter this one time.
    if (Object.prototype.hasOwnProperty.call(this, 'hass')) {
      const preUpgradeHass = this.hass;
      delete this.hass;
      this.hass = preUpgradeHass;
    }
  }

  disconnectedCallback() {
    // Without cleanup, cached rows (and their chronometer intervals) would
    // keep living forever after the card leaves the DOM, e.g. on a view
    // switch.
    // TEMPORARY diagnostic logging — remove once the refresh-required bug
    // is actually located.
    console.debug('[notify-dashboard-card DEBUG] disconnectedCallback');
    this._teardownRows();
  }

  connectedCallback() {
    // Lovelace detaches and reattaches a card's DOM node (without
    // destroying the element) when entering/exiting dashboard edit mode —
    // that fires disconnectedCallback above, which empties the row
    // container. The entity's last_updated usually hasn't changed across
    // that move, so set hass's guard below would otherwise never notice
    // anything needs rebuilding, leaving the card an empty shell until a
    // full page refresh recreates it. Force a fresh render on every
    // (re)connect instead of relying on that guard alone.
    // TEMPORARY diagnostic logging — remove once the refresh-required bug
    // is actually located.
    console.debug('[notify-dashboard-card DEBUG] connectedCallback', {
      hasHass: !!this._hass,
      hasConfig: !!this._config,
    });
    if (this._hass && this._config) this._render();
  }

  _teardownRows() {
    // Always also cleans up the DOM node itself (not just the intervals) —
    // that makes this a real "remove everything" primitive, usable both by
    // paths that wipe the whole root afterward anyway and by setConfig(),
    // where that doesn't happen and a node left in place would otherwise
    // become a silent duplicate.
    for (const entry of this._rows.values()) {
      entry.intervalIds.forEach((id) => clearInterval(id));
      entry.el.remove();
    }
    this._rows.clear();
  }

  setConfig(config) {
    if (!config) throw new Error('notify-dashboard-card: config missing');
    this._config = { ...CARD_DEFAULTS, ...config };
    this._entity = config.entity || 'sensor.notify_dashboard';
    // Config can affect how every row renders (icons, buttons,
    // confirm_dismiss, ...) — the row cache is then no longer valid, so
    // everything needs to be freshly rebuilt on the next render.
    this._teardownRows();
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const state = hass.states[this._entity];
    const ts = state?.last_updated ?? null;
    // TEMPORARY diagnostic logging — remove once the refresh-required bug
    // is actually located. Prefixed so it's easy to filter/find and strip.
    console.debug('[notify-dashboard-card DEBUG] set hass() called', {
      entity: this._entity,
      stateFound: !!state,
      ts,
      lastUpdated: this._lastUpdated,
      changed: ts !== this._lastUpdated,
      built: this._built,
      itemCount: state?.attributes?.items?.length,
    });
    if (ts !== this._lastUpdated || !this._built) {
      this._lastUpdated = ts;
      this._render();
    }
  }

  _uiTr() {
    return CARD_TRANSLATIONS[this._hass?.language] || CARD_TRANSLATIONS['en'];
  }

  _dismiss(id) {
    if (this._config.confirm_dismiss && !window.confirm(this._uiTr().confirm_dismiss)) return;
    this._hass.callService('notify_dashboard', 'dismiss', { id });
  }

  _handleAction(action, item, actionData) {
    if (!action) return;
    // Runs through the notify_dashboard.fire_action service (which calls
    // hass.bus.async_fire server-side) instead of sending the fire_event
    // websocket action from here — that one requires admin rights in HA
    // core, so it would silently do nothing for non-admin dashboard
    // viewers (e.g. a kiosk tablet). Service calls don't have that
    // restriction. Same event shape as the companion app (action,
    // action_data, tag), so existing wait_for_trigger automations keep
    // working unchanged.
    const payload = { action };
    if (item.data?.tag) payload.tag = item.data.tag;
    if (actionData != null) payload.action_data = actionData;
    this._hass
      .callService('notify_dashboard', 'fire_action', payload)
      .catch((err) => console.warn('notify-dashboard-card: could not send action', err));
  }

  _openUrl(url) {
    if (!url) return;
    if (url.startsWith('/')) {
      history.pushState(null, '', url);
      window.dispatchEvent(new CustomEvent('location-changed', { bubbles: true, composed: true }));
    } else {
      window.open(url, '_blank');
    }
  }

  _formatChrono(remainingSeconds) {
    const abs = Math.abs(Math.round(remainingSeconds));
    const h = Math.floor(abs / 3600);
    const m = Math.floor((abs % 3600) / 60);
    const s = abs % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  }

  _renderRow(item, intervalIds) {
    const data = item.data || {};
    const icon = data.notification_icon || this._config.default_icon;
    const color = data.notification_icon_color || this._config.default_icon_color;
    const url = data.url || data.clickAction || null;
    const persistent = !!data.persistent;
    const actions = Array.isArray(data.actions) ? data.actions : [];
    // Only ever true when debug.dismissed asked _collectItems() to include
    // these at all — faded + no close button (dismissing an already-
    // dismissed entry would just fail server-side), so it reads as a
    // read-only history entry, not a live, actionable one.
    const isDismissed = !!item.dismissed_at;

    const row = mk('div', 'row' + (isDismissed ? ' row-ghost' : ''));
    // Low-opacity wash, not a solid fill — see the .row CSS comment on why
    // an arbitrary user-supplied color stays off of text/large surfaces.
    if (data.color) row.style.background = `color-mix(in srgb, ${data.color} 12%, transparent)`;
    const main = mk('div', 'row-main');

    const iconWrap = mk('div', 'icon-wrap' + (url ? ' clickable' : ''));
    if (url) {
      iconWrap.style.background = `color-mix(in srgb, ${color} 15%, transparent)`;
    }
    iconWrap.appendChild(mkIcon(icon, color));

    const content = mk('div', 'content' + (url ? ' clickable' : ''));
    // Only render what's actually there — an empty div would otherwise push
    // unwanted whitespace into the row.
    // Nothing is ever shown twice: once message has filled in the title,
    // that same text doesn't also appear as the message.
    const hasChronometer =
      item._kind === 'live_activities' && !!data.chronometer && Number.isFinite(data.when);
    // critical_text is replaced by the timer once chronometer is set, same
    // as the companion app's own status-bar-chip behavior — never both.
    const hasCriticalText = item._kind === 'live_activities' && !hasChronometer && !!data.critical_text;
    const titleText = item.title || item.message || null;
    // The chronometer takes the message's spot entirely (same as iOS) —
    // if there's no separate message to replace (message already became
    // titleText above), it just becomes the one supplementary line instead.
    const showMessage = !!item.title && !!item.message && !hasChronometer;

    // critical-text rides along on the same line as title/title-fallback,
    // *inside* .content, rather than as a separate box next to it — .content
    // vertically centers short content against the 38px icon (see its CSS
    // comment), so a box outside of it can never reliably track where that
    // first line actually ends up. Nesting them in one flex row means
    // critical-text moves exactly wherever that line moves, title or not.
    if (hasCriticalText) {
      const headerLine = mk('div', 'header-line');
      if (titleText) headerLine.appendChild(mk('div', 'title', titleText));
      headerLine.appendChild(mk('div', 'critical-text', data.critical_text));
      content.appendChild(headerLine);
    } else if (titleText) {
      content.appendChild(mk('div', 'title', titleText));
    }
    if (data.subtitle) content.appendChild(mk('div', 'subtitle', data.subtitle));

    // when_relative adds when to updated_at (the moment we received it)
    // instead of to the render time, so the target doesn't shift on every
    // re-render. Ticks locally via setInterval — no repeated pushes needed,
    // same as with the companion app.
    if (hasChronometer) {
      const target = data.when_relative ? (item.updated_at || 0) + data.when : data.when;
      const chrono = mk('div', 'chronometer');
      const update = () => {
        chrono.textContent = this._formatChrono(target - Date.now() / 1000);
      };
      update();
      intervalIds.push(setInterval(update, 1000));
      content.appendChild(chrono);
    } else if (showMessage) {
      content.appendChild(mk('div', 'message', item.message));
    }

    // Relative "sent X ago" for regular notifications — live activities
    // have the chronometer/critical_text instead. Coarse (minute)
    // granularity, so a minute-interval tick is enough — no need for
    // chronometer's 1s.
    if (item._kind === 'notifications' && Number.isFinite(item.created_at)) {
      const uiTr = this._uiTr();
      const ts = mk('div', 'timestamp');
      const update = () => {
        ts.textContent = formatRelativeTime(item.created_at, uiTr);
      };
      update();
      intervalIds.push(setInterval(update, 60000));
      content.appendChild(ts);
    }

    // YAML-only debugging aid (see CARD_DEFAULTS) — raw tag/group/timeout
    // metadata as a plain inline row of icon+text pairs joined by "·", same
    // shape as package-tracker-card's .carrier row (confirmed directly
    // against its actual source — not a pill/chip, no background at all).
    // Static, not live-ticking: it's showing the configured values as sent,
    // not a countdown. The dismiss-reason chip always shows on a dismissed
    // item (regardless of the tag/group/timeout toggles) — that's the
    // whole point of turning debug.dismissed on in the first place.
    const debugCfg = this._config.debug;
    if (debugCfg && (debugCfg.tag || debugCfg.group || debugCfg.timeout || isDismissed)) {
      const tag = data.tag;
      const group = data.group;
      const timeout = data.timeout;
      const parts = [];
      if (debugCfg.tag && tag) parts.push({ icon: 'mdi:tag-outline', text: tag });
      if (debugCfg.group && group) parts.push({ icon: 'mdi:folder-multiple-outline', text: group });
      if (debugCfg.timeout && Number.isFinite(timeout)) {
        parts.push({ icon: 'mdi:timer-outline', text: this._formatChrono(timeout) });
      }
      if (isDismissed) {
        parts.push({
          icon: 'mdi:archive-arrow-down-outline',
          text: item.dismiss_reason || 'dismissed',
        });
      }
      if (parts.length) {
        const debugRow = mk('div', 'debug-row');
        parts.forEach((p, i) => {
          if (i > 0) debugRow.appendChild(mk('span', 'debug-sep', '·'));
          debugRow.appendChild(mkIcon(p.icon, 'var(--secondary-text-color)'));
          debugRow.appendChild(document.createTextNode(p.text));
        });
        content.appendChild(debugRow);
      }
    }

    if (url) {
      // Tap = navigate, doesn't dismiss (see design doc 3.7).
      const onTap = () => this._openUrl(url);
      iconWrap.addEventListener('click', onTap);
      content.addEventListener('click', onTap);
    }

    main.appendChild(iconWrap);
    main.appendChild(content);

    // persistent only blocks manual dismiss for notifications — a live
    // activity stays dismissable via the close button regardless (matches
    // store.py's is_persistent(), which bakes in the same exception).
    // Already-dismissed (debug.dismissed view) never gets one either — the
    // backend would just reject dismissing something already inactive.
    if (!isDismissed && (!persistent || item._kind === 'live_activities')) {
      // Same primitive (icon-wrap) as the main icon instead of ha-icon-button,
      // so the box (and thus the hover background) is exactly 38x38 — matching
      // the main icon, and at the same height since both are plain flex
      // children of row-main.
      const closeBtn = mk('div', 'icon-wrap row-dismiss');
      closeBtn.setAttribute('role', 'button');
      closeBtn.tabIndex = 0;
      closeBtn.setAttribute('aria-label', this._uiTr().dismiss);
      closeBtn.appendChild(mkIcon('mdi:close', 'var(--secondary-text-color)'));
      const onDismiss = () => this._dismiss(item.id);
      closeBtn.addEventListener('click', onDismiss);
      closeBtn.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onDismiss();
        }
      });
      main.appendChild(closeBtn);
    }

    row.appendChild(main);
    // The Open button is optional (show_open_action) — tapping the icon/
    // content already navigates anyway, this button is purely an explicit,
    // visible alternative for that.
    const showOpenBtn = !!url && this._config.show_open_action;

    // Progress bar: only for live activities, and only if both fields are
    // present (same condition as the companion app: progress_max must be
    // set for a bar to appear). progress: -1 (the "done" signal) already
    // removes the live activity server-side, so it never reaches here.
    const hasProgress =
      item._kind === 'live_activities' &&
      Number.isFinite(data.progress) &&
      Number.isFinite(data.progress_max) &&
      data.progress_max > 0;

    // A concrete percentage wins if we have one — it's strictly more useful
    // than a spinner. Android's native API lets progress_indeterminate
    // override stale progress values left behind from an earlier
    // setProgress() call, but that quirk doesn't apply here: our store does
    // a full replace on every update, so if both are present they arrived
    // together in the same payload, deliberately. Indeterminate is only the
    // fallback for when there's no usable percentage to show.
    const hasIndeterminateProgress =
      item._kind === 'live_activities' && data.progress_indeterminate === true && !hasProgress;

    if (hasIndeterminateProgress || hasProgress || showOpenBtn || actions.length) {
      // Always stacked vertically — labels are often too long for a
      // horizontal row of equally-sized buttons.
      const rowActions = mk('div', 'row-actions');
      if (hasIndeterminateProgress) {
        const bar = mk('div', 'progress-feature');
        const fill = mk('div', 'progress-fill indeterminate');
        fill.style.background = color;
        bar.appendChild(fill);
        rowActions.appendChild(bar);
      } else if (hasProgress) {
        const pct = Math.max(0, Math.min(100, (data.progress / data.progress_max) * 100));
        const bar = mk('div', 'progress-feature');
        const fill = mk('div', 'progress-fill');
        fill.style.width = `${pct}%`;
        fill.style.background = color;
        bar.appendChild(fill);
        const wrap = mk('div', 'progress-wrap');
        wrap.appendChild(bar);
        wrap.appendChild(mk('span', 'progress-label', `${Math.round(pct)}%`));
        rowActions.appendChild(wrap);
      }
      actions.forEach((a) => {
        const btn = document.createElement('ha-control-button');
        btn.textContent = a.title || a.action;
        // destructive (companion-app field): red text instead of the default color.
        if (a.destructive) {
          btn.style.setProperty('--control-button-icon-color', 'var(--error-color)');
        }
        let clicked = false;
        btn.addEventListener('click', () => {
          // Own flag instead of relying on ha-control-button's disabled
          // state — prevents double-tapping regardless of whether that
          // element handles disabled correctly itself.
          if (clicked) return;
          clicked = true;
          btn.textContent = '';
          btn.appendChild(mk('div', 'action-spinner'));
          this._handleAction(a.action, item, a.action_data);
          // Small delay to confirm the tap was processed, then dismiss —
          // doesn't apply to the Open button (which only navigates).
          setTimeout(() => {
            this._hass
              .callService('notify_dashboard', 'dismiss', { id: item.id })
              .catch(() => {}); // e.g. already gone, or persistent — nothing to do then
          }, 600);
        });
        rowActions.appendChild(btn);
      });
      if (showOpenBtn) {
        // After the actions (not before) — Open is the generic fallback
        // tap, not a primary action. Less prominent once real actions
        // exist too.
        const openBtn = document.createElement('ha-control-button');
        openBtn.textContent = 'Open';
        if (actions.length) {
          openBtn.style.setProperty('--control-button-icon-color', 'var(--secondary-text-color)');
          openBtn.style.setProperty('--control-button-background-opacity', '0.08');
        }
        openBtn.addEventListener('click', () => this._openUrl(url));
        rowActions.appendChild(openBtn);
      }
      row.appendChild(rowActions);
    }

    return row;
  }

  _collectItems() {
    const state = this._hass.states[this._entity];
    const attrs = state?.attributes || {};
    const {
      filter_tags: filterTags,
      filter_groups: filterGroups,
      filter_tags_exclude: excludeTags,
      filter_groups_exclude: excludeGroups,
      content,
      group_order: groupOrder,
    } = this._config;

    const byNewest = (a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0);
    // chronological sorts the combined list again anyway — a per-kind sort
    // here would then just be pure repeated work.
    const sortPerKind = groupOrder !== 'chronological';

    // `items` holds both kinds together, told apart by data.live_update
    // (same field the companion app itself uses — no separate kind label
    // on the sensor) and both active + recently-dismissed entries
    // (dismissed_at set) — normally the card only shows active ones, unless
    // the YAML-only debug.dismissed flag asks to see recently-dismissed
    // ones too (see _renderRow for how those are visually distinguished).
    // One pass over the raw list — skip dismissed, filter, and bucket by
    // kind all at once — instead of filtering the same list twice (once
    // per kind).
    const showDismissed = !!this._config.debug?.dismissed;
    const live = [];
    const notif = [];
    for (const item of attrs.items || []) {
      if (item.dismissed_at && !showDismissed) continue;
      const kind = item.data?.live_update ? 'live_activities' : 'notifications';
      if (!content.includes(kind)) continue;
      if (!matchesFilter(item, filterTags, filterGroups, excludeTags, excludeGroups)) continue;
      (kind === 'live_activities' ? live : notif).push({ ...item, _kind: kind });
    }
    if (sortPerKind) {
      live.sort(byNewest);
      notif.sort(byNewest);
    }

    let items;
    if (groupOrder === 'chronological') {
      items = [...live, ...notif].sort(byNewest);
    } else if (groupOrder === 'notifications_first') {
      items = [...notif, ...live];
    } else {
      items = [...live, ...notif];
    }

    if (this._config.max_items > 0) items = items.slice(0, this._config.max_items);
    return items;
  }

  // Sets (or reuses) the rows for `items` as children of this._rowContainer,
  // in the right order. A row is only actually rebuilt (and thus only then
  // gets a new chronometer interval) if updated_at/created_at has changed —
  // an unchanged row elsewhere in the card is left completely alone, even
  // when another row just updated. Without this, every chronometer would
  // tick again from zero whenever anything at all changes in the card.
  _syncRows(items, layout) {
    const seen = new Set();
    let prevEl = null;

    for (const item of items) {
      const key = `${item._kind}:${item.id}`;
      seen.add(key);
      const updatedAt = item.updated_at || item.created_at || 0;
      let entry = this._rows.get(key);

      if (!entry || entry.updatedAt !== updatedAt) {
        if (entry) {
          entry.intervalIds.forEach((id) => clearInterval(id));
          entry.el.remove(); // otherwise the old node stays behind as a stale duplicate
        }
        const intervalIds = [];
        const row = this._renderRow(item, intervalIds);
        const el = layout === 'split' ? document.createElement('ha-card') : row;
        if (layout === 'split') el.appendChild(row);
        entry = { el, intervalIds, updatedAt };
        this._rows.set(key, entry);
      }

      const expectedNext = prevEl ? prevEl.nextSibling : this._rowContainer.firstChild;
      if (expectedNext !== entry.el) {
        this._rowContainer.insertBefore(entry.el, expectedNext);
      }
      prevEl = entry.el;
    }

    for (const [key, entry] of this._rows) {
      if (!seen.has(key)) {
        entry.intervalIds.forEach((id) => clearInterval(id));
        entry.el.remove();
        this._rows.delete(key);
      }
    }
  }

  _render() {
    if (!this._hass || !this._config) return;
    const items = this._collectItems();
    this._built = true;
    // TEMPORARY diagnostic logging — remove once the refresh-required bug
    // is actually located.
    console.debug('[notify-dashboard-card DEBUG] _render() ran', {
      collectedCount: items.length,
      ids: items.map((i) => i.id),
      rowsInMap: this._rows.size,
    });

    if (!items.length && this._config.hide_when_empty) {
      this.classList.add('hidden');
      this._teardownRows();
      this._root.innerHTML = '';
      this._containerKind = null;
      return;
    }
    this.classList.remove('hidden');

    if (!items.length) {
      this._teardownRows();
      if (this._containerKind !== 'empty') {
        this._root.innerHTML = '';
        const card = document.createElement('ha-card');
        const empty = mk('div', 'empty');
        const ico = mkIcon(this._config.default_icon);
        ico.style.setProperty('--mdc-icon-size', '32px');
        ico.style.opacity = '.3';
        empty.appendChild(ico);
        empty.appendChild(mk('div', null, this._uiTr().empty));
        card.appendChild(empty);
        this._root.appendChild(card);
        this._containerKind = 'empty';
      }
      return;
    }

    const layout = this._config.layout === 'split' ? 'split' : 'single';
    if (this._containerKind !== layout) {
      // Layout switched (or first render) — replace the container itself too;
      // _syncRows() then sees no existing rows and rebuilds everything fresh.
      this._teardownRows();
      this._root.innerHTML = '';
      this._rowContainer =
        layout === 'split' ? mk('div', 'split-wrapper') : document.createElement('ha-card');
      this._root.appendChild(this._rowContainer);
      this._containerKind = layout;
    }

    this._syncRows(items, layout);
  }

  getCardSize() {
    if (this._config?.hide_when_empty && this.classList.contains('hidden')) return 0;
    return 3;
  }

  getGridOptions() {
    // Notification/activity lists vary a lot in height, so rows is 'auto'
    // (grow to fit content) rather than a fixed row count; full-width by
    // default since a notification list cramped into a narrow column reads
    // poorly.
    return { columns: 'full', rows: 'auto' };
  }

  static getStubConfig(hass) {
    // Prefer a real entity from this integration (matched via the entity
    // registry's platform field, not a hardcoded id) so the card picker's
    // live preview actually renders instead of showing "entity not found".
    const match = hass?.entities
      ? Object.entries(hass.entities).find(([, e]) => e.platform === 'notify_dashboard')
      : null;
    return { ...CARD_DEFAULTS, entity: match ? match[0] : 'sensor.notify_dashboard' };
  }

  static getConfigElement() {
    return document.createElement('notify-dashboard-card-editor');
  }
}

// Visual editor — tab skeleton (tab bar, _fire/_ownFire echo protection,
// ha-switch/ha-form rows) taken 1-to-1 from package-tracker-card.
// debug (tag/group/timeout metadata, see CARD_DEFAULTS) is deliberately not
// included here either — it's a YAML-only debugging aid, not a real
// feature, so an editor field for it would invite permanently-on debug
// metadata nobody meant to keep around.
class NotifyDashboardCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = null;
    this._hass = null;
    this._built = false;
    this._ownFire = false;
    this._tab = 'content';
    // Same defensive fix as NotifyDashboardCard's constructor — see its
    // comment for why this is needed.
    if (Object.prototype.hasOwnProperty.call(this, 'hass')) {
      const preUpgradeHass = this.hass;
      delete this.hass;
      this.hass = preUpgradeHass;
    }
  }

  set hass(hass) {
    this._hass = hass;
    this.shadowRoot.querySelectorAll('ha-form').forEach((f) => {
      f.hass = hass;
    });
  }

  setConfig(config) {
    if (!this._built) {
      this._config = this._normalize(config);
      this._init();
      return;
    }
    // The config-changed we just fired ourselves comes back here through
    // Lovelace — without this guard that would trigger a pointless full
    // re-render (and could reset the active tab).
    if (this._ownFire) {
      this._ownFire = false;
      return;
    }
    this._config = this._normalize(config);
    this._renderTab();
  }

  _normalize(config) {
    return { ...CARD_DEFAULTS, ...config };
  }

  _uiTr() {
    return EDITOR_TRANSLATIONS[this._hass?.language] || EDITOR_TRANSLATIONS['en'];
  }

  _fire(config) {
    // Deliberately no re-render here: every row in _renderContent /
    // _renderFilter / _renderAppearance is unconditional (none of them
    // show/hide or relabel based on another row's value), and each row's
    // own widget already reflects what the user just typed/toggled. Doing
    // a synchronous _renderTab() after every keystroke used to tear down
    // and recreate the ha-form text inputs mid-typing, kicking focus out
    // after every character.
    this._config = config;
    this._ownFire = true;
    this.dispatchEvent(
      new CustomEvent('config-changed', { detail: { config: stripDefaults(config) }, bubbles: true, composed: true })
    );
  }

  _init() {
    this._built = true;
    const root = this.shadowRoot;
    root.innerHTML = '';
    root.appendChild(Object.assign(document.createElement('style'), { textContent: EDITOR_CSS }));

    const uiTr = this._uiTr();
    const card = mk('div', 'editor-card');
    const tabBar = mk('div', 'tab-bar');
    [
      ['content', uiTr.content_tab],
      ['filter', uiTr.filter_tab],
      ['appearance', uiTr.appearance_tab],
    ].forEach(([id, label]) => {
      const btn = Object.assign(document.createElement('button'), {
        className: 'tab-btn' + (id === this._tab ? ' active' : ''),
        textContent: label,
      });
      btn.dataset.tab = id;
      btn.addEventListener('click', () => {
        if (this._tab === id) return;
        this._tab = id;
        tabBar.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === id));
        this._renderTab();
      });
      tabBar.appendChild(btn);
    });
    card.appendChild(tabBar);

    this._content = mk('div', 'tab-content');
    card.appendChild(this._content);
    card.appendChild(Object.assign(document.createElement('a'), {
      href: 'https://github.com/klaptafel/ha-notify-dashboard',
      target: '_blank',
      rel: 'noopener noreferrer',
      className: 'version-link',
      textContent: 'Notify Dashboard Card v' + CARD_VERSION,
    }));
    root.appendChild(card);
    this._renderTab();
  }

  _renderTab() {
    this._content.innerHTML = '';
    if (this._tab === 'content') this._renderContent();
    else if (this._tab === 'filter') this._renderFilter();
    else if (this._tab === 'appearance') this._renderAppearance();
    if (this._hass) {
      this.shadowRoot.querySelectorAll('ha-form').forEach((f) => {
        f.hass = this._hass;
      });
    }
  }

  // ── Content ───────────────────────────────────────────────────────────────

  _renderContent() {
    const root = this._content;
    const c = this._config;
    const uiTr = this._uiTr();

    root.appendChild(mk('div', 'section-label', uiTr.source_section));
    const sourceGroup = mk('div', 'settings-group');
    sourceGroup.appendChild(
      this._mkFormRow(uiTr.entity, uiTr.entity_desc, { entity: { domain: 'sensor' } }, c.entity || 'sensor.notify_dashboard', (val) =>
        this._fire({ ...c, entity: val })
      )
    );
    root.appendChild(sourceGroup);
  }

  // ── Filter ────────────────────────────────────────────────────────────────

  _renderFilter() {
    const root = this._content;
    const c = this._config;
    const content = c.content || [];
    const uiTr = this._uiTr();

    root.appendChild(mk('div', 'section-label', uiTr.content_section));
    const contentGroup = mk('div', 'settings-group');
    contentGroup.appendChild(
      this._mkToggleRow(uiTr.live_activities, content.includes('live_activities'), null, (val) =>
        this._fire({ ...c, content: toggleInArray(content, 'live_activities', val) })
      )
    );
    contentGroup.appendChild(
      this._mkToggleRow(uiTr.notifications, content.includes('notifications'), null, (val) =>
        this._fire({ ...c, content: toggleInArray(content, 'notifications', val) })
      )
    );
    root.appendChild(contentGroup);

    root.appendChild(mk('div', 'section-label', uiTr.filter_tags_section));
    const tagsGroup = mk('div', 'settings-group');
    tagsGroup.appendChild(
      this._mkFormRow(uiTr.filter_include, uiTr.filter_desc, { text: {} }, (c.filter_tags || []).join(', '), (val) =>
        this._fire({ ...c, filter_tags: splitCsv(val) })
      )
    );
    tagsGroup.appendChild(
      this._mkFormRow(
        uiTr.filter_exclude,
        uiTr.filter_exclude_desc,
        { text: {} },
        (c.filter_tags_exclude || []).join(', '),
        (val) => this._fire({ ...c, filter_tags_exclude: splitCsv(val) })
      )
    );
    root.appendChild(tagsGroup);

    root.appendChild(mk('div', 'section-label', uiTr.filter_groups_section));
    const groupsGroup = mk('div', 'settings-group');
    groupsGroup.appendChild(
      this._mkFormRow(uiTr.filter_include, uiTr.filter_desc, { text: {} }, (c.filter_groups || []).join(', '), (val) =>
        this._fire({ ...c, filter_groups: splitCsv(val) })
      )
    );
    groupsGroup.appendChild(
      this._mkFormRow(
        uiTr.filter_exclude,
        uiTr.filter_exclude_desc,
        { text: {} },
        (c.filter_groups_exclude || []).join(', '),
        (val) => this._fire({ ...c, filter_groups_exclude: splitCsv(val) })
      )
    );
    root.appendChild(groupsGroup);
  }

  // ── Appearance ────────────────────────────────────────────────────────────

  _renderAppearance() {
    const root = this._content;
    const c = this._config;
    const uiTr = this._uiTr();

    root.appendChild(mk('div', 'section-label', uiTr.appearance_section));
    const group = mk('div', 'settings-group');
    group.appendChild(
      this._mkFormRow(
        uiTr.layout,
        null,
        { select: { options: [{ value: 'single', label: uiTr.layout_single }, { value: 'split', label: uiTr.layout_split }] } },
        c.layout || 'single',
        (val) => this._fire({ ...c, layout: val })
      )
    );
    group.appendChild(
      this._mkFormRow(
        uiTr.max_items,
        uiTr.max_items_desc,
        { number: { min: 0, max: 100, step: 1, mode: 'box' } },
        c.max_items ?? 0,
        (val) => this._fire({ ...c, max_items: Number(val) || 0 })
      )
    );
    root.appendChild(group);

    root.appendChild(mk('div', 'section-label', uiTr.behaviour_section));
    const behavGroup = mk('div', 'settings-group');
    behavGroup.appendChild(
      this._mkToggleRow(uiTr.hide_when_empty, !!c.hide_when_empty, null, (val) =>
        this._fire({ ...c, hide_when_empty: val })
      )
    );
    behavGroup.appendChild(
      this._mkToggleRow(uiTr.confirm_dismiss, !!c.confirm_dismiss, null, (val) =>
        this._fire({ ...c, confirm_dismiss: val })
      )
    );
    behavGroup.appendChild(
      this._mkToggleRow(uiTr.show_open_action, c.show_open_action !== false, uiTr.show_open_action_desc, (val) =>
        this._fire({ ...c, show_open_action: val })
      )
    );
    root.appendChild(behavGroup);
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────

  _mkToggleRow(label, checked, description, onChange) {
    const row = mk('div', 'srow');
    const tw = mk('div', 'srow-text');
    tw.appendChild(mk('span', 'srow-label', label));
    if (description) tw.appendChild(mk('span', 'srow-desc', description));
    const sw = document.createElement('ha-switch');
    sw.checked = checked;
    sw.addEventListener('change', () => onChange(sw.checked));
    row.append(tw, sw);
    return row;
  }

  // Generic ha-form row for everything except toggles — pass the selector
  // in fully formed (select/text/icon/entity/number) instead of a separate
  // helper per field type, since form.data/schema/computeLabel are
  // identical for each type.
  _mkFormRow(label, description, selector, value, onChange) {
    const row = mk('div', 'srow');
    const tw = mk('div', 'srow-text');
    tw.appendChild(mk('span', 'srow-label', label));
    if (description) tw.appendChild(mk('span', 'srow-desc', description));
    const form = document.createElement('ha-form');
    form.schema = [{ name: 'v', selector }];
    form.data = { v: value };
    form.computeLabel = () => '';
    form.style.cssText = 'flex-shrink:0; width:200px;';
    if (this._hass) form.hass = this._hass;
    form.addEventListener('value-changed', (e) => {
      const val = e.detail.value?.v;
      if (val !== undefined) onChange(val);
    });
    row.append(tw, form);
    return row;
  }
}

if (!customElements.get('notify-dashboard-card-editor')) {
  customElements.define('notify-dashboard-card-editor', NotifyDashboardCardEditor);
}

if (!customElements.get('notify-dashboard-card')) {
  customElements.define('notify-dashboard-card', NotifyDashboardCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'notify-dashboard-card',
    name: 'Notify Dashboard Card',
    description: 'Displays notifications and live activities sent via notify.dashboard.',
    preview: true,
    documentationURL: 'https://github.com/klaptafel/ha-notify-dashboard',
    version: CARD_VERSION,
    getEntitySuggestion: (hass, entityId) => {
      const entry = hass?.entities?.[entityId];
      if (!entry || entry.platform !== 'notify_dashboard') return null;
      return { config: { type: 'custom:notify-dashboard-card', entity: entityId } };
    },
  });
}

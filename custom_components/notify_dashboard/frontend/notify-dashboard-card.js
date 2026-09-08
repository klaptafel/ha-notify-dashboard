// notify-dashboard-card.js
// Lovelace card for the notify_dashboard integration.
// Reads sensor.notify_dashboard (attribute: items[]: notifications and
// live activities together, told apart by data.live_update; active and
// recently-dismissed entries alike, told apart by dismissed_at).
//
// Status: phase 1, including a visual editor (tab skeleton taken 1-to-1 from
// package-tracker-card: tab bar, ha-switch/ha-form rows, config-changed +
// echo protection by comparing against the last-fired config).
// Design decisions are implemented 1-to-1: no chevron/expand, always full
// text, dismiss button as the last feature, tap = navigate (not dismiss),
// tag-replace = full replacement (so no client-side merge needed: the
// backend already delivers complete entries).
//
// Phase 2, partially: progress bar (progress/progress_max, with percentage),
// chronometer/when, and critical_text (live activities only: shares the
// status bar chip slot with chronometer, which wins when both are set,
// same as the companion app). progress_indeterminate is picked up too.

const CARD_VERSION = '1.3.0';

// Minimum time an action button's spinner stays visible after a tap, even
// if the item is already gone from the sensor by then (see the action
// button's click handler and _syncRows).
const MIN_ACTION_SPINNER_MS = 1000;


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
  // YAML-only: deliberately not in the visual editor (see
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
  /* hide_when_empty sets the real hidden property (see _render), not a
     class, so hui-card's own visibility logic can see it too (see
     getCardSize's own comment). This rule just makes our own element
     collapse the same aggressive way the old class-based one did. */
  :host([hidden]) { display: none !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }

  /* A low-opacity color-mix wash over the row background, not solid text/
     background: color is user-supplied and arbitrary, so a full-strength
     fill risks failing WCAG contrast against title/message text, which
     keeps using the theme's own --primary-text-color regardless. Mixing at
     a low percentage keeps it a subtle tint layered on top of the card's
     own background (rather than a flat replacement) so it still reads
     correctly over busy wallpapers and holds up in both light and dark
     themes. Transparent by default so rows without a color still look
     exactly like any other row. */
  /* Padding here deliberately matches HA's own hui-tile-card as closely as a
     variable-height row can: home-assistant/frontend's ha-tile-container
     uses padding: 0 10px + min-height: 56px (a FIXED height centering a
     fixed two-line layout) and a 10px icon-to-content gap. Our rows can
     grow well past two lines (message, chronometer, debug metadata), so a
     fixed min-height would leave tall rows uneven: 10px uniform padding
     keeps the same horizontal rhythm and approximates Tile's effective
     vertical spacing for the common short-row case, while still working for
     long ones. Same reasoning as package-tracker-card.js's .row. */
  .row {
    display: flex; flex-direction: column; padding: 10px; gap: 10px;
    background: transparent;
  }
  /* ha-card has a real 1px border by default (box-sizing: border-box), so
     its content box starts 1px inside the card's outer edge. HA's own
     hui-tile-card compensates for exactly this with the same negative
     margin trick (see ha-tile-container.ts's .container), so its icon/text
     sit flush with the card edge regardless of border width -- without
     this our rows sit a visible ~1px further in than a real Tile row does.
     Child combinator (>) matters here: a .row is always a direct child of
     *some* ha-card (either _rowContainer itself in single layout, or its
     own per-row wrapper in split layout, see _syncRows), so this one rule
     covers both. Horizontal only, not vertical: stacked rows share top/
     bottom borders with each other (see .row + .row below), so a vertical
     negative margin would make them overlap; Tile never has this problem
     since it's always a single row. */
  ha-card > .row, ha-card > .empty {
    margin-left: calc(-1 * var(--ha-card-border-width, 1px));
    margin-right: calc(-1 * var(--ha-card-border-width, 1px));
  }
  .row + .row { border-top: 1px solid var(--divider-color, rgba(0,0,0,.06)); }
  /* debug.dismissed only: a recently-dismissed item shown as read-only
     history, not a live one. */
  .row-ghost { opacity: .5; }

  /* flex-start (not center): icon/dismiss must stay pinned to the top and
     never sink down when the message spans multiple lines. Short content
     (e.g. just a title) gets vertically centered instead via .content
     itself, see below. */
  .row-main { display: flex; align-items: flex-start; gap: 10px; }

  /* 36px + 24px glyph match ha-tile-icon's --tile-icon-size/--mdc-icon-size exactly. */
  .icon-wrap {
    position: relative; width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
  }
  .icon-wrap.clickable { cursor: pointer; -webkit-tap-highlight-color: transparent; overflow: hidden; }
  /* Tap feedback for the clickable icon: same pattern as
     package-tracker-card.js's .icon-wrap.clickable. */
  ha-ripple { position: absolute; inset: 0; }
  ha-icon { --mdc-icon-size: 24px; pointer-events: none; display: flex; }

  /* min-height matching .icon-wrap: for short content (no message) this
     clamps the box to 36px and justify-content centers the title within it,
     matching the icon. For longer content this has no effect: the box just
     grows along with it and everything stacks from the top, same as the
     icon. */
  .content {
    flex: 1; min-width: 0; min-height: 36px;
    display: flex; flex-direction: column; justify-content: center;
  }
  .content.clickable { cursor: pointer; }
  /* font-size/weight/color/line-height match ha-tile-info's --tile-info-
     primary-* tokens; letter-spacing added to match too (line-height
     deliberately stays condensed rather than Tile's 1.6, see
     package-tracker-card.js's .name for why). */
  .title {
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.2);
    letter-spacing: 0.1px;
  }
  /* Holds title + critical-text together as one line: see .critical-text
     below for why this has to be a single flex row instead of two
     independently positioned boxes. align-items: flex-start (not center)
     keeps critical-text pinned to title's *first* line if title wraps. */
  .header-line { display: flex; align-items: flex-start; gap: 8px; }
  .header-line > .title { flex: 1; min-width: 0; }
  /* Deliberately its own third tier (medium weight, secondary-text-color),
     not Tile's plain secondary style, same reasoning as package-tracker-
     card.js's .carrier: this card has more text roles (title/subtitle/
     message) than Tile's two, so subtitle reads as a label/kicker above
     .message rather than being forced onto Tile's secondary-line styling. */
  .subtitle {
    font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--secondary-text-color); line-height: var(--ha-line-height-condensed, 1.2);
    margin-top: 2px;
  }
  /* Whenever title/critical_text are both absent, subtitle becomes
     .content's first child instead: it shouldn't carry the same top
     margin then as when it's following a title line above it. */
  .subtitle:first-child { margin-top: 0; }
  /* .message is the closest analogue to Tile's secondary line: font-size/
     weight/color/letter-spacing match ha-tile-info's --tile-info-secondary-*
     tokens exactly (Tile uses primary-text-color for its secondary line
     too, not a dimmed color). */
  .message {
    font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-normal, 400);
    color: var(--primary-text-color); letter-spacing: 0.4px;
    line-height: var(--ha-line-height-condensed, 1.2); margin-top: 3px; white-space: pre-wrap;
  }
  .chronometer {
    /* The live timer replaces the message line entirely (same as iOS): it
       needs to read as real content, not a small muted caption smaller
       than title/message. Size/weight carry that emphasis, not color:
       --primary-color is a theme accent with no contrast guarantee against
       the card surface (same reason data.color stays a decorative stripe,
       never text/background); --primary-text-color is what HA themes
       actually keep legible here. */
    font-size: var(--ha-font-size-l, 20px); font-weight: var(--ha-font-weight-bold, 700);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.2);
    margin-top: 4px; font-variant-numeric: tabular-nums;
  }
  .timestamp {
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    margin-top: 3px;
  }
  /* debug metadata (tag/group/timeout): same shape as package-tracker-card's
     .carrier row: plain inline icon+text pairs joined by a "·" separator, no
     pill/background/border-radius (confirmed directly against its actual
     source: no chip/pill class exists there at all). */
  .debug-row {
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    line-height: var(--ha-line-height-condensed, 1.2);
    margin-top: 4px; display: flex; align-items: center; gap: 3px; flex-wrap: wrap;
  }
  .debug-row ha-icon { --mdc-icon-size: 13px; flex-shrink: 0; }
  .debug-sep { margin: 0 2px; opacity: .5; }
  /* Lives *inside* .content's .header-line, next to title: not as a
     separate box next to .content in row-main. .content vertically centers
     short content against the 36px icon (min-height + justify-content:
     center, see .content's own comment), so a box outside of it can never
     reliably track where the first line actually ends up: with just one
     short line, that line sits centered partway down a 36px box, not flush
     at the top; a fixed "flush top" position elsewhere then drifts out of
     sync with it, worse still whenever title happens to be missing and the
     first line becomes something else entirely. Being on the same flex row
     as title fixes that structurally: critical-text now moves exactly
     wherever that line moves, whatever it is. margin-left: auto pushes it
     to the end of the row on its own, whether or not a title sibling with
     flex: 1 exists next to it. Capped width + wrapping (not truncation:
     this project never truncates, see the file header) so a long
     critical_text doesn't crowd out the title. */
  .critical-text {
    flex-shrink: 0; margin-left: auto; max-width: 96px; text-align: right;
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.2);
    overflow-wrap: break-word;
  }
  /* A radial "time remaining" indicator wrapped around the dismiss button
     (or, for a persistent timed notification with no button, around the
     plain timer icon) for a timed notification: see _renderRow's
     buildRing(). Sits *behind* the icon (absolute, inset slightly beyond
     the 36px circle) rather than inside it, so it reads as a ring around
     the button rather than competing with the icon for the same space.
     conic-gradient fills clockwise from --ring-percent (0% at created_at,
     100% right when the backend actually dismisses it); the mask punches
     out everything but a thin band at the edge, so it draws as a ring, not
     a solid pie wedge. pointer-events: none so it never steals the click
     from the button underneath. */
  .timeout-ring {
    /* inset: 0, not negative: stays exactly within the same 36px circle
       as .row-dismiss's own hover fill, sitting right at its edge, rather
       than poking out past it. */
    position: absolute; inset: 0; border-radius: 50%; pointer-events: none;
    background: conic-gradient(
      color-mix(in srgb, var(--secondary-text-color) 55%, transparent) var(--ring-percent, 0%),
      transparent 0
    );
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 1.5px), #000 calc(100% - 1.5px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 1.5px), #000 calc(100% - 1.5px));
  }

  /* Reuses .icon-wrap for the exact box (36x36, round): ha-icon-button
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

  /* margin-left = icon-wrap width + row-main gap, so action buttons align under .content, not under the icon. */
  .row-actions { display: flex; flex-direction: column; gap: 8px; margin-left: 46px; }
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

  /* Looks like an empty action feature that fills with notification_icon_color,
     same width as the action buttons, but deliberately shorter (14px vs the
     ~36-40px of ha-control-button). --control-button-border-radius (if
     ha-control-button actually sets it: confirmed against the real HA
     frontend source) takes precedence; the 5px fallback is deliberately
     smaller than the button radius itself and than half the height (7px);
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
  /* progress_bar_direction: 'decreasing' -- a plain block box with an
     explicit width and no margin-right auto-shifts to the right edge of
     its (non-flex) .progress-feature container, so the visible fill stays
     anchored there as its width shrinks, instead of shrinking away from
     the left like the default 'increasing' fill does. */
  .progress-fill.decreasing { margin-left: auto; }
  /* progress_indeterminate: no known percentage, so a sliding segment
     instead of a width-based fill: same track/box as the regular bar. */
  .progress-fill.indeterminate {
    position: absolute; top: 0; height: 100%; width: 40%;
    transition: none;
    animation: notify-dashboard-indeterminate 1.4s ease-in-out infinite;
  }
  @keyframes notify-dashboard-indeterminate {
    0% { left: -40%; }
    100% { left: 100%; }
  }
  /* Same width as the dismiss button (.icon-wrap, 36px), text centered. */
  .progress-label {
    flex-shrink: 0; width: 36px; text-align: center;
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

  /* Without this, a row's straight left edge (where the color accent
     stripe paints) overhangs past ha-card's own rounded corners: visible
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
  .empty-sub { opacity: .7; font-size: var(--ha-font-size-xs, 11px); }
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
// Single combined dict (card + editor strings together): same shape as
// package-tracker-card.js's TRANSLATIONS. English is the base language;
// Dutch is supported as an additional language, never a replacement.
const TRANSLATIONS = {
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
    dismiss: 'Dismiss',
    empty: 'No notifications',
    confirm_dismiss_prompt: 'Remove this notification?',
    just_now: 'Just now',
    minutes_ago: (n) => `${n}m ago`,
    hours_ago: (n) => `${n}h ago`,
    days_ago: (n) => `${n}d ago`,
    entity_not_found: (entity) => `Entity not found: ${entity}`,
  },
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
    dismiss: 'Sluiten',
    empty: 'Geen meldingen',
    confirm_dismiss_prompt: 'Melding verwijderen?',
    just_now: 'Zojuist',
    minutes_ago: (n) => `${n}m geleden`,
    hours_ago: (n) => `${n}u geleden`,
    days_ago: (n) => `${n}d geleden`,
    entity_not_found: (entity) => `Entiteit niet gevonden: ${entity}`,
  },
};

// Shared by the card and editor classes' own _uiTr() methods (each just
// delegates to this), instead of each repeating the same TRANSLATIONS
// lookup + 'en' fallback independently.
function resolveUiTr(hass) {
  return TRANSLATIONS[hass?.language] || TRANSLATIONS['en'];
}

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

// HA's color_rgb selector (commonly used for notification_icon_color/color
// in notify scripts) hands back a plain [r, g, b] array, not a CSS color
// string. Passed straight into a style property or template literal, an
// array coerces via its own toString() into "r,g,b" (no rgb(...) wrapper):
// invalid CSS, silently dropped by the browser, so the icon/wash just
// falls back to its default color instead of erroring visibly. Every other
// source (hex, named colors, var(--x)) is already a valid CSS string and
// passes through unchanged.
function cssColor(value) {
  return Array.isArray(value) ? `rgb(${value[0]}, ${value[1]}, ${value[2]})` : value;
}

function mkIcon(icon, color) {
  const ico = document.createElement('ha-icon');
  ico.setAttribute('icon', icon || 'mdi:bell-outline');
  if (color) ico.style.color = cssColor(color);
  return ico;
}

function matchesFilter(item, filterTags, filterGroups, excludeTags, excludeGroups) {
  const tag = item.data?.tag;
  const group = item.data?.group;
  if (filterTags.length && !filterTags.includes(tag)) return false;
  if (filterGroups.length && !filterGroups.includes(group)) return false;
  // Exclude wins over include: an explicit denylist entry should always
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
// e.g. `type`/`entity`): _normalize merges every default into `_config` for
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
    // keyed by _kind:id: a re-render only rebuilds what actually changed
    // in terms of updated_at/created_at, instead of tearing everything down
    // and rebuilding it. See _syncRows().
    this._rows = new Map();
    this._rowContainer = null;
    this._containerKind = null;
    // key ("_kind:id") -> timestamp until which _syncRows should keep
    // showing that row even after it's dropped out of the sensor's active
    // items: see the action-button click handler and _syncRows below.
    // Deliberately narrow: only ever set for a row the user just tapped an
    // action on, so the rest of the card stays exactly as reactive as
    // fixed (no general "lag behind reality" reintroduced).
    this._pendingRemoval = new Map();
    // A real, documented LovelaceCard interface property (confirmed
    // against home-assistant/frontend's own types.ts and hui-card.ts):
    // without it, hui-card's own _setElementVisibility removes this card
    // from its DOM entirely the moment it goes hidden, which would also
    // stop hass from ever being pushed to it again, leaving it hidden
    // forever with no way to notice items becoming available again and
    // show itself once more.
    this.connectedWhileHidden = true;
    // Lovelace can create this element and assign `.hass` before our own
    // module has finished loading/registering the class (the resource is
    // fetched as an ES module, which loads asynchronously); that first
    // assignment lands as a plain own-property on the not-yet-upgraded
    // element, which then permanently shadows the `set hass()` accessor
    // below once upgrade completes. Every *later* `.hass = ...` from
    // Lovelace becomes a silent plain property write that never reaches
    // the setter again, so the card renders once (whatever hass happened
    // to be at upgrade time) and then never reactively updates: exactly
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
    this._teardownRows();
  }

  connectedCallback() {
    // Lovelace detaches and reattaches a card's DOM node (without
    // destroying the element) when entering/exiting dashboard edit mode:
    // that fires disconnectedCallback above, which empties the row
    // container. The entity's last_updated usually hasn't changed across
    // that move, so set hass's guard below would otherwise never notice
    // anything needs rebuilding, leaving the card an empty shell until a
    // full page refresh recreates it. Force a fresh render on every
    // (re)connect instead of relying on that guard alone.
    if (this._hass && this._config) this._render();
  }

  _teardownRows() {
    // Always also cleans up the DOM node itself (not just the intervals):
    // that makes this a real "remove everything" primitive, usable both by
    // paths that wipe the whole root afterward anyway and by setConfig(),
    // where that doesn't happen and a node left in place would otherwise
    // become a silent duplicate.
    for (const entry of this._rows.values()) {
      entry.intervalIds.forEach((id) => clearInterval(id));
      if (entry.holdTimeout) clearTimeout(entry.holdTimeout);
      entry.el.remove();
    }
    this._rows.clear();
    this._pendingRemoval.clear();
  }

  setConfig(config) {
    if (!config) throw new Error('notify-dashboard-card: config missing');
    this._config = { ...CARD_DEFAULTS, ...config };
    this._entity = config.entity || 'sensor.notify_dashboard';
    // Config can affect how every row renders (icons, buttons,
    // confirm_dismiss, ...): the row cache is then no longer valid, so
    // everything needs to be freshly rebuilt on the next render.
    this._teardownRows();
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const state = hass.states[this._entity];
    const ts = state?.last_updated ?? null;
    const changed = ts !== this._lastUpdated;
    if (changed || !this._built) {
      this._lastUpdated = ts;
      this._render();
    }
  }

  _uiTr() {
    return resolveUiTr(this._hass);
  }

  _dismiss(id) {
    if (this._config.confirm_dismiss && !window.confirm(this._uiTr().confirm_dismiss_prompt)) return;
    this._hass.callService('notify_dashboard', 'dismiss', { id });
  }

  _handleAction(action, item, actionData) {
    if (!action) return;
    // Runs through the notify_dashboard.fire_action service (which calls
    // hass.bus.async_fire server-side) instead of sending the fire_event
    // websocket action from here: that one requires admin rights in HA
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
    // Only the leading (most-significant) unit goes unpadded, like a plain
    // duration, e.g. "9:42", "1:00:05"; every unit *after* it stays zero-
    // padded, since a bare "1:5" for 1 minute 5 seconds would be genuinely
    // ambiguous/hard to read, not just cosmetically redundant.
    if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
    if (m > 0) return `${m}:${pad(s)}`;
    return `${s}`;
  }

  _renderRow(item, intervalIds) {
    const data = item.data || {};
    const icon = data.notification_icon || this._config.default_icon;
    // Normalized once here: every downstream use (icon-wrap background,
    // mkIcon, progress-bar fill) then gets a valid CSS color regardless of
    // whether it came from a color_rgb selector ([r,g,b]) or a plain string.
    const color = cssColor(data.notification_icon_color || this._config.default_icon_color);
    const url = data.url || data.clickAction || null;
    const persistent = !!data.persistent;
    const actions = Array.isArray(data.actions) ? data.actions : [];
    // Only ever true when debug.dismissed asked _collectItems() to include
    // these at all: faded + no close button (dismissing an already-
    // dismissed entry would just fail server-side), so it reads as a
    // read-only history entry, not a live, actionable one.
    const isDismissed = !!item.dismissed_at;

    const row = mk('div', 'row' + (isDismissed ? ' row-ghost' : ''));
    // background_color (live activity only, mirrors the companion app's own
    // lockscreen background) is applied exactly as given, full color/
    // opacity, not run through the `color` wash below -- direct user
    // feedback, 2026-07-28: unlike `color` (a decorative accent over
    // whatever the row would otherwise look like), background_color is the
    // sender's own deliberate, complete background choice for this exact
    // surface (paired with text_color below for contrast), so diluting it
    // through the same low-opacity mix `color` uses would defeat that
    // choice. Only applied when there's no explicit background_color:
    // that's what the low-opacity wash exists for, see the .row CSS comment
    // on why an arbitrary user-supplied `color` stays off of text/large
    // surfaces otherwise.
    if (item._kind === 'live_activities' && data.background_color) {
      row.style.background = cssColor(data.background_color);
    } else if (data.color) {
      row.style.background = `color-mix(in srgb, ${cssColor(data.color)} 12%, transparent)`;
    }
    // text_color, unlike `color`/background_color, is genuinely meant as a
    // foreground text color by the companion app itself ("Tekstkleur op het
    // lockscreen"), not a decorative wash -- applying it literally here
    // doesn't run into the same arbitrary-color-on-text risk the .row CSS
    // comment above warns about for `color`. Live activity only, same as
    // background_color.
    if (item._kind === 'live_activities' && data.text_color) row.style.color = cssColor(data.text_color);
    const main = mk('div', 'row-main');

    const iconWrap = this._buildRowIcon(icon, color, url);
    const content = this._buildRowContent(item, data, isDismissed, intervalIds);
    if (url) {
      // Tap = navigate, doesn't dismiss: mirrors the Companion App's own
      // convention where opening a notification's link is a separate
      // action from dismissing it (the explicit dismiss/X button).
      const onTap = () => this._openUrl(url);
      iconWrap.addEventListener('click', onTap);
      content.addEventListener('click', onTap);
    }
    main.appendChild(iconWrap);
    main.appendChild(content);

    const dismissArea = this._buildRowDismissArea(item, data, isDismissed, persistent, intervalIds);
    if (dismissArea) main.appendChild(dismissArea);

    row.appendChild(main);

    const rowActions = this._buildRowActions(item, data, color, url, actions);
    if (rowActions) row.appendChild(rowActions);

    return row;
  }

  // Left-hand icon (with optional ripple + tap-tinted background when the
  // row is clickable).
  _buildRowIcon(icon, color, url) {
    const iconWrap = mk('div', 'icon-wrap' + (url ? ' clickable' : ''));
    if (url) {
      iconWrap.style.background = `color-mix(in srgb, ${color} 15%, transparent)`;
      // Tap feedback for the clickable icon: same pattern as
      // package-tracker-card.js's .icon-wrap.clickable.
      iconWrap.appendChild(document.createElement('ha-ripple'));
    }
    iconWrap.appendChild(mkIcon(icon, color));
    return iconWrap;
  }

  // Title/critical-text/subtitle/chronometer-or-message/timestamp/debug-row,
  // in that vertical order, inside .content.
  _buildRowContent(item, data, isDismissed, intervalIds) {
    const url = data.url || data.clickAction || null;
    const content = mk('div', 'content' + (url ? ' clickable' : ''));
    // Only render what's actually there: an empty div would otherwise push
    // unwanted whitespace into the row.
    // Nothing is ever shown twice: once message has filled in the title,
    // that same text doesn't also appear as the message.
    const hasChronometer =
      item._kind === 'live_activities' && !!data.chronometer && Number.isFinite(data.when);
    // critical_text is replaced by the timer once chronometer is set, same
    // as the companion app's own status-bar-chip behavior: never both.
    const hasCriticalText = item._kind === 'live_activities' && !hasChronometer && !!data.critical_text;
    const titleText = item.title || item.message || null;
    // The chronometer takes the message's spot entirely (same as iOS):
    // if there's no separate message to replace (message already became
    // titleText above), it just becomes the one supplementary line instead.
    const showMessage = !!item.title && !!item.message && !hasChronometer;

    // critical-text rides along on the same line as title/title-fallback,
    // *inside* .content, rather than as a separate box next to it: .content
    // vertically centers short content against the 36px icon (see its CSS
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
    // re-render. Ticks locally via setInterval: no repeated pushes needed,
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

    // Relative "sent X ago" for regular notifications: live activities
    // have the chronometer/critical_text instead. Coarse (minute)
    // granularity, so a minute-interval tick is enough: no need for
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

    this._appendDebugRow(content, item, data, isDismissed);

    return content;
  }

  // YAML-only debugging aid (see CARD_DEFAULTS): raw tag/group/timeout
  // metadata as a plain inline row of icon+text pairs joined by "·", same
  // shape as package-tracker-card's .carrier row (confirmed directly
  // against its actual source: not a pill/chip, no background at all).
  // Static, not live-ticking: it's showing the configured values as sent,
  // not a countdown. The dismiss-reason chip always shows on a dismissed
  // item (regardless of the tag/group/timeout toggles): that's the
  // whole point of turning debug.dismissed on in the first place.
  _appendDebugRow(content, item, data, isDismissed) {
    const debugCfg = this._config.debug;
    if (!debugCfg || !(debugCfg.tag || debugCfg.group || debugCfg.timeout || isDismissed)) return;
    const tag = data.tag;
    const group = data.group;
    const timeout = Number(data.timeout);
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
    if (!parts.length) return;
    const debugRow = mk('div', 'debug-row');
    parts.forEach((p, i) => {
      if (i > 0) debugRow.appendChild(mk('span', 'debug-sep', '·'));
      debugRow.appendChild(mkIcon(p.icon, 'var(--secondary-text-color)'));
      debugRow.appendChild(document.createTextNode(p.text));
    });
    content.appendChild(debugRow);
  }

  // Radial "time remaining" ring + close button, or (for a persistent
  // notification that still has a timeout) a plain non-interactive timer
  // box; returns null when neither a dismiss button nor a countdown apply.
  _buildRowDismissArea(item, data, isDismissed, persistent, intervalIds) {
    // Countdown to auto-dismiss for a regular, timed notification: live
    // activities expire on their own 8h staleness check instead (see
    // store.py's _cleanup), so data.timeout has no meaning there. Only
    // shown while still active: a debug.dismissed ghost row already has
    // its own dismiss-reason chip, a countdown to nothing would be noise.
    const timeoutSeconds = Number(data.timeout);
    const hasTimeoutCountdown =
      item._kind === 'notifications' &&
      !isDismissed &&
      Number.isFinite(timeoutSeconds) &&
      timeoutSeconds > 0;

    // Radial "time remaining" ring, built once and appended into whichever
    // box below ends up hosting it: a plain background element behind the
    // icon (see .timeout-ring's CSS), not a replacement for it, so the
    // button keeps reading as "close" the whole time instead of swapping
    // between an icon and a timer.
    const buildRing = () => {
      const ring = mk('div', 'timeout-ring');
      // created_at (not updated_at): matches store.py's own
      // created_at + timeout expiry math exactly, so the ring reads 100%
      // at the *real* expiry instant, not some padded stand-in for it.
      // With CLEANUP_INTERVAL down to 1s, the worst-case "ring's full but
      // the row's still here" window is small enough not to be worth
      // trading away that exactness for.
      const target = item.created_at + timeoutSeconds;
      const update = () => {
        const remaining = Math.max(0, target - Date.now() / 1000);
        const pct = timeoutSeconds > 0 ? (1 - remaining / timeoutSeconds) * 100 : 100;
        ring.style.setProperty('--ring-percent', `${Math.min(100, Math.max(0, pct))}%`);
      };
      update();
      intervalIds.push(setInterval(update, 1000));
      return ring;
    };

    // persistent only blocks manual dismiss for notifications: a live
    // activity stays dismissable via the close button regardless (matches
    // store.py's is_persistent(), which bakes in the same exception).
    // Already-dismissed (debug.dismissed view) never gets one either: the
    // backend would just reject dismissing something already inactive.
    if (!isDismissed && (!persistent || item._kind === 'live_activities')) {
      // Same primitive (icon-wrap) as the main icon instead of ha-icon-button,
      // so the box (and thus the hover background) is exactly 38x38, matching
      // the main icon, and at the same height since both are plain flex
      // children of row-main.
      const closeBtn = mk('div', 'icon-wrap row-dismiss');
      closeBtn.setAttribute('role', 'button');
      closeBtn.tabIndex = 0;
      closeBtn.setAttribute('aria-label', this._uiTr().dismiss);
      // Ring appended first so it paints *behind* the icon in normal flow
      // (no z-index needed): both share the same 36px circle, the ring
      // just extends slightly past its edge (see .timeout-ring's inset).
      if (hasTimeoutCountdown) closeBtn.appendChild(buildRing());
      closeBtn.appendChild(mkIcon('mdi:close', 'var(--secondary-text-color)'));
      const onDismiss = () => this._dismiss(item.id);
      closeBtn.addEventListener('click', onDismiss);
      closeBtn.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onDismiss();
        }
      });
      return closeBtn;
    } else if (hasTimeoutCountdown) {
      // persistent notification with a timeout: no manual close button (see
      // above), but store.py's own auto-expiry doesn't check `persistent`
      // either: it'll still get dismissed on its own, so the ring
      // shouldn't just silently disappear here. Same 36px box, not
      // clickable/focusable this time: there's nothing to dismiss early.
      // A plain timer icon fills the ring's center, since there's no
      // dismiss-X appropriate for a non-interactive box.
      const box = mk('div', 'icon-wrap');
      box.appendChild(buildRing());
      box.appendChild(mkIcon('mdi:timer-outline', 'var(--secondary-text-color)'));
      return box;
    }
    return null;
  }

  // Progress bar (live activities) + action buttons + the optional Open
  // button, stacked vertically below the row's main line; returns null when
  // none of those apply.
  _buildRowActions(item, data, color, url, actions) {
    // The Open button is optional (show_open_action): tapping the icon/
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

    // A concrete percentage wins if we have one: it's strictly more useful
    // than a spinner. Android's native API lets progress_indeterminate
    // override stale progress values left behind from an earlier
    // setProgress() call, but that quirk doesn't apply here: our store does
    // a full replace on every update, so if both are present they arrived
    // together in the same payload, deliberately. Indeterminate is only the
    // fallback for when there's no usable percentage to show.
    const hasIndeterminateProgress =
      item._kind === 'live_activities' && data.progress_indeterminate === true && !hasProgress;

    if (!hasIndeterminateProgress && !hasProgress && !showOpenBtn && !actions.length) return null;

    // Always stacked vertically: labels are often too long for a
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
      const fill = mk('div', 'progress-fill' + (data.progress_bar_direction === 'decreasing' ? ' decreasing' : ''));
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
        // state: prevents double-tapping regardless of whether that
        // element handles disabled correctly itself.
        if (clicked) return;
        clicked = true;
        btn.textContent = '';
        btn.appendChild(mk('div', 'action-spinner'));
        // Hold this specific row on screen for a bit even if it drops out
        // of the sensor's active items before that: e.g. an automation
        // reacting to this same action, dismissing it faster than this
        // card's own 600ms fallback below. Purely a visible "your tap
        // registered" confirmation, not a wait for anything real, so a
        // short, fixed hold (not tied to whatever finishes it) is exactly
        // the point: see _syncRows for the other half of this.
        this._pendingRemoval.set(`${item._kind}:${item.id}`, Date.now() + MIN_ACTION_SPINNER_MS);
        this._handleAction(a.action, item, a.action_data);
        // Small delay to confirm the tap was processed, then dismiss:
        // doesn't apply to the Open button (which only navigates).
        setTimeout(() => {
          this._hass
            .callService('notify_dashboard', 'dismiss', { id: item.id })
            .catch(() => {}); // e.g. already gone, or persistent: nothing to do then
        }, 600);
      });
      rowActions.appendChild(btn);
    });
    if (showOpenBtn) {
      // After the actions (not before): Open is the generic fallback
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
    return rowActions;
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
    // chronological sorts the combined list again anyway: a per-kind sort
    // here would then just be pure repeated work.
    const sortPerKind = groupOrder !== 'chronological';

    // `items` holds both kinds together, told apart by data.live_update
    // (same field the companion app itself uses, no separate kind label
    // on the sensor) and both active + recently-dismissed entries
    // (dismissed_at set): normally the card only shows active ones, unless
    // the YAML-only debug.dismissed flag asks to see recently-dismissed
    // ones too (see _renderRow for how those are visually distinguished).
    // One pass over the raw list: skip dismissed, filter, and bucket by
    // kind all at once, instead of filtering the same list twice (once
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
  // gets a new chronometer interval) if updated_at/created_at has changed:
  // an unchanged row elsewhere in the card is left completely alone, even
  // when another row just updated. Without this, every chronometer would
  // tick again from zero whenever anything at all changes in the card.
  _syncRows(items, layout) {
    const seen = new Set();
    let prevEl = null;

    for (const item of items) {
      const key = `${item._kind}:${item.id}`;
      seen.add(key);
      // Still genuinely active: any hold from an earlier action-button tap
      // is moot now.
      this._pendingRemoval.delete(key);
      const updatedAt = item.updated_at || item.created_at || 0;
      let entry = this._rows.get(key);

      if (!entry || entry.updatedAt !== updatedAt) {
        if (entry) {
          entry.intervalIds.forEach((id) => clearInterval(id));
          if (entry.holdTimeout) clearTimeout(entry.holdTimeout);
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

    const now = Date.now();
    for (const [key, entry] of this._rows) {
      if (!seen.has(key)) {
        const holdUntil = this._pendingRemoval.get(key);
        if (holdUntil && now < holdUntil) {
          // Just tapped, gone from the sensor already, but still inside its
          // minimum-visible window: leave the row (spinner and all)
          // exactly as it was, and come back once the hold expires to
          // finish removing it (nothing else guarantees another render
          // will happen by then).
          if (!entry.holdTimeout) {
            entry.holdTimeout = setTimeout(() => this._render(), holdUntil - now);
          }
          continue;
        }
        this._pendingRemoval.delete(key);
        entry.intervalIds.forEach((id) => clearInterval(id));
        if (entry.holdTimeout) clearTimeout(entry.holdTimeout);
        entry.el.remove();
        this._rows.delete(key);
      }
    }
  }

  _render() {
    if (!this._hass || !this._config) return;
    const items = this._collectItems();
    this._built = true;

    // A row can be mid-hold (see _pendingRemoval / _syncRows' click-driven
    // "keep this one on screen a bit longer" logic) even though `items` no
    // longer includes it. The empty/hide_when_empty shortcuts below call
    // _teardownRows() unconditionally, which would nuke a held row before
    // its hold ever gets to matter: skip straight to the normal
    // container+_syncRows path instead whenever a hold is still pending.
    // Prune already-expired holds *before* checking, not after: the hold's
    // own setTimeout calls this same method once holdUntil passes, and
    // without this the still-stale _pendingRemoval entry (only ever
    // cleared *inside* _syncRows, further down) would make `holding` true
    // for that entire call too: one render late to ever actually reach
    // the empty-state branch below, leaving a bare empty container behind
    // instead of the proper "no notifications" placeholder.
    const now = Date.now();
    for (const [key, holdUntil] of this._pendingRemoval) {
      if (now >= holdUntil) this._pendingRemoval.delete(key);
    }
    const holding = this._pendingRemoval.size > 0;

    if (!items.length && !holding && this._config.hide_when_empty) {
      this.hidden = true;
      this._teardownRows();
      this._root.innerHTML = '';
      this._containerKind = null;
      return;
    }
    this.hidden = false;

    if (!items.length && !holding) {
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
        // Surface a misconfigured/missing entity instead of showing the
        // same generic empty state whether there are simply no
        // notifications right now or the entity doesn't exist at all.
        if (!this._hass.states[this._entity]) {
          empty.appendChild(mk('div', 'empty-sub', this._uiTr().entity_not_found(this._entity)));
        }
        card.appendChild(empty);
        this._root.appendChild(card);
        this._containerKind = 'empty';
      }
      return;
    }

    const layout = this._config.layout === 'split' ? 'split' : 'single';
    if (this._containerKind !== layout) {
      // Layout switched (or first render): replace the container itself too;
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

  // The real <hui-card> HA wraps this element in already collapses itself
  // to nothing whenever this.hidden is true (confirmed against
  // hui-card.ts's own real source, _updateVisibility/_setElementVisibility:
  // it checks this._element.hidden on every hass push and sets its own
  // style.display accordingly), so setting the actual DOM property above
  // is enough on its own. A first attempt instead reached into hui-card
  // directly and set its style.display by hand, the same shape
  // https://github.com/Clooos/Bubble-Card/pull/2535 uses for their own
  // popup host, but that fought a losing battle against hui-card's own
  // _updateVisibility, which re-derives its own style.display from
  // this.hidden on every single hass push and would silently undo a
  // manual override moments later, since it had no idea we ever hidden
  // ourselves. connectedWhileHidden (see the constructor) is what keeps
  // hass pushes coming at all once hidden, otherwise hui-card removes
  // this element outright and it could never notice items becoming
  // available again.
  getCardSize() {
    if (this._config?.hide_when_empty && this.hidden) return 0;
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
    // Only `entity`: spreading CARD_DEFAULTS in here would persist every
    // default setting into the freshly-added card's YAML verbatim,
    // defeating the whole point of stripDefaults() (which only ever runs
    // on edits made *after* this point, not on this initial config).
    // _normalize() already merges CARD_DEFAULTS in at runtime, so nothing
    // here needs them written down explicitly.
    return { entity: match ? match[0] : 'sensor.notify_dashboard' };
  }

  static getConfigElement() {
    return document.createElement('notify-dashboard-card-editor');
  }
}

// Visual editor: tab skeleton (tab bar, _fire/_ownFire echo protection,
// ha-switch/ha-form rows) taken 1-to-1 from package-tracker-card.
// debug (tag/group/timeout metadata, see CARD_DEFAULTS) is deliberately not
// included here either: it's a YAML-only debugging aid, not a real
// feature, so an editor field for it would invite permanently-on debug
// metadata nobody meant to keep around.
class NotifyDashboardCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = null;
    this._hass = null;
    this._built = false;
    this._lastFiredConfig = null;
    this._tab = 'content';
    // Same defensive fix as NotifyDashboardCard's constructor: see its
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
    // Lovelace: without this guard that would trigger a pointless full
    // re-render (and could reset the active tab). A single-use boolean
    // flag isn't reliable for this (confirmed elsewhere in these card
    // projects: it can miss a second echo, or clear before a delayed one
    // arrives, letting either fall through to a destructive re-render mid-
    // edit) -- comparing directly against what we last actually dispatched
    // catches every echo regardless of timing or count.
    if (this._lastFiredConfig && deepEqual(config, this._lastFiredConfig)) return;
    this._config = this._normalize(config);
    this._renderTab();
  }

  _normalize(config) {
    return { ...CARD_DEFAULTS, ...config };
  }

  _uiTr() {
    return resolveUiTr(this._hass);
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
    const stripped = stripDefaults(config);
    this._lastFiredConfig = stripped;
    this.dispatchEvent(
      new CustomEvent('config-changed', { detail: { config: stripped }, bubbles: true, composed: true })
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

    this._renderFilterPair(root, uiTr.filter_tags_section, 'filter_tags', 'filter_tags_exclude');
    this._renderFilterPair(root, uiTr.filter_groups_section, 'filter_groups', 'filter_groups_exclude');
  }

  // Shared by the tags/groups sections in _renderFilter above: both are an
  // identical include/exclude text-field pair, differing only in which
  // config keys they read/write.
  _renderFilterPair(root, sectionLabel, includeKey, excludeKey) {
    const c = this._config;
    const uiTr = this._uiTr();
    root.appendChild(mk('div', 'section-label', sectionLabel));
    const group = mk('div', 'settings-group');
    group.appendChild(
      this._mkFormRow(uiTr.filter_include, uiTr.filter_desc, { text: {} }, (c[includeKey] || []).join(', '), (val) =>
        this._fire({ ...c, [includeKey]: splitCsv(val) })
      )
    );
    group.appendChild(
      this._mkFormRow(
        uiTr.filter_exclude,
        uiTr.filter_exclude_desc,
        { text: {} },
        (c[excludeKey] || []).join(', '),
        (val) => this._fire({ ...c, [excludeKey]: splitCsv(val) })
      )
    );
    root.appendChild(group);
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

  // Generic ha-form row for everything except toggles: pass the selector
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

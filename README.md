[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Notify Dashboard

A `notify.dashboard` notify service plus a matching Lovelace card, so notifications you already send to your phone also show up on your dashboard — tags, actions, live activities, and live-progress the same way the Companion App's `live_update` does.

---

## Features

- **`notify.dashboard`** — drop it into an existing `notify` group next to your phones, same payload, no changes needed.
- **Tag-aware** — `tag` replaces, `clear_notification` clears, exactly like the Companion App.
- **Live activities** — anything sent with `live_update: true` is tracked separately from regular notifications, auto-expires after 8h of inactivity.
- **Self-contained frontend** — the card is served by the integration itself, no manual Lovelace resource needed.
- **Optional dismiss mirroring** — clearing a notification on the dashboard can forward `clear_notification` to your phone too.

---

## Installation

This integration isn't in the HACS default store yet — add it as a custom repository.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=klaptafel&repository=ha-notify-dashboard&category=integration)

1. In HACS, add `klaptafel/ha-notify-dashboard` as a custom repository (category: Integration).
2. Install "Notify Dashboard" and restart Home Assistant.

Or manually: copy `custom_components/notify_dashboard` into your own `custom_components` folder and restart.

---

## Configuration

**1. Add the integration via Settings → Devices & Services → Add Integration → Notify Dashboard.**
This sets up the store, services, and frontend, and lets you optionally pick one or more `notify.*` targets that should also receive a `clear_notification` when a notification is dismissed on the dashboard — including automatically, when it times out or gets trimmed by the retention cap, not just an explicit dismiss (editable later via "Configure"). Both notify *entities* (e.g. `notify.mobile_app_pixel`) and legacy notify *services*/groups (e.g. a YAML `notify: - platform: group`, which has no entity at all) show up in the picker.

**2. Add the notify platform in YAML — this step can't be done through the UI**, since legacy notify platforms don't support config entries:

```yaml
notify:
  - platform: notify_dashboard
    name: dashboard
```

---

## Adding the card

No manual Lovelace resource needed — the integration registers the card's JS itself as soon as it's set up.

Edit a dashboard → **Add card** → search for "Notify Dashboard" to use the visual editor (Source / Filter / Appearance tabs), or pick **Manual** and paste YAML directly. The editor only shows the settings most people need — the visual editor writes out just what you actually change, defaults are never persisted into the saved YAML.

**Minimal:**

```yaml
type: custom:notify-dashboard-card
```

**Full** (including a few YAML-only options not in the visual editor — see below):

```yaml
type: custom:notify-dashboard-card
entity: sensor.notify_dashboard
layout: single              # or: split
content:
  - live_activities
  - notifications
filter_tags: []           # only show these tags (empty = all)
filter_groups: []         # only show these groups (empty = all)
filter_tags_exclude: []   # hide these tags, wins over filter_tags
filter_groups_exclude: [] # hide these groups, wins over filter_groups
max_items: 0                # 0 = no limit
hide_when_empty: false
confirm_dismiss: false     # ask for confirmation before dismissing
show_open_action: true     # show an explicit "Open" button for items with a url

# YAML-only — not in the visual editor, since the defaults are already the
# intended behavior and don't need to be a user-facing decision:
group_order: live_first     # or: notifications_first / chronological
default_icon: mdi:bell-outline
default_icon_color: var(--primary-color)
```

---

## Usage

Send exactly like you would to a phone:

```yaml
action: notify.dashboard
data:
  title: Dishwasher
  message: "Running (73%)"
  data:
    tag: dishwasher_activity
    live_update: true
    notification_icon: mdi:dishwasher
    notification_icon_color: "#26C6DA"
    progress: 73
    progress_max: 100
```

`progress`/`progress_max` only render as a bar (with a live percentage) on live activities (`live_update: true`) and only when both are set — same condition as the companion app.

`chronometer`/`when` render as a live-ticking countdown/count-up under the title, updating every second entirely client-side (no repeated pushes needed):

```yaml
action: notify.dashboard
data:
  title: Pizza timer
  data:
    tag: pizza_timer
    live_update: true
    chronometer: true
    when: 900              # 15 minutes
    when_relative: true     # when = seconds from now, not a Unix timestamp
```

`critical_text` (live activities only) is short supplementary text shown below the title — it shares its slot with `chronometer`, which takes over that slot when both are set (same as the companion app):

```yaml
action: notify.dashboard
data:
  title: Front door
  data:
    tag: front_door
    live_update: true
    critical_text: Package waiting
```

Regular (non-live) notifications also show a relative "sent X ago" timestamp automatically — no config needed.

`actions` render as pill buttons (`action`, `title`, optional `action_data`, optional `destructive` for red text). Tapping one fires `mobile_app_notification_action`, shows a small spinner, and dismisses the notification ~600ms later — the `url`-driven Open button is unaffected by this and never auto-dismisses.

```yaml
action: notify.dashboard
data:
  title: Update available
  data:
    actions:
      - action: INSTALL
        title: Install
      - action: DISMISS_FOREVER
        title: Ignore
        destructive: true
```

`subtitle` renders as a secondary line between the title and message (iOS-only on the companion app; works on any notification here, not just live activities):

```yaml
action: notify.dashboard
data:
  title: Package delivered
  data:
    subtitle: Front door camera
    subject: Front door camera   # Android's equivalent field, same rendering here
```

`color` renders as a left accent stripe on the row, not as text or a background wash — an arbitrary user-supplied color used for text/background risks failing WCAG contrast, so it stays decorative-only. Handy for telling notifications apart at a glance in a list:

```yaml
action: notify.dashboard
data:
  title: Security alert
  data:
    color: "#e53935"
```

`progress_indeterminate: true` on a live activity shows a sliding animated bar instead of a percentage fill, for tasks with no known completion time — it's only a fallback for when there's no usable percentage; a concrete `progress`/`progress_max` in the same payload always wins. Paste this into **Developer Tools → Actions** (YAML mode) to see it live:

```yaml
action: notify.dashboard
data:
  title: Backing up
  message: Please wait…
  data:
    tag: backup_job
    live_update: true
    notification_icon: mdi:backup-restore
    notification_icon_color: "#7E57C2"
    progress_indeterminate: true
```

Clear it afterward with:

```yaml
action: notify.dashboard
data:
  message: clear_notification
  data:
    tag: backup_job
```

---

## Services

| Service | Fields | Does |
|---|---|---|
| `notify_dashboard.dismiss` | `id` (required) | Removes a notification or live activity. For notifications `id` is a uuid; for live activities `id` equals the `tag`. Raises an error for an unknown id or a `persistent: true` notification. |
| `notify_dashboard.dismiss_all` | — | Removes all notifications (except `persistent`-marked ones). Leaves live activities untouched. |
| `notify_dashboard.fire_action` | `action` (required), `tag`, `action_data` | Fires a `mobile_app_notification_action` event, same shape as the companion app. Used internally by the card for action taps — a regular service call rather than the frontend's `fire_event` websocket command, since that one requires an admin user and would silently do nothing for anyone else (e.g. a kiosk tablet on a restricted account). |

---

## Removal

1. Remove the `notify: - platform: notify_dashboard` block from `configuration.yaml`.
2. Remove the integration via Settings → Devices & Services → Notify Dashboard → delete.
3. Remove `custom_components/notify_dashboard` (or the HACS repository).
4. Restart Home Assistant.

Stored data lives in `.storage/notify_dashboard.notifications` — delete that file manually if you also want to wipe saved notifications/live activities.

---

## How data updates

The dashboard sensor (`sensor.notify_dashboard`) is push-based, not polled — it updates immediately whenever a notification/live activity is added, dismissed, or expires (a 15-second background cleanup timer removes anything past its timeout/max-age, no manual "refresh" needed). The card itself only re-renders the rows that actually changed, so an unrelated update elsewhere in the list won't reset an in-progress chronometer/countdown.

---

## Debugging

YAML-only — not in the visual editor, since it's a debugging aid rather than a real feature. Shows the raw `tag`/`group`/`timeout` of each notification as small chips, so you can check what actually arrived without opening dev tools:

```yaml
type: custom:notify-dashboard-card
debug:
  tag: true
  group: true
  timeout: true
```

Only shows a chip for a field that's actually present on that item — a notification without a `group` just won't get a group chip, for example.

---

## Known limitations

- **Dismiss mirroring only works for Companion App (`mobile_app`) targets.** `mirror_dismiss_to` forwards the same `clear_notification` command the phone app understands — other `notify.*` integrations (Telegram, Pushover, ntfy, Slack, ...) have no equivalent concept of "delete a previously delivered message by tag", so picking one there just delivers a literal, confusing text message instead. A repair issue is raised if a configured target entity no longer exists at all, but this content mismatch can't be detected the same way.
- **No device registry entry.** The sensor is set up via `discovery.async_load_platform` (needed to keep the YAML-only `notify.dashboard` path working without a config entry), which never attaches a `ConfigEntry` to the entity's platform — and HA only creates a device for an entity when one is attached. The entity still works normally; it just won't show up grouped under a "device" in Settings → Devices & Services.
- **Single instance only.** Only one config entry is allowed; `mirror_dismiss_to` is a single shared list, not per-dashboard.

---

## Troubleshooting

- **"Found both the YAML key ... and a config entry" warning** — you have both a `notify_dashboard:` YAML block and the config entry's "Configure" settings populated. The config entry always wins; remove the YAML block (keep just the `notify:` platform block, which is unrelated and still required) to clear the warning.
- **`notify.dashboard` doesn't exist even though the integration is installed** — the config entry only sets up the store/services/frontend/sensor; the actual `notify.dashboard` service still needs the separate YAML platform block from the Configuration section above. This is a limitation of the legacy notify platform itself, not something the UI can replace.
- **Card added but shows nothing** — check the `entity:` in the card config actually points at your `sensor.notify_dashboard` (or its renamed entity id); the card reads its data entirely from that one entity's attributes.

---

## Roadmap

- `image`, `icon_url`, `alert_once`
- `notify-dashboard-badge` for a count badge in a Sections dashboard header

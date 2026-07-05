[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Notify Dashboard

> [!NOTE]
> Early scaffold. The design is fully worked out (see [`notify-dashboard-ontwerp.md`](./notify-dashboard-ontwerp.md)), but this hasn't been tested against a running Home Assistant instance yet.

A `notify.dashboard` notify service plus a matching Lovelace card, so notifications you already send to your phone also show up on your dashboard — tags, actions, and (eventually) live-progress the same way the Companion App's `live_update` does.

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
This sets up the store, services, and frontend, and lets you optionally pick which `notify.*` targets should also receive a `clear_notification` when you dismiss something on the dashboard (editable later via "Configure").

**2. Add the notify platform in YAML — this step can't be done through the UI**, since legacy notify platforms don't support config entries:

```yaml
notify:
  - platform: notify_dashboard
    name: dashboard
```

---

## Adding the card

No manual Lovelace resource needed — the integration registers the card's JS itself as soon as it's set up.

Edit a dashboard → **Add card** → **Manual**, then paste:

**Minimal:**

```yaml
type: custom:notify-dashboard-card
```

**Full:**

```yaml
type: custom:notify-dashboard-card
entity: sensor.notify_dashboard
layout: single              # or: split
content:
  - live_activities
  - notifications
group_order: live_first     # or: notifications_first / chronological
filter_tags: []
filter_groups: []
max_items: 0                # 0 = no limit
hide_when_empty: false
default_icon: mdi:bell-outline
default_icon_color: var(--primary-color)
hold_action:
  action: none
double_tap_action:
  action: none
confirm_dismiss: false     # ask for confirmation before dismissing
show_open_action: true     # show an explicit "Open" button for items with a url
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

## Roadmap

- Visual card editor (YAML-only for now)
- `image`, `icon_url`, `alert_once`, `subtitle`/`subject`, `color`, `critical_text`, `progress_indeterminate`
- `notify-dashboard-badge` for a count badge in a Sections dashboard header

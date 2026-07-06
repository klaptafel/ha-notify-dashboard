[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Notify Dashboard
> [!NOTE]
> This integration is vibe coded

A `notify.dashboard` notify service plus a matching Lovelace card, so notifications you already send to your phone also show up on your dashboard — tags, actions, live activities, and live-progress the same way the Companion App's `live_update` does.

![Logo](/custom_components/notify_dashboard/brand/logo.png)

---

## Features

- **Drop-in `notify.dashboard` service** — same payload you already send to your phone, no changes needed; add it next to your other notify targets.
- **Tag-aware** — `tag` replaces, `clear_notification` clears, exactly like the Companion App.
- **Live activities** — anything sent with `live_update: true` is tracked separately, with a live progress bar/chronometer, and auto-expires after 8h of inactivity.
- **Actions and an Open button** — action buttons fire the same `mobile_app_notification_action` event the Companion App uses; a `url` gets an explicit Open button.
- **Optional dismiss mirroring** — clearing a notification on the dashboard can forward `clear_notification` to your phone (or a legacy notify group) too.
- **Self-contained frontend** — the card is served by the integration itself, no manual Lovelace resource needed.

---

## Installation

This integration isn't in the HACS default store yet — add it as a custom repository.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=klaptafel&repository=ha-notify-dashboard&category=integration)

1. In HACS, add `klaptafel/ha-notify-dashboard` as a custom repository (category: Integration).
2. Install "Notify Dashboard" and restart Home Assistant.

---

## Configuration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=notify_dashboard)

1. **Settings → Devices & Services → Add Integration → Notify Dashboard.** Sets up the store, services, and frontend, and optionally lets you pick `notify.*` targets that should also get `clear_notification` when a notification is dismissed here.
2. **Add the notify platform in YAML** — legacy notify platforms can't be set up through the UI:
   ```yaml
   notify:
     - platform: notify_dashboard
       name: dashboard
   ```

---

## Adding the card

No manual Lovelace resource needed. **Add card** → search "Notify Dashboard" for the visual editor, or paste YAML directly:

```yaml
type: custom:notify-dashboard-card
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
    progress: 73
    progress_max: 100
```

### Supported `data` fields

A payload with `live_update: true` is tracked as a live activity instead of a regular notification — several fields below only apply to that mode.

| Field | Applies to | Does |
|---|---|---|
| `tag` | Any | Sending the same `tag` again replaces it in place; `clear_notification` + `tag` removes it. |
| `group` | Any | Free-form label for grouping/filtering (`filter_groups`) — not currently used for visual clustering, items aren't sorted by it. |
| `persistent: true` | Any | Excluded from `dismiss_all`; can't be dismissed from the card or the `dismiss` service. |
| `timeout` | Notification only | Seconds until auto-removal. Without it, a notification is only capped by the 30-day/100-item retention limit — live activities never use `timeout`; they expire 8h after their last update instead. |
| `notification_icon` / `notification_icon_color` | Any | Icon override and its background wash color. |
| `color` | Any | Accent background wash for the whole row. |
| `url` / `clickAction` | Any | Makes the row tappable and shows an explicit Open button. |
| `actions` | Any | Array of `{action, title, action_data, destructive}` → pill buttons that fire `mobile_app_notification_action` on tap. |
| `subtitle` / `subject` | Any | Secondary line under the title. |
| `critical_text` | Live activity | Short text under the title (shares its slot with `chronometer` — the timer wins if both are set). |
| `chronometer` / `when` / `when_relative` | Live activity | Live-ticking countdown/count-up under the title, updated client-side every second. |
| `progress` / `progress_max` | Live activity | Progress bar with a live percentage — both fields required. |
| `progress_indeterminate: true` | Live activity | Sliding indeterminate bar, used when there's no concrete `progress` to show. |

Clear a notification or live activity the same way the app does:

```yaml
action: notify.dashboard
data:
  message: clear_notification
  data:
    tag: dishwasher_activity
```

---

## Services

| Service | Fields | Does |
|---|---|---|
| `notify_dashboard.dismiss` | `id` (required) | Removes a notification or live activity (uuid, or `tag` for a live activity). |
| `notify_dashboard.dismiss_all` | — | Removes all non-`persistent` notifications. |
| `notify_dashboard.fire_action` | `action`, `tag`, `action_data` | Fires a `mobile_app_notification_action` event — used internally for action-button taps. |

---

## Known limitations

- Dismiss mirroring only understands the Companion App's `clear_notification` — other `notify.*` integrations have no equivalent, so picking one there just sends a literal text message.
- No device registry entry (the legacy notify platform never attaches a `ConfigEntry`).
- Single instance only; `mirror_dismiss_to` is one shared list, not per-dashboard.

---

## Removal

1. Remove the `notify: - platform: notify_dashboard` block from `configuration.yaml`.
2. Remove the integration via Settings → Devices & Services → Notify Dashboard → delete.
3. Remove `custom_components/notify_dashboard` (or the HACS repository).

Stored data lives in `.storage/notify_dashboard.notifications` — delete that file manually if you also want to wipe saved notifications/live activities.

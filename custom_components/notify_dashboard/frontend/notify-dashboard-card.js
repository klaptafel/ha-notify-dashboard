// notify-dashboard-card.js
// Lovelace-card voor de notify_dashboard integratie.
// Leest sensor.notify_dashboard (attributen: notifications[], live_activities[]).
//
// Status: fase-1 scaffold — YAML-config, nog geen visuele editor.
// Ontwerpbeslissingen zijn 1-op-1 verwerkt: geen chevron/uitklap, altijd
// volledige tekst, sluiten-knop als laatste feature, tap=navigeren (niet
// dismissen), tag-replace = volledige vervanging (dus geen client-side merge
// nodig — de backend levert al complete entries).

const CARD_VERSION = '0.1.7';

const CARD_DEFAULTS = {
  layout: 'single', // of: split
  content: ['live_activities', 'notifications'],
  group_order: 'live_first', // of: notifications_first / chronological
  filter_tags: [],
  filter_groups: [],
  max_items: 0, // 0 = geen limiet
  hide_when_empty: false,
  default_icon: 'mdi:bell-outline',
  default_icon_color: 'var(--primary-color)',
  hold_action: { action: 'none' },
  double_tap_action: { action: 'none' },
};

const CARD_CSS = `
  :host {
    display: block;
    font-family: var(--ha-font-family-body, inherit);
    -webkit-font-smoothing: var(--ha-font-smoothing, auto);
  }
  :host(.hidden) { display: none !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }

  .row { display: flex; flex-direction: column; padding: 12px 16px; gap: 8px; position: relative; }
  .row + .row { border-top: 1px solid var(--divider-color, rgba(0,0,0,.06)); }

  .row-dismiss {
    position: absolute; top: 12px; right: 16px;
    --mdc-icon-button-size: 38px; --mdc-icon-size: 20px;
    color: var(--secondary-text-color);
  }

  .row-main { display: flex; align-items: flex-start; gap: 14px; }

  .icon-wrap {
    width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
  }
  .icon-wrap.clickable { cursor: pointer; -webkit-tap-highlight-color: transparent; }
  ha-icon { --mdc-icon-size: 20px; pointer-events: none; display: flex; }

  .content { flex: 1; min-width: 0; padding-right: 44px; }
  .content.clickable { cursor: pointer; }
  .title {
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.3);
  }
  .message {
    font-size: var(--ha-font-size-s, 12px); color: var(--primary-text-color);
    line-height: var(--ha-line-height-condensed, 1.3); margin-top: 3px; white-space: pre-wrap;
  }

  .row-actions { display: flex; align-items: center; gap: 8px; margin-left: 52px; }
  .row-actions ha-control-button-group { flex: 1; min-width: 0; }

  .split-wrapper { display: flex; flex-direction: column; gap: 8px; }
  .split-wrapper ha-card .row { border-top: none; }

  .empty {
    padding: 28px 16px; text-align: center; color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 12px);
    display: flex; flex-direction: column; align-items: center; gap: 8px;
  }
`;

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

function matchesFilter(item, filterTags, filterGroups) {
  const tag = item.tag ?? item.data?.tag;
  const group = item.group ?? item.data?.group;
  if (filterTags.length && !filterTags.includes(tag)) return false;
  if (filterGroups.length && !filterGroups.includes(group)) return false;
  return true;
}

class NotifyDashboardCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `<style>${CARD_CSS}</style><div id="root"></div>`;
    this._root = this.shadowRoot.getElementById('root');
    this._lastUpdated = null;
    this._built = false;
  }

  setConfig(config) {
    if (!config) throw new Error('notify-dashboard-card: config ontbreekt');
    this._config = { ...CARD_DEFAULTS, ...config };
    this._entity = config.entity || 'sensor.notify_dashboard';
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const state = hass.states[this._entity];
    const ts = state?.last_updated ?? null;
    if (ts !== this._lastUpdated || !this._built) {
      this._lastUpdated = ts;
      this._render();
    }
  }

  _dismiss(id) {
    this._hass.callService('notify_dashboard', 'dismiss', { id });
  }

  _handleAction(action, item, actionData) {
    if (!action) return;
    // Zelfde event-vorm als de companion-app (action, action_data, tag),
    // zodat bestaande wait_for_trigger-automations ongewijzigd blijven
    // werken. Vereist admin-rechten op de websocket-verbinding; als dat
    // ontbreekt loggen we het en doen niets destructiefs.
    const event_data = { action, tag: item.tag };
    if (actionData !== undefined) event_data.action_data = actionData;
    this._hass.connection
      .sendMessagePromise({
        type: 'fire_event',
        event_type: 'mobile_app_notification_action',
        event_data,
      })
      .catch((err) => console.warn('notify-dashboard-card: kon actie-event niet versturen', err));
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

  _renderRow(item) {
    const data = item.data || {};
    const icon = data.notification_icon || this._config.default_icon;
    const color = data.notification_icon_color || this._config.default_icon_color;
    const url = data.url || data.clickAction || null;
    const persistent = !!data.persistent;
    const actions = Array.isArray(data.actions) ? data.actions : [];

    const row = mk('div', 'row');
    const main = mk('div', 'row-main');

    const iconWrap = mk('div', 'icon-wrap' + (url ? ' clickable' : ''));
    if (url) {
      iconWrap.style.background = `color-mix(in srgb, ${color} 15%, transparent)`;
    }
    iconWrap.appendChild(mkIcon(icon, color));

    const content = mk('div', 'content' + (url ? ' clickable' : ''));
    content.appendChild(mk('div', 'title', item.title || ''));
    content.appendChild(mk('div', 'message', item.message || ''));

    if (url) {
      // Tap = navigeren, dismixt niet (zie ontwerpdocument 3.7).
      const onTap = () => this._openUrl(url);
      iconWrap.addEventListener('click', onTap);
      content.addEventListener('click', onTap);
    }

    main.appendChild(iconWrap);
    main.appendChild(content);
    row.appendChild(main);

    if (url || actions.length) {
      const rowActions = mk('div', 'row-actions');
      const controlGroup = document.createElement('ha-control-button-group');
      if (url) {
        const openBtn = document.createElement('ha-control-button');
        openBtn.textContent = 'Open';
        openBtn.addEventListener('click', () => this._openUrl(url));
        controlGroup.appendChild(openBtn);
      }
      actions.forEach((a) => {
        const btn = document.createElement('ha-control-button');
        btn.textContent = a.title || a.action;
        btn.addEventListener('click', () => this._handleAction(a.action, item, a.action_data));
        controlGroup.appendChild(btn);
      });
      rowActions.appendChild(controlGroup);
      row.appendChild(rowActions);
    }

    if (!persistent) {
      const closeBtn = document.createElement('ha-icon-button');
      closeBtn.className = 'row-dismiss';
      closeBtn.label = 'Sluiten';
      closeBtn.path = 'M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z';
      closeBtn.addEventListener('click', () => this._dismiss(item.id));
      row.appendChild(closeBtn);
    }

    return row;
  }

  _collectItems() {
    const state = this._hass.states[this._entity];
    const attrs = state?.attributes || {};
    const { filter_tags: filterTags, filter_groups: filterGroups, content, group_order: groupOrder } = this._config;

    const notifications = (attrs.notifications || [])
      .filter((n) => matchesFilter(n, filterTags, filterGroups))
      .map((n) => ({ ...n, _kind: 'notifications' }));
    const liveActivities = (attrs.live_activities || [])
      .filter((n) => matchesFilter(n, filterTags, filterGroups))
      .map((n) => ({ ...n, _kind: 'live_activities' }));

    const byNewest = (a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0);

    let items;
    if (groupOrder === 'chronological') {
      items = [...(content.includes('live_activities') ? liveActivities : []),
                ...(content.includes('notifications') ? notifications : [])].sort(byNewest);
    } else {
      const live = content.includes('live_activities') ? [...liveActivities].sort(byNewest) : [];
      const notif = content.includes('notifications') ? [...notifications].sort(byNewest) : [];
      items = groupOrder === 'notifications_first' ? [...notif, ...live] : [...live, ...notif];
    }

    if (this._config.max_items > 0) items = items.slice(0, this._config.max_items);
    return items;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const items = this._collectItems();
    this._built = true;

    if (!items.length && this._config.hide_when_empty) {
      this.classList.add('hidden');
      this._root.innerHTML = '';
      return;
    }
    this.classList.remove('hidden');
    this._root.innerHTML = '';

    if (!items.length) {
      const card = document.createElement('ha-card');
      const empty = mk('div', 'empty');
      const ico = mkIcon(this._config.default_icon);
      ico.style.setProperty('--mdc-icon-size', '32px');
      ico.style.opacity = '.3';
      empty.appendChild(ico);
      empty.appendChild(mk('div', null, 'Geen meldingen'));
      card.appendChild(empty);
      this._root.appendChild(card);
      return;
    }

    if (this._config.layout === 'split') {
      const wrapper = mk('div', 'split-wrapper');
      for (const item of items) {
        const card = document.createElement('ha-card');
        card.appendChild(this._renderRow(item));
        wrapper.appendChild(card);
      }
      this._root.appendChild(wrapper);
    } else {
      const card = document.createElement('ha-card');
      for (const item of items) {
        card.appendChild(this._renderRow(item));
      }
      this._root.appendChild(card);
    }
  }

  getCardSize() {
    if (this._config?.hide_when_empty && this.classList.contains('hidden')) return 0;
    return 3;
  }

  static getStubConfig() {
    return { ...CARD_DEFAULTS, entity: 'sensor.notify_dashboard' };
  }
}

if (!customElements.get('notify-dashboard-card')) {
  customElements.define('notify-dashboard-card', NotifyDashboardCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'notify-dashboard-card',
    name: 'Notify Dashboard Card',
    description: 'Toont meldingen en live activities verstuurd via notify.dashboard.',
    preview: true,
    version: CARD_VERSION,
  });
}

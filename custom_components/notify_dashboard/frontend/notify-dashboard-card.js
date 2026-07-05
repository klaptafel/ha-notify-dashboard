// notify-dashboard-card.js
// Lovelace-card voor de notify_dashboard integratie.
// Leest sensor.notify_dashboard (attributen: notifications[], live_activities[]).
//
// Status: fase-1 scaffold — YAML-config, nog geen visuele editor.
// Ontwerpbeslissingen zijn 1-op-1 verwerkt: geen chevron/uitklap, altijd
// volledige tekst, sluiten-knop als laatste feature, tap=navigeren (niet
// dismissen), tag-replace = volledige vervanging (dus geen client-side merge
// nodig — de backend levert al complete entries).
//
// Fase 2, deels: progress-bar (progress/progress_max, met percentage) en
// chronometer/when voor live activities. progress_indeterminate en
// critical_text zijn bewust nog niet opgepakt (onbevestigd veld resp. een
// lock-screen-conceptje dat niet 1-op-1 op een dashboard-kaart past).

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
  confirm_dismiss: false,
  show_open_action: true,
};

const CARD_CSS = `
  :host {
    display: block;
    font-family: var(--ha-font-family-body, inherit);
    -webkit-font-smoothing: var(--ha-font-smoothing, auto);
  }
  :host(.hidden) { display: none !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }

  .row { display: flex; flex-direction: column; padding: 12px 16px; gap: 14px; }
  .row + .row { border-top: 1px solid var(--divider-color, rgba(0,0,0,.06)); }

  /* flex-start (niet center): icon/dismiss moeten bovenin blijven hangen en
     nooit meezakken als de message meerdere regels beslaat. Korte content
     (bv. enkel een titel) wordt in plaats daarvan via .content zelf verticaal
     gecentreerd, zie hieronder. */
  .row-main { display: flex; align-items: flex-start; gap: 14px; }

  .icon-wrap {
    width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
  }
  .icon-wrap.clickable { cursor: pointer; -webkit-tap-highlight-color: transparent; }
  ha-icon { --mdc-icon-size: 20px; pointer-events: none; display: flex; }

  /* min-height gelijk aan .icon-wrap: bij korte content (geen message) klemt
     dit de doos op 38px en centreert justify-content de titel daarin, gelijk
     met het icoon. Bij langere content heeft dit geen effect — de doos groeit
     gewoon mee en alles stapelt vanaf boven, net als het icoon. */
  .content {
    flex: 1; min-width: 0; min-height: 38px;
    display: flex; flex-direction: column; justify-content: center;
  }
  .content.clickable { cursor: pointer; }
  .title {
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color); line-height: var(--ha-line-height-condensed, 1.3);
  }
  .message {
    font-size: var(--ha-font-size-s, 12px); color: var(--primary-text-color);
    line-height: var(--ha-line-height-condensed, 1.3); margin-top: 3px; white-space: pre-wrap;
  }
  .chronometer {
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    margin-top: 3px; font-variant-numeric: tabular-nums;
  }

  /* Hergebruikt .icon-wrap voor de exacte doos (38x38, rond) — ha-icon-button
     forceert intern een vaste ~48x48 touch-target die --mdc-icon-button-size
     niet overschrijft, dus nooit exact gelijk aan het main-icoon te krijgen. */
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
  /* currentColor volgt de knop-tekstkleur automatisch mee, ook bij destructive
     (dan rood via --control-button-icon-color: var(--error-color)). */
  .action-spinner {
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid color-mix(in srgb, currentColor 25%, transparent);
    border-top-color: currentColor;
    animation: notify-dashboard-spin 0.8s linear infinite;
  }
  @keyframes notify-dashboard-spin { to { transform: rotate(360deg); } }

  /* Ziet eruit als een lege actie-feature die vult met notification_icon_color
     — zelfde breedte als de actie-knoppen, maar bewust lager (14px vs de
     ~36-40px van ha-control-button). --control-button-border-radius (indien
     ha-control-button die daadwerkelijk zet) is leidend; de 5px-fallback is
     bewust kleiner dan de knop-radius zelf en dan de halve hoogte (7px) —
     anders klemt de browser 'm sowieso vast op een volledige pil/capsule i.p.v.
     een lichte afronding. Nog niet geverifieerd of
     --control-button-border-radius de juiste variabele-naam is. */
  .progress-wrap { display: flex; align-items: center; gap: 8px; }
  .progress-feature {
    width: 100%; height: 14px; border-radius: var(--control-button-border-radius, 5px);
    background: color-mix(in srgb, var(--secondary-text-color) 12%, transparent);
    overflow: hidden;
  }
  .progress-wrap .progress-feature { flex: 1; width: auto; }
  .progress-fill { height: 100%; border-radius: inherit; transition: width 300ms ease-in-out; }
  /* Zelfde breedte als de sluiten-knop (.icon-wrap, 38px), tekst gecentreerd. */
  .progress-label {
    flex-shrink: 0; width: 38px; text-align: center;
    font-size: var(--ha-font-size-xs, 11px); color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

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
    // Rijen (en hun chronometer-intervals) blijven tussen renders in leven,
    // gekeyed op _kind:id — een re-render herbouwt alleen wat qua
    // updated_at/created_at echt gewijzigd is, i.p.v. alles af te breken en
    // opnieuw op te bouwen. Zie _syncRows().
    this._rows = new Map();
    this._rowContainer = null;
    this._containerKind = null;
  }

  disconnectedCallback() {
    // Zonder opruimen blijven gecachete rijen (en hun chronometer-intervals)
    // eeuwig leven nadat de kaart uit de DOM is, bv. bij wisselen van view.
    this._teardownRows();
  }

  _teardownRows() {
    // Ruimt altijd ook de DOM-node zelf op (niet alleen de intervals) — zo is
    // dit een echte "alles weg"-primitief, bruikbaar door zowel paden die de
    // hele root daarna toch wipen als door setConfig(), waar dat niet gebeurt
    // en een niet-verwijderde node anders als stille duplicaat blijft staan.
    for (const entry of this._rows.values()) {
      entry.intervalIds.forEach((id) => clearInterval(id));
      entry.el.remove();
    }
    this._rows.clear();
  }

  setConfig(config) {
    if (!config) throw new Error('notify-dashboard-card: config ontbreekt');
    this._config = { ...CARD_DEFAULTS, ...config };
    this._entity = config.entity || 'sensor.notify_dashboard';
    // Config kan van invloed zijn op hoe elke rij rendert (iconen, knoppen,
    // confirm_dismiss, ...) — de rij-cache is dan niet meer geldig, dus
    // alles moet bij de eerstvolgende render vers opgebouwd worden.
    this._teardownRows();
    if (this._hass) this._render();
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
    if (this._config.confirm_dismiss && !window.confirm('Melding verwijderen?')) return;
    this._hass.callService('notify_dashboard', 'dismiss', { id });
  }

  _handleAction(action, item, actionData) {
    if (!action) return;
    // Loopt via de notify_dashboard.fire_action-service (die hass.bus.async_fire
    // server-side aanroept) i.p.v. hier zelf de fire_event websocket-actie te
    // sturen — die vereist admin-rechten in HA core, dus zou voor niet-admin
    // dashboardgebruikers (bv. een kiosk-tablet) stil niets doen. Service-
    // aanroepen kennen die beperking niet. Zelfde event-vorm als de companion-
    // app (action, action_data, tag), zodat bestaande wait_for_trigger-
    // automations ongewijzigd blijven werken.
    const payload = { action };
    if (item.tag) payload.tag = item.tag;
    if (actionData != null) payload.action_data = actionData;
    this._hass
      .callService('notify_dashboard', 'fire_action', payload)
      .catch((err) => console.warn('notify-dashboard-card: kon actie niet versturen', err));
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

    const row = mk('div', 'row');
    const main = mk('div', 'row-main');

    const iconWrap = mk('div', 'icon-wrap' + (url ? ' clickable' : ''));
    if (url) {
      iconWrap.style.background = `color-mix(in srgb, ${color} 15%, transparent)`;
    }
    iconWrap.appendChild(mkIcon(icon, color));

    const content = mk('div', 'content' + (url ? ' clickable' : ''));
    // Alleen renderen wat er is — een lege div duwt anders ongewenste
    // witruimte in de rij. Cascaderende fallback zodat een ontbrekend veld
    // niet gewoon leeg blijft terwijl er nog relevante content is:
    // - geen title, wel message -> message krijgt de title-opmaak.
    // - geen message (en title kwam niet al van message) -> de chronometer
    //   krijgt de message-opmaak i.p.v. zijn eigen kleinere stijl.
    // Niets wordt dubbel getoond: zodra message de title heeft ingevuld,
    // verschijnt diezelfde tekst niet nogmaals als message.
    const hasChronometer =
      item._kind === 'live_activities' && !!data.chronometer && Number.isFinite(data.when);
    const titleText = item.title || item.message || null;
    const showMessage = !!item.title && !!item.message;
    const chronoAsMessage = !item.message && hasChronometer;

    if (titleText) content.appendChild(mk('div', 'title', titleText));
    if (showMessage) content.appendChild(mk('div', 'message', item.message));

    // when_relative telt when op bij updated_at (het moment dat wij 'm
    // binnenkregen) i.p.v. bij de rendertijd, zodat het target niet
    // verschuift bij elke re-render. Tikt lokaal door via setInterval — geen
    // herhaalde pushes nodig, net als bij de companion-app.
    if (hasChronometer) {
      const target = data.when_relative ? (item.updated_at || 0) + data.when : data.when;
      const chrono = mk('div', chronoAsMessage ? 'message' : 'chronometer');
      const update = () => {
        chrono.textContent = this._formatChrono(target - Date.now() / 1000);
      };
      update();
      intervalIds.push(setInterval(update, 1000));
      content.appendChild(chrono);
    }

    if (url) {
      // Tap = navigeren, dismixt niet (zie ontwerpdocument 3.7).
      const onTap = () => this._openUrl(url);
      iconWrap.addEventListener('click', onTap);
      content.addEventListener('click', onTap);
    }

    main.appendChild(iconWrap);
    main.appendChild(content);

    if (!persistent) {
      // Zelfde primitief (icon-wrap) als het main-icoon i.p.v. ha-icon-button,
      // zodat de doos (dus ook de hover-achtergrond) exact 38x38 is — gelijk
      // aan het main-icoon, en op dezelfde hoogte omdat beide gewone flex-
      // children van row-main zijn.
      const closeBtn = mk('div', 'icon-wrap row-dismiss');
      closeBtn.setAttribute('role', 'button');
      closeBtn.tabIndex = 0;
      closeBtn.setAttribute('aria-label', 'Sluiten');
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

    // De Open-knop is optioneel (show_open_action) — tap op icoon/content
    // navigeert sowieso al, deze knop is puur een expliciet, zichtbaar
    // alternatief daarvoor.
    const showOpenBtn = !!url && this._config.show_open_action;

    // Progress-bar: alleen voor live activities, en alleen als beide velden
    // aanwezig zijn (zelfde voorwaarde als de companion-app: progress_max
    // moet gezet zijn wil er een balk verschijnen). progress: -1 (klaar-
    // signaal) verwijdert de live activity al server-side, komt hier dus
    // nooit binnen.
    const hasProgress =
      item._kind === 'live_activities' &&
      Number.isFinite(data.progress) &&
      Number.isFinite(data.progress_max) &&
      data.progress_max > 0;

    if (hasProgress || showOpenBtn || actions.length) {
      // Altijd verticaal gestapeld — labels zijn vaak te lang voor een
      // horizontale rij van gelijk-verdeelde knoppen.
      const rowActions = mk('div', 'row-actions');
      if (hasProgress) {
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
        // destructive (companion-app-veld): rode tekst i.p.v. de standaardkleur.
        if (a.destructive) {
          btn.style.setProperty('--control-button-icon-color', 'var(--error-color)');
        }
        let clicked = false;
        btn.addEventListener('click', () => {
          // Eigen vlag i.p.v. op ha-control-button's disabled-status leunen —
          // voorkomt dubbel-tappen ongeacht of dat element zelf disabled
          // correct afhandelt.
          if (clicked) return;
          clicked = true;
          btn.textContent = '';
          btn.appendChild(mk('div', 'action-spinner'));
          this._handleAction(a.action, item, a.action_data);
          // Kleine delay als bevestiging dat de tap is verwerkt, daarna
          // dismissen — geldt niet voor de Open-knop (die navigeert alleen).
          setTimeout(() => {
            this._hass
              .callService('notify_dashboard', 'dismiss', { id: item.id })
              .catch(() => {}); // bv. al weg, of persistent — dan hoeft dit niets te doen
          }, 600);
        });
        rowActions.appendChild(btn);
      });
      if (showOpenBtn) {
        // Na de acties (niet ervoor) — Open is de generieke fallback-tap,
        // geen hoofdactie. Minder prominent zodra er ook echte acties zijn.
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
    const { filter_tags: filterTags, filter_groups: filterGroups, content, group_order: groupOrder } = this._config;

    const byNewest = (a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0);
    // chronological sorteert de gecombineerde lijst toch nog een keer — een
    // per-kind sort hier zou dan pure herhaalde arbeid zijn.
    const sortPerKind = groupOrder !== 'chronological';

    const collect = (key, kind) => {
      if (!content.includes(key)) return [];
      const arr = (attrs[key] || [])
        .filter((n) => matchesFilter(n, filterTags, filterGroups))
        .map((n) => ({ ...n, _kind: kind }));
      return sortPerKind ? arr.sort(byNewest) : arr;
    };

    const notif = collect('notifications', 'notifications');
    const live = collect('live_activities', 'live_activities');

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

  // Zet (of hergebruikt) de rijen van `items` als kinderen van
  // this._rowContainer, in de juiste volgorde. Een rij wordt alleen echt
  // opnieuw gebouwd (en dus: krijgt alleen dan een nieuwe chronometer-
  // interval) als updated_at/created_at is veranderd — een niet-gewijzigde
  // rij elders in de kaart blijft volledig met rust, ook als een andere rij
  // net update. Zonder dit tikt elke chronometer opnieuw vanaf nul zodra
  // wát dan ook in de kaart verandert.
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
          entry.el.remove(); // anders blijft de oude node als stale duplicaat staan
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
        empty.appendChild(mk('div', null, 'Geen meldingen'));
        card.appendChild(empty);
        this._root.appendChild(card);
        this._containerKind = 'empty';
      }
      return;
    }

    const layout = this._config.layout === 'split' ? 'split' : 'single';
    if (this._containerKind !== layout) {
      // Layout gewisseld (of eerste render) — container zelf ook vervangen;
      // _syncRows() ziet dan geen bestaande rijen meer en bouwt alles vers op.
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

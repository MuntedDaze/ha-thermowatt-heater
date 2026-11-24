/*
 * Thermowatt cards (one resource): <thermowatt-power-flow-card>, <thermowatt-panel-card>,
 * <thermowatt-lights-card> and <thermowatt-device-energy-card>.
 * Power-flow card: a lightweight, dependency-free, SEMS+-inspired three-node view.
 *   solar (top), house (bottom left), grid (bottom right)
 * Reads three MEASURED power entities (W or kW). Nothing is estimated or guessed: an unavailable,
 * unknown or stale reading is shown as "--" and its lines stay grey and stationary.
 *
 * Install: copy to /config/www/thermowatt/thermowatt-power-flow-card.js and add the Dashboard
 * resource /local/thermowatt/thermowatt-power-flow-card.js (type: JavaScript module).
 * Card config: solar_entity, house_entity, grid_entity, grid_export_positive (default true),
 *              idle_threshold_w (default 5), stale_seconds (default 900), name (optional).
 */

export const GREEN = "#43a047";
export const ORANGE = "#fb8c00";
export const GREY = "#9e9e9e";
const SPEED_KW_SECONDS = 3; // chevron travel time = 3 / kW seconds ...
const MIN_SECONDS = 0.5; // ... never faster than 0.5 s
const MAX_SECONDS = 8; // ... never slower than 8 s

/** Reading in watts, or null if missing/unavailable/unknown/non-numeric/stale. */
export function readWatts(stateObj, staleSeconds = 900, nowMs = Date.now()) {
  if (!stateObj || stateObj.state === undefined || stateObj.state === null) return null;
  const text = String(stateObj.state).trim().toLowerCase();
  if (text === "" || text === "unavailable" || text === "unknown" || text === "none") return null;
  const value = Number(text);
  if (!Number.isFinite(value)) return null;
  const stamp = stateObj.last_reported || stateObj.last_updated || stateObj.last_changed;
  if (stamp && staleSeconds > 0) {
    const age = (nowMs - new Date(stamp).getTime()) / 1000;
    if (Number.isFinite(age) && age > staleSeconds) return null;
  }
  const unit = String((stateObj.attributes || {}).unit_of_measurement || "").trim().toLowerCase();
  if (unit !== "w" && unit !== "kw") return null; // missing or unexpected unit: never assume
  return unit === "kw" ? value * 1000 : value;
}

export function formatKw(watts) {
  return watts === null || watts === undefined ? "--" : `${(Math.abs(watts) / 1000).toFixed(3)} kW`;
}

/** Seconds for one chevron to cross a line: speed is proportional to power within the clamp. */
export function travelSeconds(kw) {
  if (!(kw > 0)) return null;
  return Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, SPEED_KW_SECONDS / kw));
}

/**
 * Pure flow model. solar/house/grid are watts or null; grid is signed.
 * A line is drawn only when every reading it depends on was measured AND the three readings
 * agree with each other (house = solar - export + import, within a tolerance); otherwise it stays
 * grey and stationary. Nothing is derived from a missing measurement.
 */
export function computeFlows({ solarW, houseW, gridW, exportPositive = true, idleW = 5 }) {
  const solar = solarW === null ? null : Math.max(0, solarW);
  const house = houseW === null ? null : Math.max(0, houseW);
  let exportW = null;
  let importW = null;
  let gridState = "unavailable";
  if (gridW !== null) {
    const toGrid = exportPositive ? gridW : -gridW;
    exportW = toGrid > idleW ? toGrid : 0;
    importW = toGrid < -idleW ? -toGrid : 0;
    gridState = exportW > 0 ? "export" : importW > 0 ? "import" : "idle";
  }
  const known = solar !== null && house !== null && gridState !== "unavailable";
  let inconsistent = false;
  if (known) {
    const supply = solar + importW;
    const demand = house + exportW;
    inconsistent = Math.abs(supply - demand) > Math.max(300, 0.15 * Math.max(supply, demand));
  }
  const lines = { solarToHouse: 0, solarToGrid: 0, gridToHouse: 0 };
  const gridKnown = gridState !== "unavailable";
  if (!inconsistent) {
    // Each path needs only the readings it is made of.
    if (gridKnown && house !== null) lines.gridToHouse = Math.min(importW, house);
    if (gridKnown && solar !== null) lines.solarToGrid = Math.min(exportW, solar);
    if (known) {
      lines.solarToHouse = Math.max(
        0,
        Math.min(solar - lines.solarToGrid, house - lines.gridToHouse)
      );
    }
    for (const key of Object.keys(lines)) if (lines[key] <= idleW) lines[key] = 0;
  }
  const label = {
    import: "Grid Import",
    export: "Grid Export",
    idle: "Grid Idle",
    unavailable: "Grid Unavailable",
  }[gridState];
  return {
    solarW: solar,
    houseW: house,
    gridW: gridState === "unavailable" ? null : exportW || importW || 0,
    gridState,
    gridLabel: label,
    inconsistent,
    lines,
  };
}

// Line geometry in a 400 x 262 viewBox; every path is drawn in its flow direction.
const GEOMETRY = {
  solarToHouse: { p: [[178, 86], [140, 120], [100, 135], [82, 156]] },
  solarToGrid: { p: [[222, 86], [260, 120], [300, 135], [318, 156]] },
  gridToHouse: { p: [[296, 190], [104, 190]] },
};
const COLOURS = { solarToHouse: GREEN, solarToGrid: GREEN, gridToHouse: ORANGE };

function pathD(key) {
  const p = GEOMETRY[key].p;
  return p.length === 2
    ? `M${p[0][0]} ${p[0][1]} L${p[1][0]} ${p[1][1]}`
    : `M${p[0][0]} ${p[0][1]} C${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]} ${p[3][0]} ${p[3][1]}`;
}

/** Point and heading (degrees) at t along a line, for static arrows. */
export function pointAt(key, t) {
  const p = GEOMETRY[key].p;
  if (p.length === 2) {
    const dx = p[1][0] - p[0][0];
    const dy = p[1][1] - p[0][1];
    return { x: p[0][0] + dx * t, y: p[0][1] + dy * t, angle: (Math.atan2(dy, dx) * 180) / Math.PI };
  }
  const u = 1 - t;
  const at = (i) =>
    u * u * u * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i] + t * t * t * p[3][i];
  const d = (i) =>
    3 * u * u * (p[1][i] - p[0][i]) + 6 * u * t * (p[2][i] - p[1][i]) + 3 * t * t * (p[3][i] - p[2][i]);
  return { x: at(0), y: at(1), angle: (Math.atan2(d(1), d(0)) * 180) / Math.PI };
}

function chevrons(key, kw, colour, reduceMotion) {
  const shape = `<path d="M-5 -5 L3 0 L-5 5" fill="none" stroke="${colour}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`;
  if (reduceMotion) {
    // Static arrows still show the direction of flow.
    return [0.3, 0.5, 0.7]
      .map((t) => {
        const { x, y, angle } = pointAt(key, t);
        return `<g class="static-arrow" transform="translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${angle.toFixed(1)})">${shape}</g>`;
      })
      .join("");
  }
  const dur = travelSeconds(kw);
  const items = [];
  for (let i = 0; i < 3; i += 1) {
    items.push(
      `<g>${shape}<animateMotion dur="${dur.toFixed(2)}s" begin="-${((dur * i) / 3).toFixed(2)}s" repeatCount="indefinite" rotate="auto"><mpath href="#tw-${key}"/></animateMotion></g>`
    );
  }
  return items.join("");
}

export function renderSvg(model, reduceMotion = false) {
  const lines = Object.keys(GEOMETRY)
    .map((key) => {
      const watts = model.lines[key];
      const active = watts > 0;
      const colour = active ? COLOURS[key] : GREY;
      const moving = active ? chevrons(key, watts / 1000, colour, reduceMotion) : "";
      return `<path id="tw-${key}" d="${pathD(key)}" fill="none" stroke="${colour}" stroke-width="${active ? 3 : 2}" stroke-linecap="round" opacity="${active ? 0.9 : 0.55}"/>${moving}`;
    })
    .join("");
  const gridColour = { import: ORANGE, export: GREEN }[model.gridState] || GREY;
  const solarColour = model.solarW > 5 ? GREEN : GREY;
  const node = (cx, cy, colour, icon, title, value) =>
    `<circle cx="${cx}" cy="${cy}" r="40" fill="var(--card-background-color,#fff)" stroke="${colour}" stroke-width="3"/>` +
    `<g transform="translate(${cx} ${cy - 10})" fill="none" stroke="${colour}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${icon}</g>` +
    `<text x="${cx}" y="${cy + 18}" text-anchor="middle" font-size="15.5" font-weight="600" fill="var(--primary-text-color,#212121)">${value}</text>` +
    `<text x="${cx}" y="${cy + 58}" text-anchor="middle" font-size="15" fill="var(--secondary-text-color,#727272)">${title}</text>`;
  const sun = '<circle r="7"/><path d="M0 -14V-11M0 11V14M-14 0H-11M11 0H14M-10 -10l2 2M8 8l2 2M-10 10l2 -2M8 -8l2 -2"/>';
  const house = '<path d="M-13 3L0 -9L13 3M-9 0V12H9V0"/>';
  const grid = '<path d="M0 -13V13M-9 -6H9M-6 1H6M-11 13L0 -13L11 13"/>';
  return (
    `<svg viewBox="0 0 400 262" xmlns="http://www.w3.org/2000/svg" width="100%" role="img" aria-label="${ariaLabel(model)}">` +
    lines +
    node(200, 46, solarColour, sun, "Solar", formatKw(model.solarW)) +
    node(66, 190, model.lines.solarToHouse || model.lines.gridToHouse ? (model.lines.gridToHouse ? ORANGE : GREEN) : GREY, house, "House", formatKw(model.houseW)) +
    node(334, 190, gridColour, grid, model.gridLabel, formatKw(model.gridW)) +
    (model.inconsistent
      ? '<text x="200" y="258" text-anchor="middle" font-size="13.5" fill="var(--secondary-text-color,#727272)">Readings not in sync</text>'
      : "") +
    "</svg>"
  );
}

function ariaLabel(model) {
  const sync = model.inconsistent ? ", readings not in sync" : "";
  return `Solar ${formatKw(model.solarW)}, house ${formatKw(model.houseW)}, ${model.gridLabel} ${formatKw(model.gridW)}${sync}`;
}

const Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

/* Today's energy for the strip under the flow diagram: solar from the inverter's own daily counter, import and
 * export from the recorder's long-term statistics (the same pipeline as Device Energy). Read only, cached,
 * refreshed every few minutes; an unreadable figure is a dash, never zero, and an incomplete one is a lower bound. */
const TODAY_CACHE = new Map();
const TODAY_REFRESH_MS = 3 * 60e3;

function liveKwh(state) {
  if (!state) return null;
  const value = Number(state.state);
  const unit = String((state.attributes || {}).unit_of_measurement || "").toLowerCase();
  return Number.isFinite(value) && value >= 0 && Object.hasOwn(ENERGY_UNITS, unit) ? value * ENERGY_UNITS[unit] : null;
}

export async function loadTodayEnergy(hass, today, timeZone = DEFAULT_TIMEZONE, now = Date.now()) {
  const result = { solar: liveKwh((hass.states || {})[today.solar]), import: null, export: null };
  const dayStart = startOfLocalDay(now, timeZone);
  const hourEnd = Math.floor(now / HOUR_MS) * HOUR_MS;
  const ids = ["import", "export"].map((k) => today[k]).filter(Boolean);
  if (!ids.length) return result;
  const metadata = await withTimeout(hass.callWS({ type: "recorder/get_statistics_metadata", statistic_ids: ids }));
  const factors = {};
  for (const m of Array.isArray(metadata) ? metadata : []) {
    const unit = String(m.statistics_unit_of_measurement || "").toLowerCase();
    if (Object.hasOwn(ENERGY_UNITS, unit) && m.has_sum !== false) factors[m.statistic_id] = ENERGY_UNITS[unit];
  }
  const usable = ids.filter((id) => factors[id] !== undefined);
  if (!usable.length) return result;
  const ask = (from, to, period) =>
    withTimeout(
      hass.callWS({
        type: "recorder/statistics_during_period",
        start_time: new Date(from).toISOString(),
        end_time: new Date(to).toISOString(),
        statistic_ids: usable,
        period,
        types: ["change"],
      })
    );
  const hourly = hourEnd > dayStart ? await ask(dayStart, hourEnd, "hour") : {};
  const fine = await ask(Math.max(dayStart, hourEnd - 3 * HOUR_MS), now + HOUR_MS, "5minute");
  for (const key of ["import", "export"]) {
    const id = today[key];
    if (!id || factors[id] === undefined) continue;
    const source = { kind: "energy", factor: factors[id] };
    const buckets = mergeBuckets(toBuckets((hourly || {})[id], source), toBuckets((fine || {})[id], source));
    const total = sumKwh(buckets, dayStart, now + HOUR_MS);
    const cov = coverage(buckets, dayStart, now + HOUR_MS, now);
    result[key] = total ? { kwh: total.kwh, incomplete: cov.leading > 0 || cov.missing > 0 } : null;
  }
  return result;
}

/** Solar used directly today: the package figure, only while the package says its daily meters are complete. */
export function directUseKwh(hass, today) {
  if (!today || !today.used) return null;
  const states = hass.states || {};
  if (today.status && (!states[today.status] || states[today.status].state !== "ready")) return null;
  return liveKwh(states[today.used]);
}

class ThermowattPowerFlowCard extends Base {
  setConfig(config) {
    for (const key of ["solar_entity", "house_entity", "grid_entity"]) {
      if (!config || !config[key]) throw new Error(`Missing ${key}`);
    }
    this._config = {
      grid_export_positive: true,
      idle_threshold_w: 5,
      stale_seconds: 900,
      title: "Energy now",
      ...config,
    };
    this._key = null;
    this._today = null;
  }

  connectedCallback() {
    this._refreshToday();
  }

  set hass(hass) {
    this._hass = hass;
    const c = this._config;
    if (!c) return;
    this._refreshToday();
    const stale = c.stale_seconds;
    const model = computeFlows({
      solarW: readWatts(hass.states[c.solar_entity], stale),
      houseW: readWatts(hass.states[c.house_entity], stale),
      gridW: readWatts(hass.states[c.grid_entity], stale),
      exportPositive: c.grid_export_positive !== false,
      idleW: c.idle_threshold_w,
    });
    const reduce = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const today = c.today ? { ...this._today, solar: liveKwh(hass.states[c.today.solar]), used: directUseKwh(hass, c.today) } : null;
    const key = JSON.stringify([model, reduce, today]);
    if (key === this._key) return; // nothing changed: keep animations running, no DOM work
    this._key = key;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
    }
    const gridTone = { import: "warn", export: "ok", idle: "idle", unavailable: "bad" }[model.gridState];
    const kpi = (label, value, tone) => {
      if (value === null || value === undefined) return `<div class="kpi t-${tone}"><div class="lab">${label}</div><div class="val">—</div></div>`;
      const kwh = typeof value === "number" ? value : value.kwh;
      const lower = typeof value === "object" && value.incomplete ? "≥ " : "";
      return `<div class="kpi t-${tone}"><div class="lab">${label}</div><div class="val">${lower}${kwh.toFixed(kwh < 10 ? 2 : 1)}<span class="unit">kWh</span></div></div>`;
    };
    const withUsed = Boolean(c.today && c.today.used);
    const strip = today
      ? `<div class="kpis${withUsed ? " k4" : ""}">${kpi("Solar today", today.solar, "ok")}${withUsed ? kpi("Used directly", today.used, "ok") : ""}${kpi("Imported today", today.import, "warn")}${kpi("Exported today", today.export, "info")}</div>`
      : "";
    const compact = c.compact
      ? `ha-card{padding:calc(var(--u,11px)*1.3) calc(var(--u,11px)*1.5);gap:calc(var(--u,11px)*.7)}
        .head{min-height:0;gap:calc(var(--u,11px)*.7)}.head ha-icon{--mdc-icon-size:calc(var(--u,11px)*1.9)}
        .title{font-size:calc(var(--u,11px)*1.1)}.chip{font-size:calc(var(--u,11px)*1.15);padding:calc(var(--u,11px)*.2) calc(var(--u,11px)*.85)}
        .flow{flex:1;min-height:0;max-width:none;margin:0;display:flex;align-items:center;justify-content:center}
        .flow svg{width:auto;max-width:100%;height:100%;max-height:100%}
        .flow svg text{font-size:17px}.flow svg text:nth-of-type(n+1):not([font-weight]){font-size:16px}
        .kpis{margin-top:0;gap:calc(var(--u,11px)*.6)}
        .kpi{padding:calc(var(--u,11px)*.6) calc(var(--u,11px)*.8);border-radius:calc(var(--u,11px)*1.1)}
        .kpi .lab{font-size:calc(var(--u,11px)*1.0);letter-spacing:.03em;line-height:1.15}
        .kpi .val{font-size:calc(var(--u,11px)*1.7);margin-top:calc(var(--u,11px)*.15);white-space:nowrap}
        @media (max-width:759px){.flow svg{width:100%;height:auto}}`
      : "";
    this._root.innerHTML =
      `<ha-card><style>${UI_CSS}
        .flow{max-width:460px;width:100%;margin:0 auto}
        .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:auto}
        .kpis.k4{grid-template-columns:repeat(4,minmax(0,1fr))}
        .kpi{min-width:0}
        .kpi{padding:10px 12px;border-radius:14px;background:color-mix(in srgb,var(--primary-text-color) 6%,transparent)}
        .kpi .lab{font-size:12.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--secondary-text-color)}
        .kpi .val{font-size:clamp(20px,6cqw,28px);font-weight:600;margin-top:2px;color:var(--tw-tone)}
        .kpi .unit{font-size:.55em;font-weight:400;margin-left:.2em;color:var(--secondary-text-color)}
        ${compact}
      </style>` +
      `<div class="head">${iconHtml("mdi:flash")}<div class="title">${escapeHtml(c.title)}</div><span class="chip t-${gridTone}">${escapeHtml(model.gridLabel)}</span></div>` +
      `<div class="flow">${renderSvg(model, reduce)}</div>${strip}</ha-card>`;
  }

  _refreshToday() {
    const c = this._config;
    if (!c || !c.today || !this._hass || typeof this._hass.callWS !== "function") return;
    const cacheKey = JSON.stringify([c.today, c.timezone]);
    const entry = TODAY_CACHE.get(cacheKey) || { value: null, loadedAt: 0, loading: false, retryAt: 0, listeners: new Set() };
    TODAY_CACHE.set(cacheKey, entry);
    entry.listeners.add(this);
    if (entry.value) this._today = entry.value;
    const due = !entry.loadedAt || Date.now() - entry.loadedAt > TODAY_REFRESH_MS;
    if (!due || entry.loading || Date.now() < entry.retryAt) return;
    entry.loading = true;
    loadTodayEnergy(this._hass, c.today, c.timezone || DEFAULT_TIMEZONE)
      .then((value) => {
        entry.value = value;
        entry.loadedAt = Date.now();
        entry.retryAt = 0;
      })
      .catch(() => {
        entry.retryAt = Date.now() + 60e3; // keep the last good figures; try again in a minute
      })
      .finally(() => {
        entry.loading = false;
        for (const card of entry.listeners) {
          if (entry.value) card._today = entry.value;
          card._key = null;
          if (card._hass) card.hass = card._hass;
        }
      });
  }

  disconnectedCallback() {
    const c = this._config;
    if (c && c.today) {
      const entry = TODAY_CACHE.get(JSON.stringify([c.today, c.timezone]));
      if (entry) entry.listeners.delete(this);
    }
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return {
      solar_entity: "sensor.goodwe_inverter_pv_power",
      house_entity: "sensor.goodwe_inverter_house_consumption",
      grid_entity: "sensor.goodwe_inverter_meter_active_power",
    };
  }
}

if (typeof customElements !== "undefined" && !customElements.get("thermowatt-power-flow-card")) {
  customElements.define("thermowatt-power-flow-card", ThermowattPowerFlowCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "thermowatt-power-flow-card",
    name: "Thermowatt power flow",
    description: "Solar, house and grid power flow (measured values only)",
  });
}

/* ================================================================================================
 * Shared design system for the display cards below (panel, lights, power flow, device energy).
 * Everything is themed with Home Assistant's own CSS variables, so it follows the dark and light themes.
 * Typography scale: 15 px small caps titles, 40-68 px hero numbers, 20 px stat values, 15-17 px body.
 * ============================================================================================== */
const TONES = ["ok", "warn", "bad", "info", "idle"];

const UI_CSS = `
  :host{display:block;height:100%}
  *{box-sizing:border-box}
  ha-card{height:100%;display:flex;flex-direction:column;gap:16px;padding:20px 22px 22px;container-type:inline-size;overflow:hidden;
    --tw-ok:var(--success-color,#43a047);--tw-warn:var(--warning-color,#fb8c00);--tw-bad:var(--error-color,#e53935);
    --tw-info:var(--primary-color,#03a9f4);--tw-idle:var(--secondary-text-color,#9e9e9e)}
  .t-ok{--tw-tone:var(--tw-ok)}.t-warn{--tw-tone:var(--tw-warn)}.t-bad{--tw-tone:var(--tw-bad)}
  .t-info{--tw-tone:var(--tw-info)}.t-idle{--tw-tone:var(--tw-idle)}
  .head{display:flex;align-items:center;gap:12px;min-height:30px}
  .head ha-icon{--mdc-icon-size:24px;color:var(--primary-color);flex:none}
  .title{flex:1;min-width:0;font-size:15px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary-text-color)}
  .chip{display:inline-flex;align-items:center;gap:6px;padding:4px 13px;border-radius:999px;font-size:14px;font-weight:500;white-space:nowrap;
    color:var(--tw-tone,var(--tw-idle));background:color-mix(in srgb,var(--tw-tone,var(--tw-idle)) 16%,transparent)}
  .chips{display:flex;flex-wrap:wrap;gap:8px}
  .heroes{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px 20px}
  .hero .lab{font-size:15px;color:var(--secondary-text-color)}
  .hero .val{font-size:clamp(40px,13cqw,68px);font-weight:500;line-height:1.05;letter-spacing:-.02em;color:var(--primary-text-color)}
  .heroes.multi .val{font-size:clamp(34px,10cqw,58px)}
  .hero .unit{font-size:.4em;font-weight:400;color:var(--secondary-text-color);margin-left:.18em;letter-spacing:0}
  .hero .cap{font-size:15px;color:var(--secondary-text-color);margin-top:2px}
  .hero.t-ok .val,.hero.t-warn .val,.hero.t-bad .val,.hero.t-info .val{color:var(--tw-tone)}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
  .stats.cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.stats.cols-3{grid-template-columns:repeat(3,minmax(0,1fr))}.stats.cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}
  @container (max-width:360px){.stats.cols-3,.stats.cols-4{grid-template-columns:repeat(2,minmax(0,1fr))}}
  .stat{padding:12px 15px;border-radius:14px;background:color-mix(in srgb,var(--primary-text-color) 6%,transparent)}
  .stat .lab{font-size:12.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--secondary-text-color)}
  .stat .val{font-size:20px;font-weight:600;margin-top:4px;color:var(--primary-text-color)}
  .stat.t-ok .val,.stat.t-warn .val,.stat.t-bad .val,.stat.t-info .val{color:var(--tw-tone)}
  .stat .det{font-size:14.5px;color:var(--secondary-text-color);margin-top:2px}
  .group+.group{margin-top:6px}
  .group h4{margin:0 0 4px;font-size:13px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary-text-color)}
  .row{display:flex;justify-content:space-between;align-items:center;gap:18px;padding:12px 0;border-top:1px solid var(--divider-color,#444)}
  .row:first-of-type{border-top:0}
  .row .k{font-size:16px;color:var(--secondary-text-color)}
  .row .v{font-size:17px;font-weight:500;text-align:right;display:flex;align-items:center;gap:9px;color:var(--primary-text-color)}
  .dot{flex:none;width:10px;height:10px;border-radius:50%;background:var(--tw-tone,var(--tw-idle))}
  .note{margin:0;font-size:15px;line-height:1.5;color:var(--secondary-text-color)}
  .note b,.note strong{color:var(--primary-text-color)}
  .actions{display:grid;gap:12px}
  .action{all:unset;box-sizing:border-box;cursor:pointer;display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:14px;
    background:color-mix(in srgb,var(--primary-text-color) 6%,transparent);color:var(--primary-text-color)}
  .action:hover{background:color-mix(in srgb,var(--primary-color) 16%,transparent)}
  .action:focus-visible{outline:2px solid var(--primary-color)}
  .action ha-icon{--mdc-icon-size:26px;color:var(--primary-color);flex:none}
  .action .t{font-size:17px;font-weight:500}.action .d{font-size:14.5px;color:var(--secondary-text-color)}
`;

const ICON_PATTERN = /^[a-z0-9-]+:[a-z0-9-]+$/;
const iconHtml = (name) => (ICON_PATTERN.test(String(name || "")) ? `<ha-icon icon="${name}"></ha-icon>` : "");
const toneClass = (tone) => ` t-${TONES.includes(tone) ? tone : "idle"}`;
const chipHtml = (chip) =>
  chip && chip.text ? `<span class="chip${toneClass(chip.tone)}">${chip.icon ? iconHtml(chip.icon) : ""}${escapeHtml(chip.text)}</span>` : "";

/** Render one panel model (see thermowatt-panel-card). Every dynamic string is escaped; a missing value is a dash, never 0. */
export function renderPanel(model, actions = []) {
  const m = model && typeof model === "object" && !Array.isArray(model) ? model : {};
  const show = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));
  let html = `<div class="head">${iconHtml(m.icon)}<div class="title">${escapeHtml(m.title || "")}</div>${chipHtml(m.badge)}</div>`;
  const heroes = Array.isArray(m.heroes) ? m.heroes : m.hero ? [m.hero] : [];
  if (heroes.length) {
    html += `<div class="heroes${heroes.length > 1 ? " multi" : ""}">`;
    for (const h of heroes) {
      html +=
        `<div class="hero${toneClass(h.tone)}">` +
        (h.label ? `<div class="lab">${escapeHtml(h.label)}</div>` : "") +
        `<div class="val">${escapeHtml(show(h.value))}${h.unit && h.value !== null && h.value !== undefined && h.value !== "" ? `<span class="unit">${escapeHtml(h.unit)}</span>` : ""}</div>` +
        (h.caption ? `<div class="cap">${escapeHtml(h.caption)}</div>` : "") +
        "</div>";
    }
    html += "</div>";
  }
  if (Array.isArray(m.chips) && m.chips.length) html += `<div class="chips">${m.chips.map(chipHtml).join("")}</div>`;
  if (Array.isArray(m.stats) && m.stats.length) {
    html += `<div class="stats${[2, 3, 4].includes(m.columns) ? ` cols-${m.columns}` : ""}">`;
    for (const s of m.stats) {
      html += `<div class="stat${toneClass(s.tone)}"><div class="lab">${escapeHtml(s.label || "")}</div><div class="val">${escapeHtml(show(s.value))}</div>${s.detail ? `<div class="det">${escapeHtml(s.detail)}</div>` : ""}</div>`;
    }
    html += "</div>";
  }
  const groups = Array.isArray(m.groups) ? m.groups : Array.isArray(m.rows) ? [{ rows: m.rows }] : [];
  for (const g of groups) {
    html += `<div class="group">${g.title ? `<h4>${escapeHtml(g.title)}</h4>` : ""}`;
    for (const r of g.rows || []) {
      html += `<div class="row"><span class="k">${escapeHtml(r.label || "")}</span><span class="v${toneClass(r.tone)}">${r.tone ? '<span class="dot"></span>' : ""}${escapeHtml(show(r.value))}</span></div>`;
    }
    html += "</div>";
  }
  for (const line of Array.isArray(m.lines) ? m.lines : []) html += `<p class="note">${escapeHtml(line)}</p>`;
  if (actions.length) {
    html += '<div class="actions">';
    actions.forEach((a, i) => {
      html += `<button class="action" data-action="${i}">${iconHtml(a.icon || "mdi:cog-outline")}<span><span class="t">${escapeHtml(a.label || "")}</span>${a.detail ? `<br><span class="d">${escapeHtml(a.detail)}</span>` : ""}</span></button>`;
    });
    html += "</div>";
  }
  return html;
}

/** Parse what a rendered template returned: a JSON string, or the object Home Assistant already parsed. */
export function parsePanelResult(result) {
  if (result && typeof result === "object") return result;
  const text = String(result === undefined || result === null ? "" : result).trim();
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("the template must return a JSON object");
  return parsed;
}

function navigateTo(path) {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

const BaseUi = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

/**
 * <thermowatt-panel-card>: a large-type read-only information card. The plain-English text is produced by a
 * Home Assistant TEMPLATE (rendered server-side through the same render_template subscription the markdown
 * card uses) that returns a JSON object {title, icon, badge, hero|heroes, chips, stats, groups|rows, lines};
 * this card only lays it out. `model` may be given instead of `template` for static content. `actions` are
 * navigation buttons ({label, detail, icon, path}). It never calls a service.
 */
class ThermowattPanelCard extends BaseUi {
  setConfig(config) {
    if (!config || (!config.template && !config.model)) throw new Error("template or model is required");
    for (const a of config.actions || []) {
      if (typeof a.path !== "string" || !a.path.startsWith("/")) throw new Error("an action path must start with /");
    }
    this._config = { ...config };
    this._model = config.model || null;
    this._error = null;
    this._key = null;
  }

  connectedCallback() {
    this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  set hass(hass) {
    this._hass = hass;
    this._subscribe();
    this._render();
  }

  async _subscribe() {
    const c = this._config;
    if (!c || !c.template || !this._hass || this._unsub || this._subscribing) return;
    if (!this._hass.connection || !this._hass.connection.subscribeMessage) return;
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage((message) => this._onMessage(message), {
        type: "render_template",
        template: c.template,
        report_errors: true,
      });
    } catch (error) {
      this._error = String(error && error.message ? error.message : error);
      this._render();
    } finally {
      this._subscribing = false;
    }
  }

  _onMessage(message) {
    try {
      if (message.error) throw new Error(message.error);
      this._model = parsePanelResult(message.result);
      this._error = null;
    } catch (error) {
      this._error = String(error && error.message ? error.message : error);
    }
    this._render();
  }

  getCardSize() {
    return this._config && this._config.size ? this._config.size : 4;
  }

  _render() {
    if (!this._config) return;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const action = (this._config.actions || [])[Number(button.dataset.action)];
        if (action) navigateTo(action.path);
      });
    }
    const body = this._error
      ? `<div class="head"><div class="title">${escapeHtml((this._model && this._model.title) || this._config.title || "Unavailable")}</div></div><p class="note">This card could not be shown (${escapeHtml(this._error)}). The rest of the dashboard is unaffected.</p>`
      : this._model
        ? renderPanel(this._model, this._config.actions || [])
        : `<div class="head"><div class="title">${escapeHtml(this._config.title || "")}</div></div><p class="note">Loading…</p>`;
    const key = body;
    if (key === this._key) return; // unchanged: no DOM work, focus and hover survive
    this._key = key;
    this._root.innerHTML = `<ha-card><style>${UI_CSS}</style>${body}</ha-card>`;
  }
}

/* ------------------------------------------------------------------------------------------------
 * <thermowatt-lights-card>: every eligible light, discovered at run time (nothing to regenerate when a light is
 * added). Each light shows its friendly name and state, a tap to switch it, and a brightness slider only when it
 * can dim. A light is NOT shown when it is: excluded (the `exclude` list, or a Home Assistant label named by
 * `exclude_label`), hidden or a configuration/diagnostic entity in the registry, unavailable, a light GROUP
 * (its members are shown instead) or a duplicate (same device and name as one already shown).
 * `lights` (entity + optional name) may still pin an order or a display name; `names` renames by entity ID.
 * ---------------------------------------------------------------------------------------------- */
/** "light.hall_light" -> "Hall light": a readable name when Home Assistant gives the entity no friendly name. */
export function prettyEntityName(entityId) {
  const text = String(entityId).split(".").pop().replace(/_+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : String(entityId);
}

export function discoverLights(hass, config) {
  const exclude = new Set((config.exclude || []).map(String));
  const label = config.exclude_label ? String(config.exclude_label) : "";
  const names = config.names || {};
  const states = hass.states || {};
  const registry = hass.entities || {};
  const out = [];
  const seen = new Set();
  const seenDevice = new Set();
  let unavailable = 0;
  const excluded = []; // every light that is NOT shown, with the plain-English reason (the Lights page lists them)
  const showLabel = config.show_as_light_label === undefined ? "show_as_light" : String(config.show_as_light_label || "");
  const labelsOf = (entry) => entry.labels || entry.lb || [];
  const skip = (entityId, name, reason) => {
    seen.add(entityId);
    excluded.push({ entityId, name, reason });
  };
  const consider = (entityId, pinnedName) => {
    if (seen.has(entityId)) return;
    const state = states[entityId];
    const entry = registry[entityId] || {};
    const attrs = (state && state.attributes) || {};
    const name = names[entityId] || pinnedName || attrs.friendly_name || prettyEntityName(entityId);
    if (exclude.has(entityId)) return skip(entityId, name, "Excluded in the dashboard configuration");
    if (!state) return skip(entityId, name, "Home Assistant has not loaded it (disabled, removed or still starting)");
    if (entry.hidden || entry.hb) return skip(entityId, name, "Hidden in the entity settings");
    if (entry.entity_category || entry.ec) return skip(entityId, name, "A configuration or diagnostic entity, not a light");
    if (label && labelsOf(entry).includes(label)) return skip(entityId, name, `Has the "${label}" label`);
    if (config.exclude_groups !== false && Array.isArray(attrs.entity_id) && attrs.entity_id.length) return skip(entityId, name, "A light group: its member lights are shown instead");
    const deviceId = entry.device_id || entry.di;
    const duplicate = deviceId ? `${deviceId}|${String(name).toLowerCase()}` : null;
    if (duplicate && seenDevice.has(duplicate)) return skip(entityId, name, "A duplicate of a light already shown (same device and name)");
    if (state.state === "unavailable" || state.state === "unknown") {
      if (!config.show_unavailable) {
        unavailable += 1;
        skip(entityId, name, `Currently ${state.state}`);
        return;
      }
    }
    seen.add(entityId);
    if (duplicate) seenDevice.add(duplicate);
    out.push({ entityId, name, state, domain: entityId.split(".")[0] });
  };
  for (const l of config.lights || []) consider(l.entity, l.name); // pinned first, in the configured order
  // A switch (a smart plug or relay that powers a lamp) is shown as a light only when the owner gives it the
  // `show_as_light` label: Home Assistant cannot tell a lamp plug from a heater plug, so it is never guessed.
  const labelled = showLabel
    ? Object.keys(states).filter((id) => !id.startsWith("light.") && ["switch", "input_boolean"].includes(id.split(".")[0]) && labelsOf(registry[id] || {}).includes(showLabel))
    : [];
  const rest = [...Object.keys(states).filter((id) => id.startsWith("light.")), ...labelled].filter((id) => !seen.has(id));
  const shownName = (id) => String(names[id] || (states[id].attributes || {}).friendly_name || prettyEntityName(id));
  rest.sort((a, b) => shownName(a).localeCompare(shownName(b), undefined, { numeric: true }));
  for (const id of rest) consider(id, null);
  // Switches that LOOK like lamps but carry no label: never shown automatically, listed as a hint.
  const lampLike = /light|lamp|lantern|downlight|porch|garden|deck|patio|spot/i;
  const candidates = [];
  for (const id of Object.keys(states)) {
    if (!id.startsWith("switch.") || seen.has(id)) continue;
    const text = `${id} ${(states[id].attributes || {}).friendly_name || ""}`;
    if (lampLike.test(text)) candidates.push({ entityId: id, name: (states[id].attributes || {}).friendly_name || prettyEntityName(id), state: states[id].state });
  }
  return { lights: out, unavailable, excluded, candidates };
}

/** Brightness 1-100 for a dimmable light that is on, else null. */
export function brightnessPct(state) {
  if (!state || state.state !== "on") return null;
  const b = Number((state.attributes || {}).brightness);
  return Number.isFinite(b) ? Math.max(1, Math.round((b / 255) * 100)) : null;
}

/** A light dims when it supports any colour mode other than plain on/off. */
export function isDimmable(state) {
  const modes = (state && state.attributes && state.attributes.supported_color_modes) || [];
  return modes.length > 0 && modes.some((m) => m !== "onoff");
}

class ThermowattLightsCard extends BaseUi {
  setConfig(config) {
    this._config = { title: "Lights", discover: true, exclude_label: "hide_from_dashboard", show_as_light_label: "show_as_light", ...config };
    for (const l of this._config.lights || []) if (!l || typeof l.entity !== "string" || !l.entity.startsWith("light.")) throw new Error("every pinned light needs a light entity");
    this._key = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 3;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const found = discoverLights(this._hass, this._config);
    const lights = found.lights;
    const key = JSON.stringify([found.unavailable, this._config.diagnostics ? [found.excluded, found.candidates] : 0, lights.map((l) => [l.entityId, l.name, l.state.state, l.state.attributes.brightness, isDimmable(l.state)])]);
    if (key === this._key) return;
    this._key = key;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.addEventListener("click", (event) => {
        const tile = event.target.closest("button[data-toggle]");
        if (!tile || tile.disabled) return;
        const id = tile.dataset.toggle;
        this._hass.callService(id.startsWith("light.") ? "light" : "homeassistant", "toggle", { entity_id: id });
      });
      this._root.addEventListener("change", (event) => {
        const slider = event.target.closest("input[data-brightness]");
        if (slider) this._hass.callService("light", "turn_on", { entity_id: slider.dataset.brightness, brightness_pct: Number(slider.value) });
      });
    }
    const on = lights.filter((l) => l.state.state === "on").length;
    const density = lights.length > 8 ? "dense" : lights.length > 4 ? "medium" : "roomy";
    let body = `<div class="head">${iconHtml("mdi:lightbulb-group")}<div class="title">${escapeHtml(this._config.title)}</div>${lights.length ? `<span class="chip${on ? " t-warn" : " t-idle"}">${on} of ${lights.length} on</span>` : ""}</div>`;
    if (!lights.length) body += '<p class="note">No lights were found. Lights appear here automatically when Home Assistant has them.</p>';
    body += `<div class="lights ${density}">`;
    for (const l of lights) {
      const s = l.state.state;
      const pct = brightnessPct(l.state);
      const dim = l.domain === "light" && isDimmable(l.state) && s === "on";
      const label = s === "on" ? (pct === null ? "On" : `On · ${pct}%`) : s === "off" ? "Off" : "Unavailable";
      const usable = s === "on" || s === "off";
      body +=
        `<div class="light${s === "on" ? " on" : ""}${usable ? "" : " off-line"}">` +
        `<button class="lt" data-toggle="${escapeHtml(l.entityId)}"${usable ? "" : " disabled"} aria-label="${escapeHtml(l.name)}: ${escapeHtml(label)}">${iconHtml(s === "on" ? "mdi:lightbulb-on" : "mdi:lightbulb-outline")}<span class="n">${escapeHtml(l.name)}</span><span class="s">${escapeHtml(label)}</span></button>` +
        (dim ? `<input type="range" min="1" max="100" value="${pct === null ? 100 : pct}" data-brightness="${escapeHtml(l.entityId)}" aria-label="${escapeHtml(l.name)} brightness">` : "") +
        "</div>";
    }
    body += "</div>";
    if (found.unavailable && !this._config.diagnostics) body += `<p class="note small">${found.unavailable} unavailable light${found.unavailable === 1 ? " is" : "s are"} not shown.</p>`;
    if (this._config.diagnostics) {
      const row = (r) => `<li><b>${escapeHtml(r.name)}</b> <code>${escapeHtml(r.entityId)}</code><br><span>${escapeHtml(r.reason)}</span></li>`;
      body += `<details class="diag" open><summary>Why some lights are not shown (${found.excluded.length})</summary>${found.excluded.length ? `<ul>${found.excluded.map(row).join("")}</ul>` : '<p class="note small">Every light entity Home Assistant has loaded is shown above.</p>'}</details>`;
      if (found.candidates.length) {
        body += `<details class="diag" open><summary>Switches that look like lamps (${found.candidates.length})</summary><p class="note small">Home Assistant lists these as switches, not lights. To show one here, add the label <b>${escapeHtml(this._config.show_as_light_label)}</b> to it in Settings → Areas, labels &amp; zones → Labels.</p><ul>${found.candidates.map((r) => `<li><b>${escapeHtml(r.name)}</b> <code>${escapeHtml(r.entityId)}</code> <span>(${escapeHtml(r.state)})</span></li>`).join("")}</ul></details>`;
      }
      body += '<p class="note small">A light Home Assistant has disabled, or an entity of another type, is not in this list. Settings → Devices &amp; services → Entities shows disabled entities.</p>';
    }
    this._root.innerHTML = `<ha-card><style>${UI_CSS}
      .lights{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
      .lights.medium{gap:10px;grid-template-columns:repeat(auto-fill,minmax(148px,1fr))}
      .lights.dense{gap:8px;grid-template-columns:repeat(auto-fill,minmax(128px,1fr))}
      .light{display:flex;flex-direction:column;justify-content:center;gap:8px;padding:12px;border-radius:16px;background:color-mix(in srgb,var(--primary-text-color) 6%,transparent);min-width:0}
      .light.on{background:color-mix(in srgb,var(--state-light-active-color,#ffc107) 20%,transparent)}
      .light.off-line{opacity:.55}
      .lt{all:unset;box-sizing:border-box;cursor:pointer;display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:auto auto;column-gap:10px;align-items:center}
      .lt[disabled]{cursor:default}
      .lt ha-icon{--mdc-icon-size:30px;grid-row:1 / span 2;color:var(--secondary-text-color)}
      .light.on .lt ha-icon{color:var(--state-light-active-color,#ffc107)}
      .lt .n{font-size:16.5px;font-weight:600;line-height:1.2;color:var(--primary-text-color);overflow:hidden;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
      .lt .s{font-size:14.5px;color:var(--secondary-text-color)}
      .dense .lt .n{font-size:15px}.dense .lt ha-icon{--mdc-icon-size:24px}.dense .light{padding:10px}
      .lt:focus-visible{outline:2px solid var(--primary-color);border-radius:8px}
      input[type=range]{width:100%;accent-color:var(--state-light-active-color,#ffc107);margin:2px 0 0}
      .small{font-size:13.5px}
      .diag{margin-top:6px;font-size:14.5px;color:var(--primary-text-color)}
      .diag summary{cursor:pointer;font-weight:600}
      .diag ul{margin:8px 0 0;padding-left:20px}.diag li{margin:0 0 8px}.diag li span{color:var(--secondary-text-color)}
      .diag code{font-size:12.5px;color:var(--secondary-text-color)}
      ${
        this._config.compact
          ? `ha-card{padding:calc(var(--u,11px)*1.35) calc(var(--u,11px)*1.5);gap:calc(var(--u,11px)*.8);overflow:hidden}
        .head{min-height:0}.head ha-icon{--mdc-icon-size:calc(var(--u,11px)*1.9)}.title{font-size:calc(var(--u,11px)*1.1)}.chip{font-size:calc(var(--u,11px)*1.15)}
        .lights,.lights.medium,.lights.dense{flex:1;min-height:0;overflow:auto;scrollbar-width:none;gap:calc(var(--u,11px)*.7);grid-template-columns:repeat(auto-fill,minmax(calc(var(--u,11px)*10.5),1fr));align-content:start}
        .light{padding:calc(var(--u,11px)*.9);border-radius:calc(var(--u,11px)*1.2);gap:calc(var(--u,11px)*.5)}
        .lt{column-gap:calc(var(--u,11px)*.7)}.lt ha-icon,.dense .lt ha-icon{--mdc-icon-size:calc(var(--u,11px)*2.4)}
        .lt .n,.dense .lt .n{font-size:calc(var(--u,11px)*1.3)}.lt .s{font-size:calc(var(--u,11px)*1.1)}
        input[type=range]{height:max(28px,calc(var(--u,11px)*2.4))}`
          : ""
      }
      </style>${body}</ha-card>`;
  }
}

/* ------------------------------------------------------------------------------------------------
 * <thermowatt-home-page>: the everyday Home page for a tablet in landscape (the primary display), as ONE card in a
 * Home Assistant "panel" view. It measures the space the browser really gives it (window height below its own top
 * edge, never the tablet's physical resolution) and lays six cards out to fit WITHOUT scrolling: energy | hot water |
 * weather and doors over bathroom 1 | bathroom 2 | lights. Type scales with the measured height inside a readable
 * range. Below 760 px wide (a phone) it is a single natural-height column. States are read only; the one control it
 * adds is the existing timed manual fan override of each bathroom (switch.turn_on / switch.turn_off on the Tapo
 * Smart Controller's own manual-override switch): it only adds demand, never interrupts automatic extraction, and
 * never touches the towel rail (status only here). Hot-water overrides are NOT offered here.
 * ---------------------------------------------------------------------------------------------- */
const BAD_STATES = ["unknown", "unavailable", "none", ""];
const stateOf = (hass, entityId) => (entityId && hass.states ? hass.states[entityId] : undefined);
const validState = (hass, entityId) => {
  const s = stateOf(hass, entityId);
  return s && !BAD_STATES.includes(String(s.state).toLowerCase()) ? s : null;
};
const niceText = (value) => {
  const text = String(value).replace(/_/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : "";
};
const clockText = (value, timeZone) => {
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? new Date(ms).toLocaleTimeString("en-AU", { timeZone, hour: "2-digit", minute: "2-digit", hour12: false }) : null;
};

/** Solar boost for the Home page: Off when the setting is off, else Active / Waiting from the controller's status. */
export function solarBoostLabel(status, enabledState) {
  if (String(enabledState || "").toLowerCase() === "off") return { text: "Off", tone: "idle" };
  switch (String(status || "").trim().toLowerCase()) {
    case "active":
      return { text: "Active", tone: "ok" };
    case "waiting":
    case "waiting to restart":
    case "cooldown":
      return { text: "Waiting", tone: "info" };
    case "off unconfirmed":
    case "stopping":
      return { text: "Stopping", tone: "warn" };
    default:
      return { text: "—", tone: "idle" };
  }
}

const TARIFF_TEXT = { off_peak: "Off-peak", peak: "Peak", shoulder: "Shoulder" };
const NEXT_ACTION_TEXT = {
  parked: "Heater off",
  baseline_45: "Hold 45 °C",
  normal_storage_62: "Heat to 62 °C",
  storage_70: "Solar boost 70 °C",
};

/** Everything the hot-water card shows, in plain English. A missing value is a dash, never a guess. */
export function hotWaterModel(hass, c, timeZone = "Australia/Hobart") {
  const read = (key) => validState(hass, c[key]);
  const temp = read("temperature");
  const tempValue = temp && Number.isFinite(Number(temp.state)) ? Number(temp.state) : null;
  const target = read("target");
  const targetValue = target && Number.isFinite(Number(target.state)) ? Math.round(Number(target.state)) : null;
  const mode = read("mode");
  const auto = stateOf(hass, c.automatic);
  const operating = read("operating");
  const tariff = read("tariff");
  const enabled = stateOf(hass, c.boost_enabled);
  const boost = solarBoostLabel(read("boost") && read("boost").state, enabled && enabled.state);
  const nextAction = read("next_action");
  const autoState = auto ? auto.state : null;
  const control =
    operating && operating.state === "guest"
      ? { text: "12 h override", tone: "warn" }
      : autoState === "on"
        ? { text: "Automatic on", tone: "ok" }
        : autoState === "off"
          ? { text: "Automatic off", tone: "warn" }
          : { text: "Status unknown", tone: "idle" };
  return {
    temperature: tempValue === null ? null : tempValue.toFixed(1),
    mode: mode ? niceText(mode.state) : null,
    target: targetValue,
    control,
    tariff: tariff ? { text: TARIFF_TEXT[tariff.state] || niceText(tariff.state), tone: tariff.state === "peak" ? "warn" : tariff.state === "off_peak" ? "ok" : "idle" } : { text: "—", tone: "idle" },
    boost,
    lastPoll: read("last_poll") ? clockText(read("last_poll").state, timeZone) : null,
    nextPoll: read("next_poll") ? clockText(read("next_poll").state, timeZone) : null,
    nextAction: nextAction ? NEXT_ACTION_TEXT[nextAction.state] || niceText(nextAction.state) : null,
  };
}

/** The manual-fan button for one bathroom: run, cancel (with the minutes left) or inert. */
export function fanButton(manualState, remainingSeconds, configuredMinutes, fanState) {
  const manual = String(manualState || "").toLowerCase();
  const fan = String(fanState || "").toLowerCase();
  if (BAD_STATES.includes(manual) || BAD_STATES.includes(fan)) return { kind: "inert", label: "Fan unavailable" };
  if (manual === "on") {
    const seconds = Number(remainingSeconds);
    const minutes = Number.isFinite(seconds) && seconds > 0 ? Math.max(1, Math.ceil(seconds / 60)) : null;
    return { kind: "cancel", label: minutes === null ? "Cancel fan" : `Cancel fan — ${minutes} min left` };
  }
  const length = Number.isFinite(Number(configuredMinutes)) && Number(configuredMinutes) > 0 ? Math.round(Number(configuredMinutes)) : 20;
  return { kind: "run", label: `Run fan — ${length} min` };
}

/** One bathroom's card: numbers, shower, the actual fan and towel-rail state, drying time left and the fan button. */
export function bathroomModel(hass, b) {
  const num = (id, digits) => {
    const s = validState(hass, id);
    const v = s ? Number(s.state) : NaN;
    return Number.isFinite(v) ? v.toFixed(digits) : null;
  };
  const attrs = (s) => (s && s.attributes) || {};
  const good = (s) => s && !BAD_STATES.includes(String(s.state).toLowerCase());
  const shower = validState(hass, b.shower);
  const fan = stateOf(hass, b.fan_running);
  const towel = stateOf(hass, b.towel_heating);
  const manual = stateOf(hass, b.fan_switch);
  const drying = stateOf(hass, b.towel_remaining);
  const seconds = good(drying) ? Number(attrs(drying).remaining_seconds) : NaN;
  const dryingLeft =
    Number.isFinite(seconds) && seconds > 0
      ? `${Math.floor(seconds / 3600) ? `${Math.floor(seconds / 3600)} h ` : ""}${Math.round((seconds % 3600) / 60)} min left${attrs(drying).waiting_for_off_peak ? " · waiting for off-peak" : ""}`
      : null;
  return {
    name: b.name,
    humidity: num(b.humidity, 0),
    temperature: num(b.temperature, 1),
    shower: shower ? shower.state === "on" : null,
    fanText: good(fan) && attrs(fan).summary ? attrs(fan).summary : "Status unknown",
    towelText: good(towel) && attrs(towel).summary ? attrs(towel).summary : "Status unknown",
    dryingLeft,
    button: fanButton(manual && manual.state, attrs(manual).remaining_seconds, attrs(manual).configured_minutes, fan && fan.state),
  };
}

const HOME_CSS = `
  :host{display:block;--u:11px}
  .grid{height:100%;display:grid;gap:calc(var(--u)*.9);grid-template-columns:1.12fr 1fr .92fr;grid-template-rows:minmax(0,1.22fr);grid-auto-rows:minmax(0,1fr)}
  .cell{min-width:0;min-height:0;display:flex;flex-direction:column;gap:calc(var(--u)*.8)}
  .cell>*{min-height:0}
  .cell>thermowatt-power-flow-card,.cell>thermowatt-lights-card{flex:1}
  .cell>.wx{flex:1;overflow:hidden;border-radius:var(--ha-card-border-radius,12px)}
  .wx>*{display:block;height:100%}
  ha-card.pg{flex:1;display:flex;flex-direction:column;gap:calc(var(--u)*.8);padding:calc(var(--u)*1.35) calc(var(--u)*1.5);overflow:hidden;container-type:inline-size;
    --tw-ok:var(--success-color,#43a047);--tw-warn:var(--warning-color,#fb8c00);--tw-bad:var(--error-color,#e53935);--tw-info:var(--primary-color,#03a9f4);--tw-idle:var(--secondary-text-color,#9e9e9e)}
  ha-card.strip{flex:none;display:flex;align-items:center;gap:calc(var(--u)*.8);padding:calc(var(--u)*.7) calc(var(--u)*1.2);
    --tw-ok:var(--success-color,#43a047);--tw-warn:var(--warning-color,#fb8c00);--tw-bad:var(--error-color,#e53935);--tw-info:var(--primary-color,#03a9f4);--tw-idle:var(--secondary-text-color,#9e9e9e)}
  .strip ha-icon{--mdc-icon-size:calc(var(--u)*1.9);color:var(--primary-color)}
  .strip .k{flex:1;font-size:calc(var(--u)*1.1);font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary-text-color)}
  .h{display:flex;align-items:center;gap:calc(var(--u)*.7)}
  .h ha-icon{--mdc-icon-size:calc(var(--u)*1.9);color:var(--primary-color);flex:none}
  .t{flex:1;min-width:0;font-size:calc(var(--u)*1.1);font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary-text-color);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .chip{display:inline-flex;align-items:center;padding:calc(var(--u)*.2) calc(var(--u)*.85);border-radius:999px;font-size:calc(var(--u)*1.15);font-weight:500;white-space:nowrap;color:var(--tw-tone,var(--tw-idle));background:color-mix(in srgb,var(--tw-tone,var(--tw-idle)) 16%,transparent)}
  .t-ok{--tw-tone:var(--tw-ok)}.t-warn{--tw-tone:var(--tw-warn)}.t-bad{--tw-tone:var(--tw-bad)}.t-info{--tw-tone:var(--tw-info)}.t-idle{--tw-tone:var(--tw-idle)}
  .big{font-size:calc(var(--u)*4.4);font-weight:500;line-height:1;letter-spacing:-.02em;color:var(--primary-text-color);white-space:nowrap}
  .big .unit{font-size:.4em;font-weight:400;color:var(--secondary-text-color);margin-left:.15em;letter-spacing:0}
  .lab{font-size:calc(var(--u)*1.1);color:var(--secondary-text-color)}
  .top{display:grid;grid-template-columns:auto 1fr;gap:calc(var(--u)*1.2);align-items:center}
  .facts{display:grid;gap:calc(var(--u)*.7) calc(var(--u)*.9);grid-template-columns:repeat(var(--n,2),minmax(0,1fr))}
  .fact{min-width:0}
  .fact .k{font-size:calc(var(--u)*.95);font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--secondary-text-color)}
  .fact .v{font-size:calc(var(--u)*1.5);font-weight:600;color:var(--primary-text-color);line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .fact .s{font-size:calc(var(--u)*1.05);color:var(--secondary-text-color)}
  .fact.t-ok .v,.fact.t-warn .v,.fact.t-info .v,.fact.t-bad .v{color:var(--tw-tone)}
  .foot{margin-top:auto;font-size:calc(var(--u)*1.1);color:var(--secondary-text-color)}
  .nums{display:grid;grid-template-columns:1fr 1fr;gap:calc(var(--u)*1)}
  .nums .big{font-size:calc(var(--u)*3.4)}
  .line{font-size:calc(var(--u)*1.2);color:var(--secondary-text-color);line-height:1.25;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
  .line b{color:var(--primary-text-color);font-weight:600;margin-right:.4em}
  button.fan{all:unset;box-sizing:border-box;cursor:pointer;margin-top:auto;display:flex;align-items:center;justify-content:center;gap:calc(var(--u)*.6);min-height:max(44px,calc(var(--u)*3.8));padding:0 calc(var(--u)*1.2);border-radius:calc(var(--u)*1.2);font-size:calc(var(--u)*1.35);font-weight:600;
    background:color-mix(in srgb,var(--primary-color) 18%,transparent);color:var(--primary-color)}
  button.fan ha-icon{--mdc-icon-size:calc(var(--u)*1.9)}
  button.fan.cancel{background:color-mix(in srgb,var(--warning-color,#fb8c00) 22%,transparent);color:var(--warning-color,#fb8c00)}
  button.fan.inert{cursor:default;background:color-mix(in srgb,var(--primary-text-color) 8%,transparent);color:var(--secondary-text-color)}
  button.fan:focus-visible{outline:2px solid var(--primary-color)}
  @container (max-width:300px){.top{grid-template-columns:1fr}.big{font-size:calc(var(--u)*3.8)}}
  @media (max-width:759px){
    :host{height:auto!important}
    .grid{display:flex;flex-direction:column;height:auto}
    .cell{flex:none}
    .cell>thermowatt-power-flow-card{min-height:calc(var(--u)*30)}
    .cell>thermowatt-lights-card{min-height:calc(var(--u)*12)}
    .cell>.wx{min-height:calc(var(--u)*24)}
    ha-card.pg{flex:none}
  }
`;

class ThermowattHomePage extends BaseUi {
  setConfig(config) {
    if (!config || !config.flow || !config.hot_water) throw new Error("flow and hot_water are required");
    this._config = { timezone: "Australia/Hobart", bathrooms: [], ...config };
    this._built = false;
    this._keys = {};
  }

  getCardSize() {
    return 12;
  }

  connectedCallback() {
    this._onResize = () => this._fit();
    window.addEventListener("resize", this._onResize);
    if (this._built) requestAnimationFrame(() => this._fit());
  }

  disconnectedCallback() {
    window.removeEventListener("resize", this._onResize);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._built) this._build();
    this._update();
  }

  /** Fit to the space the browser really offers: window height below this card's top edge (not the panel's pixels). */
  _fit() {
    if (!this._root || typeof window === "undefined") return;
    if (window.innerWidth < 760) {
      this.style.height = "auto";
      this.style.setProperty("--u", "13px");
      return;
    }
    const top = this.getBoundingClientRect().top;
    const available = Math.max(420, Math.floor(window.innerHeight - top - 8));
    this.style.height = `${available}px`;
    // type scales with the measured height inside a readable range
    const u = Math.min(14, Math.max(9.6, available / 52));
    this.style.setProperty("--u", `${u.toFixed(2)}px`);
  }

  _build() {
    this._built = true;
    const c = this._config;
    const root = this.attachShadow({ mode: "open" });
    this._root = root;
    root.innerHTML = `<style>${HOME_CSS}</style><div class="grid">
      <div class="cell" id="c-energy"></div>
      <div class="cell"><ha-card class="pg" id="hot"></ha-card></div>
      <div class="cell"><div class="wx" id="weather"></div><ha-card class="strip" id="doors"></ha-card></div>
      ${(c.bathrooms || []).map((_, i) => `<div class="cell"><ha-card class="pg" id="bath${i}"></ha-card></div>`).join("")}
      <div class="cell" id="c-lights"></div>
    </div>`;
    // the animated flow diagram and the lights are the existing cards, embedded in compact mode
    this._flow = document.createElement("thermowatt-power-flow-card");
    this._flow.setConfig({ ...c.flow, title: c.flow.title || "Energy now", compact: true });
    root.getElementById("c-energy").appendChild(this._flow);
    this._lights = document.createElement("thermowatt-lights-card");
    this._lights.setConfig({ ...(c.lights || { discover: true }), compact: true, title: "Lights" });
    root.getElementById("c-lights").appendChild(this._lights);
    root.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-fan]");
      if (!button || button.classList.contains("inert")) return;
      const b = (this._config.bathrooms || [])[Number(button.dataset.fan)];
      if (!b || !b.fan_switch || !this._hass) return;
      this._hass.callService("switch", button.classList.contains("cancel") ? "turn_off" : "turn_on", { entity_id: b.fan_switch });
    });
    this._mountWeather(root.getElementById("weather"));
    requestAnimationFrame(() => this._fit());
  }

  async _mountWeather(host) {
    const w = this._config.weather;
    if (!w || !w.entity) {
      host.innerHTML = '<ha-card class="pg"><div class="line">Weather is not configured.</div></ha-card>';
      return;
    }
    try {
      const helpers = await window.loadCardHelpers();
      this._weather = await helpers.createCardElement({ type: "weather-forecast", entity: w.entity, ...(w.name ? { name: w.name } : {}), show_current: true, show_forecast: true, forecast_type: "daily" });
      host.appendChild(this._weather);
      if (this._hass) this._weather.hass = this._hass;
    } catch (error) {
      host.innerHTML = '<ha-card class="pg"><div class="line">Weather could not be shown.</div></ha-card>';
    }
  }

  _set(id, key, html) {
    if (this._keys[id] === key) return;
    this._keys[id] = key;
    this._root.getElementById(id).innerHTML = html;
  }

  _update() {
    const hass = this._hass;
    const c = this._config;
    this._flow.hass = hass;
    this._lights.hass = hass;
    if (this._weather) this._weather.hass = hass;
    const hw = hotWaterModel(hass, c.hot_water, c.timezone);
    const fact = (k, v, tone, sub) => `<div class="fact${toneClass(tone)}"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v ?? "—")}</div>${sub ? `<div class="s">${escapeHtml(sub)}</div>` : ""}</div>`;
    const polls = `Last poll ${hw.lastPoll || "—"} · next ${hw.nextPoll || "—"}`;
    this._set(
      "hot",
      JSON.stringify(hw),
      `<div class="h">${iconHtml("mdi:water-boiler")}<div class="t">Hot water</div><span class="chip${toneClass(hw.control.tone)}">${escapeHtml(hw.control.text)}</span></div>
       <div class="top"><div><div class="big">${escapeHtml(hw.temperature ?? "—")}${hw.temperature === null ? "" : '<span class="unit">°C</span>'}</div><div class="lab">Water temperature</div></div>
       <div class="facts" style="--n:1">${fact("Heater", hw.mode, null, hw.target === null ? null : `Target ${hw.target} °C`)}</div></div>
       <div class="facts" style="--n:2">${fact("Tariff", hw.tariff.text, hw.tariff.tone)}${fact("Solar boost", hw.boost.text, hw.boost.tone)}<div style="grid-column:1 / -1">${fact("Next", hw.nextAction)}</div></div>
       <div class="foot">${escapeHtml(polls)}</div>`
    );
    const doors = c.doors || {};
    const garage = validState(hass, doors.garage_position);
    const front = stateOf(hass, doors.front_open);
    const garageText = garage && garage.state === "Closed" ? { v: "closed", t: "ok" } : garage && garage.state === "Not closed" ? { v: "not closed", t: "warn" } : { v: "unknown", t: "idle" };
    const frontText = front && front.state === "off" ? { v: "closed", t: "ok" } : front && front.state === "on" ? { v: "open", t: "warn" } : { v: "unknown", t: "idle" };
    this._set(
      "doors",
      JSON.stringify([garageText, frontText]),
      `${iconHtml("mdi:shield-home")}<span class="k">Doors</span><span class="chip${toneClass(garageText.t)}">Garage ${garageText.v}</span><span class="chip${toneClass(frontText.t)}">Front ${frontText.v}</span>`
    );
    (c.bathrooms || []).forEach((b, i) => {
      const m = bathroomModel(hass, b);
      const shower = m.shower === null ? { text: "Shower unknown", tone: "idle" } : m.shower ? { text: "Shower detected", tone: "info" } : { text: "No shower", tone: "idle" };
      this._set(
        `bath${i}`,
        JSON.stringify(m),
        `<div class="h">${iconHtml("mdi:shower-head")}<div class="t">${escapeHtml(m.name)}</div><span class="chip${toneClass(shower.tone)}">${escapeHtml(shower.text)}</span></div>
         <div class="nums"><div><div class="big">${escapeHtml(m.humidity ?? "—")}${m.humidity === null ? "" : '<span class="unit">%</span>'}</div><div class="lab">Humidity</div></div>
         <div><div class="big">${escapeHtml(m.temperature ?? "—")}${m.temperature === null ? "" : '<span class="unit">°C</span>'}</div><div class="lab">Temperature</div></div></div>
         <div class="line"><b>Fan</b>${escapeHtml(m.fanText)}</div>
         <div class="line"><b>Towel rail</b>${escapeHtml(m.towelText)}${m.dryingLeft ? ` · ${escapeHtml(m.dryingLeft)}` : ""}</div>
         <button class="fan ${m.button.kind}" data-fan="${i}"${m.button.kind === "inert" ? " disabled" : ""}>${iconHtml("mdi:fan")}${escapeHtml(m.button.label)}</button>`
      );
    });
  }
}

if (typeof customElements !== "undefined") {
  if (!customElements.get("thermowatt-panel-card")) customElements.define("thermowatt-panel-card", ThermowattPanelCard);
  if (!customElements.get("thermowatt-lights-card")) customElements.define("thermowatt-lights-card", ThermowattLightsCard);
  if (!customElements.get("thermowatt-home-page")) customElements.define("thermowatt-home-page", ThermowattHomePage);
  window.customCards = window.customCards || [];
  window.customCards.push(
    { type: "thermowatt-panel-card", name: "Thermowatt panel", description: "Large-type status panel from a template (read only)" },
    { type: "thermowatt-lights-card", name: "Thermowatt lights", description: "Any number of lights with brightness" },
    { type: "thermowatt-home-page", name: "Thermowatt Home page", description: "The whole everyday Home page, fitted to a tablet in landscape" }
  );
}

/* ================================================================================================
 * Device energy: <thermowatt-device-energy-card>
 *
 * Discovers Tapo (and other configured-platform) devices that expose energy or power sensors through
 * Home Assistant's own device/entity registries (nothing is hardcoded), reads their LONG-TERM STATISTICS
 * (Home Assistant's persistent accounting: survives restarts, counter resets and keeps history), allocates
 * every statistics bucket to the tariff in force WHEN IT WAS CONSUMED, and values it with the rate that
 * applied on that date. Costs are ESTIMATED tariff-valued operating costs, never Aurora charges: no
 * supply charge, no solar credits, no solar/grid attribution.
 * Read-only: it never calls a device service and never polls a device.
 * ============================================================================================== */

export const DEFAULT_TIMEZONE = "Australia/Hobart";
const HOUR_MS = 3600e3;
const SHORT_TERM_MS = 9.5 * 24 * HOUR_MS; // 5-minute statistics are kept for 10 days

/** Calendar parts of an instant in a named time zone (DST aware). weekday: 0 = Monday. */
export function zonedParts(ms, timeZone = DEFAULT_TIMEZONE) {
  const parts = new Intl.DateTimeFormat("en-AU", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    weekday: "short",
  }).formatToParts(new Date(ms));
  const get = (type) => parts.find((p) => p.type === type).value;
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")),
    minute: Number(get("minute")),
    second: Number(get("second")),
    weekday: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(get("weekday")),
  };
}

/** The instant of local midnight on calendar date y-m-d in the zone (handles 23 h and 25 h days). */
export function localMidnight(year, month, day, timeZone = DEFAULT_TIMEZONE) {
  let guess = Date.UTC(year, month - 1, day);
  for (let i = 0; i < 4; i += 1) {
    const p = zonedParts(guess, timeZone);
    const shown = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
    const wanted = Date.UTC(year, month - 1, day);
    guess -= shown - wanted;
  }
  return guess;
}

export function startOfLocalDay(ms, timeZone = DEFAULT_TIMEZONE) {
  const p = zonedParts(ms, timeZone);
  return localMidnight(p.year, p.month, p.day, timeZone);
}

export function startOfLocalMonth(ms, timeZone = DEFAULT_TIMEZONE) {
  const p = zonedParts(ms, timeZone);
  return localMidnight(p.year, p.month, 1, timeZone);
}

/** Start of the local month `delta` months away from the month containing ms. */
export function shiftMonth(ms, delta, timeZone = DEFAULT_TIMEZONE) {
  const p = zonedParts(ms, timeZone);
  const index = p.year * 12 + (p.month - 1) + delta;
  return localMidnight(Math.floor(index / 12), (index % 12) + 1, 1, timeZone);
}

export function shiftDay(ms, delta, timeZone = DEFAULT_TIMEZONE) {
  const p = zonedParts(ms, timeZone);
  const d = new Date(Date.UTC(p.year, p.month - 1, p.day + delta));
  return localMidnight(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(), timeZone);
}

function minutes(text) {
  const [h, m] = String(text).split(":").map(Number);
  return h * 60 + (m || 0);
}

/**
 * Peak / off-peak at an instant. `tariff` mirrors the Thermowatt tariff source
 * (energy_monitoring/entity_map.yaml): { clock: "standard"|"local", utc_offset_hours, peak_windows:
 * [{days:[0..6 Mon..Sun], start:"07:00", end:"10:00"}] }. Everything else is off-peak.
 */
export function tariffAt(ms, tariff, timeZone = DEFAULT_TIMEZONE) {
  let weekday;
  let clock;
  if (tariff.clock === "local") {
    const p = zonedParts(ms, timeZone);
    weekday = p.weekday;
    clock = p.hour * 60 + p.minute;
  } else {
    // fixed-offset clock (Aurora Tariff 93 runs on AEST all year, ignoring daylight saving)
    const shifted = new Date(ms + (tariff.utc_offset_hours ?? 10) * HOUR_MS);
    weekday = (shifted.getUTCDay() + 6) % 7;
    clock = shifted.getUTCHours() * 60 + shifted.getUTCMinutes();
  }
  for (const w of tariff.peak_windows || []) {
    if ((w.days || []).includes(weekday) && clock >= minutes(w.start) && clock < minutes(w.end)) {
      return "peak";
    }
  }
  return "offpeak";
}

/**
 * Reject a rate schedule that could produce nonsense costs: every entry needs finite, non-negative
 * `offpeak` and `peak` prices and an `effective_from` that is a real YYYY-MM-DD date, or null when the date
 * the price started is not confirmed. At most one entry may be undated and dates must be unique.
 */
export function validateRates(rates) {
  if (!Array.isArray(rates) || !rates.length) throw new Error("rates are required");
  const seen = new Set();
  for (const r of rates) {
    for (const key of ["offpeak", "peak"]) {
      const value = r[key];
      if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) || Number(value) < 0) {
        throw new Error(`every rate needs a finite, non-negative ${key} price`);
      }
    }
    const from = r.effective_from;
    if (from !== null && from !== undefined) {
      const text = String(from);
      const valid = /^\d{4}-\d{2}-\d{2}$/.test(text) && !Number.isNaN(Date.parse(`${text}T00:00:00Z`)) && new Date(`${text}T00:00:00Z`).toISOString().slice(0, 10) === text;
      if (!valid) throw new Error(`rate effective_from must be a real YYYY-MM-DD date or null, got ${text}`);
    }
    const key = from === null || from === undefined ? "" : String(from);
    if (seen.has(key)) throw new Error(`duplicate rate effective_from ${key || "(undated)"}`);
    seen.add(key);
  }
}

/**
 * The rates in force at an instant, or null when no rate is configured (cost is then withheld, never
 * zero). `rates` is an append-only schedule: [{effective_from:"2026-07-01", offpeak:0.15, peak:0.20}].
 * An entry applies from its local date until the next dated entry, so adding a new price never recalculates
 * earlier history. `assumed` is true when the price is NOT verified for that date: the entry has no start
 * date (`effective_from: null`) or the date precedes the earliest dated entry. Such costs are valued at the
 * earliest listed price and labelled as assumed, never presented as verified historical costs.
 */
export function ratesAt(ms, rates, timeZone = DEFAULT_TIMEZONE) {
  if (!Array.isArray(rates) || !rates.length) return null;
  const p = zonedParts(ms, timeZone);
  const day = `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
  const dateOf = (r) => (r.effective_from === null || r.effective_from === undefined ? "" : String(r.effective_from));
  const ordered = [...rates].sort((a, b) => dateOf(a).localeCompare(dateOf(b)));
  let chosen = null;
  for (const r of ordered) if (dateOf(r) === "" || dateOf(r) <= day) chosen = r;
  if (!chosen) return { ...ordered[0], assumed: true }; // before the earliest dated price
  return { ...chosen, assumed: dateOf(chosen) === "" };
}

const ENERGY_UNITS = { kwh: 1, wh: 0.001, mwh: 1000 };
const POWER_UNITS = { w: 0.001, kw: 1, mw: 1000 };

/**
 * What an energy counter is: `lifetime` (never resets), `month` (resets monthly), `day` (resets daily),
 * `skip` (a finished past period such as yesterday: never a source) or `other`.
 */
export function counterKind(entityId, entry, state) {
  const key = String((entry && (entry.translation_key || entry.tk)) || "").toLowerCase();
  // the trailing words of the entity ID describe the counter; a device NAME earlier in the ID must not
  const tail = String(entityId).split(".").pop().toLowerCase().split("_").slice(-3).join("_");
  const text = `${tail} ${key}`;
  if (/yesterday|last_(week|month|year)|previous|week|year|annual/.test(text)) return "skip";
  if (key === "total_consumption") return "lifetime";
  if (/month/.test(text)) return "month";
  if (/today|daily/.test(text)) return "day";
  if (/\b(total|lifetime|cumulative)\b|_total|total_/.test(text)) return "lifetime";
  return "other";
}

/**
 * Rank a cumulative counter as the one statistics source for its device (higher = better). A lifetime counter
 * is best; a device that only has resetting counters uses its monthly one (fewest resets), then its daily one.
 * Home Assistant's statistics turn each reset into a new cycle, so the `change` of any of them is the energy
 * used; the other counters are never added on top (one source per device) and only serve as a cross-check.
 */
export function energyScore(entityId, entry, state) {
  const key = String((entry && (entry.translation_key || entry.tk)) || "").toLowerCase();
  const kind = counterKind(entityId, entry, state);
  if (kind === "lifetime") return key === "total_consumption" ? 100 : 80;
  if (kind === "month") return 30;
  if (kind === "day") return 20;
  return 50;
}

/**
 * Find the devices to monitor from Home Assistant's registries. One source per DEVICE (so a device's
 * today / month / lifetime counters are never added together): the best cumulative energy counter, else
 * its measured power (energy then estimated by integrating mean power over time).
 */
export function discoverDevices(hass, config = {}) {
  const platforms = (config.platforms || ["tplink", "tapo"]).map(String);
  const exclude = new Set((config.exclude || []).map((x) => String(x).toLowerCase()));
  const only = new Set((config.include_only || []).map((x) => String(x).toLowerCase()));
  const label = config.exclude_label || "";
  const byDevice = new Map();
  const monitoredPlatform = new Set();
  for (const [entityId, entry] of Object.entries(hass.entities || {})) {
    const platform = entry.platform || entry.pl;
    if (!platforms.includes(platform)) continue;
    const deviceId = entry.device_id || entry.di;
    if (!deviceId || entry.hidden || entry.hb) continue;
    monitoredPlatform.add(deviceId);
    const state = (hass.states || {})[entityId];
    if (!state) continue;
    const attrs = state.attributes || {};
    const unit = String(attrs.unit_of_measurement || "").toLowerCase();
    const group = byDevice.get(deviceId) || { energy: [], power: [], labels: new Set(), entities: [], native: {} };
    byDevice.set(deviceId, group);
    group.entities.push(entityId);
    for (const l of entry.labels || entry.lb || []) group.labels.add(l);
    if (attrs.device_class === "energy" && Object.hasOwn(ENERGY_UNITS, unit) && ["total", "total_increasing"].includes(attrs.state_class)) {
      const kind = counterKind(entityId, entry, state);
      if (kind === "skip") continue; // yesterday's figure is a finished period, never a source
      if (kind === "day" || kind === "month") group.native[kind] = { entityId, factor: ENERGY_UNITS[unit] };
      group.energy.push({ entityId, factor: ENERGY_UNITS[unit], score: energyScore(entityId, entry, state) });
    } else if (attrs.device_class === "power" && Object.hasOwn(POWER_UNITS, unit)) {
      group.power.push({ entityId, factor: POWER_UNITS[unit] });
    }
  }
  const devices = [];
  let withoutMonitoring = 0;
  for (const deviceId of monitoredPlatform) {
    const group = byDevice.get(deviceId) || { energy: [], power: [], labels: new Set(), entities: [], native: {} };
    const device = (hass.devices || {})[deviceId] || {};
    const name = device.name_by_user || device.name || (group.entities[0] || deviceId);
    const keys = [name, ...group.entities].map((x) => String(x).toLowerCase());
    if (label && group.labels.has(label)) continue;
    if (keys.some((k) => exclude.has(k))) continue;
    if (only.size && !keys.some((k) => only.has(k))) continue;
    const energy = [...group.energy].sort((a, b) => b.score - a.score || a.entityId.localeCompare(b.entityId))[0];
    const power = [...group.power].sort((a, b) => a.entityId.localeCompare(b.entityId))[0];
    const live = power ? Number(((hass.states || {})[power.entityId] || {}).state) * power.factor : NaN;
    const powerKw = Number.isFinite(live) && live >= 0 ? live : null;
    if (energy) {
      devices.push({ deviceId, name, source: { kind: "energy", entityId: energy.entityId, factor: energy.factor }, estimated: false, native: group.native, powerKw });
    } else if (power) {
      devices.push({ deviceId, name, source: { kind: "power", entityId: power.entityId, factor: power.factor }, estimated: true, native: group.native, powerKw });
    } else {
      withoutMonitoring += 1; // no energy capability: never shown as zero consumption
    }
  }
  devices.sort((a, b) => a.name.localeCompare(b.name));
  return { devices, withoutMonitoring };
}

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

function toMs(v) {
  if (typeof v === "number") return v < 1e11 ? v * 1000 : v;
  return Date.parse(v);
}

/**
 * Turn statistics rows into kWh buckets. Energy sources use `change`; power sources integrate the mean
 * power over the bucket (an ESTIMATE). Rows without a number are skipped: missing data is never zero.
 */
export function toBuckets(rows, source) {
  const out = [];
  for (const row of rows || []) {
    const start = toMs(row.start);
    const end = toMs(row.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
    if (source.kind === "energy") {
      const change = num(row.change);
      if (change === null || change < 0) continue;
      out.push({ start, end, kwh: change * source.factor });
    } else {
      const mean = num(row.mean);
      if (mean === null || mean < 0) continue;
      out.push({ start, end, kwh: mean * source.factor * ((end - start) / HOUR_MS) });
    }
  }
  return out;
}

/**
 * Combine whole-hour statistics with 5-minute statistics without counting any hour twice: a 5-minute bucket
 * is used only for an hour that has no hourly row (the hour that has just ended or is still running).
 */
export function mergeBuckets(hourly, fine) {
  const covered = new Set(hourly.map((b) => Math.floor(b.start / HOUR_MS) * HOUR_MS));
  return [...hourly, ...fine.filter((b) => !covered.has(Math.floor(b.start / HOUR_MS) * HOUR_MS))];
}

/**
 * How completely the statistics cover the COMPLETED hours of [from, to) (the running hour is never expected).
 * An hour counts as recorded when it has an hourly row or all twelve 5-minute rows. `leading` = hours before
 * the first recorded one (monitoring began partway), `missing` = hours without statistics after that (a gap).
 * A recorded zero is data; an hour with no row is NOT zero.
 */
export function coverage(buckets, from, to, now) {
  const hours = new Map();
  for (const b of buckets) {
    const h = Math.floor(b.start / HOUR_MS) * HOUR_MS;
    const entry = hours.get(h) || { whole: false, fine: 0 };
    if (b.end - b.start >= HOUR_MS) entry.whole = true;
    else entry.fine += 1;
    hours.set(h, entry);
  }
  const end = Math.min(to, Math.floor(now / HOUR_MS) * HOUR_MS);
  const result = { expected: 0, present: 0, leading: 0, missing: 0, firstPresent: null };
  for (let h = Math.ceil(from / HOUR_MS) * HOUR_MS; h < end; h += HOUR_MS) {
    result.expected += 1;
    const entry = hours.get(h);
    if (entry && (entry.whole || entry.fine >= 12)) {
      result.present += 1;
      if (result.firstPresent === null) result.firstPresent = h;
    } else if (result.firstPresent === null) {
      result.leading += 1;
    } else {
      result.missing += 1;
    }
  }
  return result;
}

/**
 * The completed hours of [from, to) that have NO statistics, as contiguous runs {start, end, hours} (hours before the
 * first recorded one included). Nothing is filled in: this only reports where Home Assistant wrote no row.
 */
export function missingRuns(buckets, from, to, now) {
  const present = new Set();
  const hours = new Map();
  for (const b of buckets) {
    const h = Math.floor(b.start / HOUR_MS) * HOUR_MS;
    const entry = hours.get(h) || { whole: false, fine: 0 };
    if (b.end - b.start >= HOUR_MS) entry.whole = true;
    else entry.fine += 1;
    hours.set(h, entry);
  }
  for (const [h, entry] of hours) if (entry.whole || entry.fine >= 12) present.add(h);
  const end = Math.min(to, Math.floor(now / HOUR_MS) * HOUR_MS);
  const runs = [];
  for (let h = Math.ceil(from / HOUR_MS) * HOUR_MS; h < end; h += HOUR_MS) {
    if (present.has(h)) continue;
    const last = runs[runs.length - 1];
    if (last && last.end === h) {
      last.end = h + HOUR_MS;
      last.hours += 1;
    } else {
      runs.push({ start: h, end: h + HOUR_MS, hours: 1 });
    }
  }
  return runs;
}

/** Plain-English listing of gap runs. `overnight` = every missing hour starts between 18:00 and 07:00 local time. */
export function describeGaps(runs, timeZone = DEFAULT_TIMEZONE, limit = 10) {
  const when = (ms) => new Date(ms).toLocaleString("en-AU", { timeZone, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  let total = 0;
  let overnight = runs.length > 0;
  for (const run of runs) {
    total += run.hours;
    for (let h = run.start; h < run.end; h += HOUR_MS) {
      const local = zonedParts(h, timeZone).hour;
      if (local >= 7 && local < 18) overnight = false;
    }
  }
  const shown = runs.slice(0, limit).map((r) => `${when(r.start)} to ${when(r.end)} (${r.hours} h)`);
  if (runs.length > limit) shown.push(`and ${runs.length - limit} more`);
  return { total, overnight, lines: shown };
}

/** Sum buckets in [from, to) into energy and tariff-valued cost, each allocated at its own start time. */
export function accumulate(buckets, { from, to, tariff, rates, timeZone = DEFAULT_TIMEZONE }) {
  const result = { kwh: 0, offKwh: 0, peakKwh: 0, offCost: 0, peakCost: 0, cost: 0, count: 0, firstStart: null, assumedKwh: 0, unpricedKwh: 0 };
  for (const b of buckets) {
    if (b.start < from || b.start >= to) continue;
    const period = tariffAt(b.start, tariff, timeZone);
    const rate = ratesAt(b.start, rates, timeZone);
    result.count += 1;
    result.firstStart = result.firstStart === null ? b.start : Math.min(result.firstStart, b.start);
    result.kwh += b.kwh;
    if (period === "peak") result.peakKwh += b.kwh;
    else result.offKwh += b.kwh;
    if (!rate) {
      result.unpricedKwh += b.kwh;
      continue;
    }
    if (rate.assumed) result.assumedKwh += b.kwh;
    if (period === "peak") result.peakCost += b.kwh * rate.peak;
    else result.offCost += b.kwh * rate.offpeak;
  }
  if (result.unpricedKwh > 0) {
    result.offCost = null; // no rate configured: cost withheld, never zero
    result.peakCost = null;
    result.cost = null;
  } else {
    result.cost = result.offCost + result.peakCost;
  }
  result.assumed = result.assumedKwh > 0;
  return result.count ? result : null; // null = no data (never zero)
}

/** Combined totals over device rows; devices without data are counted, not treated as zero. */
export function combine(rows) {
  const total = { kwh: 0, offCost: 0, peakCost: 0, cost: 0, devices: 0, missing: 0, estimated: false, assumed: false, incomplete: false };
  for (const row of rows) {
    if (!row.data) {
      total.missing += 1;
      continue;
    }
    total.devices += 1;
    total.kwh += row.data.kwh;
    if (row.data.cost === null || total.cost === null) {
      total.offCost = total.peakCost = total.cost = null;
    } else {
      total.offCost += row.data.offCost;
      total.peakCost += row.data.peakCost;
      total.cost += row.data.cost;
    }
    if (row.estimated) total.estimated = true;
    if (row.data.assumed) total.assumed = true;
    if (row.partialFrom || row.missingHours) total.incomplete = true;
  }
  if (total.missing && total.devices) total.incomplete = true;
  return total.devices ? total : null;
}

/** Sum bucket energy whose start is in [from, to); null when there is no bucket (never zero). */
export function sumKwh(buckets, from, to) {
  let kwh = 0;
  let count = 0;
  for (const b of buckets || []) {
    if (b.start >= from && b.start < to) {
      kwh += b.kwh;
      count += 1;
    }
  }
  return count ? { kwh, count } : null;
}

export const COUNTER_RESOLUTION_KWH = 0.1; // GoodWe lifetime and daily counters step in 0.1 kWh
const BALANCE_TOLERANCE_KWH = 3 * COUNTER_RESOLUTION_KWH; // three counters are combined
const COMPILE_LAG_MS = 10 * 60e3; // hourly statistics are compiled a few minutes after the hour

/**
 * Whole-house energy balance for a battery-free installation over [from, to), from the SAME complete hours of
 * every source: solar generation G, grid import I, grid export E (long-term statistics) and the individually
 * monitored devices M. Solar used S = G - E; household H = G + I - E; unmeasured U = H - M; self-consumption
 * S / G; independence S / H; monitored share M / H.
 * - Only completed hours are used (the running hour is excluded), so latency differences between sources cannot
 *   distort the comparison; a source with a missing hour withholds the balance.
 * - Differences within the counters' resolution are shown as rounded with a note; larger inconsistencies
 *   (export above generation, monitored above household) are WITHHELD with the reason, never clamped.
 * - Incomplete device statistics make M a lower bound and U an upper bound (never a confirmed figure).
 */
export function energyBalance({ sources, devices, from, to, now, battery, unusableDevices = 0, timeZone = DEFAULT_TIMEZONE }) {
  // the newest hour is only trusted once Home Assistant has had time to compile its hourly row
  const end = Math.min(to, Math.floor((now - COMPILE_LAG_MS) / HOUR_MS) * HOUR_MS);
  const base = { from, end, notes: [] };
  const withheld = (reason) => ({ ...base, status: "withheld", reason });
  if (battery !== false) {
    return withheld("a battery is not confirmed absent, so household energy cannot be derived from generation, import and export");
  }
  if (end <= from) return { ...base, status: "pending", reason: "no complete hour in this period yet" };
  const labels = { solar: "solar generation", import: "grid import", export: "grid export" };
  const values = {};
  let start = from;
  const lateSources = [];
  for (const key of ["solar", "import", "export"]) {
    const src = (sources || {})[key];
    if (!src || !src.buckets) return withheld(`${labels[key]}: ${(src && src.reason) || "not configured"}`);
    if (!sumKwh(src.buckets, from, end)) return withheld(`${labels[key]} has no statistics in this period`);
    const cov = coverage(src.buckets, from, end, end);
    if (cov.firstPresent === null) return withheld(`${labels[key]} has no complete hour of statistics in this period`);
    if (cov.leading > 0) {
      lateSources.push(labels[key]);
      start = Math.max(start, cov.firstPresent); // statistics begin part-way through: use the window every source covers
    }
  }
  for (const key of ["solar", "import", "export"]) {
    const src = sources[key];
    const total = sumKwh(src.buckets, start, end);
    const cov = coverage(src.buckets, start, end, end);
    if (!total || cov.leading || cov.missing) {
      return {
        ...withheld(`${labels[key]} statistics are incomplete (${cov.leading + cov.missing} h without data)`),
        gaps: { source: labels[key], runs: missingRuns(src.buckets, start, end, end) },
      };
    }
    values[key] = total.kwh;
  }
  base.requestedFrom = from;
  base.from = start;
  base.partial = start > from;
  if (base.partial) {
    const when = new Date(start).toLocaleString("en-AU", { timeZone, day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    base.notes.push(`The ${lateSources.join(" and ")} statistics start part-way through the period, so this balance covers ${when} onwards.`);
  }
  const G = values.solar;
  const I = values.import;
  const E = values.export;
  const tol = BALANCE_TOLERANCE_KWH;
  if (E > G + tol) {
    return withheld(`grid export (${E.toFixed(2)} kWh) exceeds solar generation (${G.toFixed(2)} kWh) by more than the counter resolution`);
  }
  let S = G - E;
  if (S < 0) {
    base.notes.push(`Export exceeded generation by ${(-S).toFixed(2)} kWh, within counter resolution: solar used is shown as 0.`);
    S = 0;
  }
  const H = S + I;
  let M = null;
  let incomplete = false;
  let estimated = false;
  let withData = 0;
  if (unusableDevices > 0) incomplete = true; // monitored devices whose statistics cannot be used
  for (const d of devices || []) {
    const total = sumKwh(d.buckets, start, end);
    if (!total) {
      incomplete = true;
      continue;
    }
    const cov = coverage(d.buckets, start, end, end);
    if (cov.leading || cov.missing) incomplete = true;
    if (d.estimated) estimated = true;
    withData += 1;
    M = (M === null ? 0 : M) + total.kwh;
  }
  const result = {
    ...base,
    status: "ok",
    G,
    I,
    E,
    S,
    H,
    M,
    U: null,
    uStatus: "none",
    deviceIncomplete: incomplete,
    estimated,
    devicesWithData: withData,
    devicesTotal: (devices || []).length + unusableDevices,
    selfPct: G >= 1 ? (S / G) * 100 : null,
    indepPct: H >= 0.5 ? (S / H) * 100 : null,
    monPct: null,
  };
  if (M !== null) {
    const U = H - M;
    const allowance = Math.max(tol, 0.05 * H);
    if (U < -allowance) {
      result.uStatus = "withheld";
      result.uReason = `monitored device energy (${M.toFixed(2)} kWh) exceeds household consumption (${H.toFixed(2)} kWh) by more than measurement error: unmeasured consumption is withheld (check for devices on the same circuit or a wrong source)`;
    } else {
      if (U < 0) result.notes.push(`Monitored devices exceed household consumption by ${(-U).toFixed(2)} kWh, within measurement error: unmeasured is shown as 0.`);
      result.U = Math.max(U, 0);
      result.uStatus = incomplete ? "upper_bound" : "confirmed";
      if (H >= 0.5) result.monPct = (M / H) * 100;
    }
  }
  return result;
}

/** The devices' own live daily and monthly counters and live power, summed (a cross-check, never a source). */
export function nativeTotals(devices, hass) {
  const live = (n) => {
    const state = n && (hass.states || {})[n.entityId];
    const value = state ? Number(state.state) : NaN;
    return Number.isFinite(value) && value >= 0 ? value * n.factor : null;
  };
  const sum = (kind) => {
    let total = 0;
    let count = 0;
    for (const d of devices) {
      const v = live((d.native || {})[kind]);
      if (v !== null) {
        total += v;
        count += 1;
      }
    }
    return count ? { kwh: total, count } : null;
  };
  let power = 0;
  let powerCount = 0;
  for (const d of devices) {
    if (d.powerKw !== null && d.powerKw !== undefined) {
      power += d.powerKw;
      powerCount += 1;
    }
  }
  const day = sum("day");
  const month = sum("month");
  return { dailyKwh: day && day.kwh, dailyCount: day ? day.count : 0, monthlyKwh: month && month.kwh, monthlyCount: month ? month.count : 0, powerKw: powerCount ? power : null };
}

/** Totals of the cross-check pairs only (the same devices and the same window on both sides). */
export function crossTotals(rows) {
  let counter = 0;
  let stats = 0;
  let count = 0;
  let differing = 0;
  for (const row of rows) {
    if (!row.check) continue;
    counter += row.check.counter;
    stats += row.check.stats;
    count += 1;
    if (row.check.differs) differing += 1;
  }
  return count ? { counter, stats, count, differing } : null;
}

/** Compare a device's statistics-derived energy with the device's own counter for the same period. */
export function crossCheck(statsKwh, native, hass, powerKw) {
  const state = native && (hass.states || {})[native.entityId];
  const value = state ? Number(state.state) : NaN;
  if (!Number.isFinite(value) || value < 0 || statsKwh === null || statsKwh === undefined) return null;
  const counter = value * native.factor;
  // allowance: rounding, 5 %, or about a quarter of an hour at the device's present power (reporting latency)
  const allowance = Math.max(0.05, 0.05 * counter, (powerKw || 0) * 0.25);
  return { counter, stats: statsKwh, differs: Math.abs(counter - statsKwh) > allowance };
}

export const fmtKwh = (v) => (v === null || v === undefined ? "—" : `${v.toFixed(v < 1 ? 3 : 2)} kWh`);
export const fmtMoney = (v, assumed = false) => (v === null || v === undefined ? "—" : `${assumed ? "≈" : ""}$${v.toFixed(2)}`);

export function sortRows(rows, key, direction) {
  const value = (r) => (key === "name" ? r.name.toLowerCase() : r.data ? r.data[key] : null);
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1; // no data always last
    if (y === null) return -1;
    const order = x < y ? -1 : x > y ? 1 : 0;
    return direction === "asc" ? order : -order;
  });
}

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function monthLabel(ms, timeZone = DEFAULT_TIMEZONE) {
  const p = zonedParts(ms, timeZone);
  return `${MONTH_NAMES[p.month - 1]} ${p.year}`;
}

const escapeHtml = (text) =>
  String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const DE_CSS = `
  .toggle{display:flex;gap:6px}
  .toggle button{all:unset;cursor:pointer;font-size:14px;padding:5px 14px;border:1px solid var(--divider-color,#555);border-radius:999px;color:var(--primary-text-color)}
  .toggle button.on{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}
  .toggle button:focus-visible,th button:focus-visible{outline:2px solid var(--primary-color)}
  .scroll{overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:15.5px}
  th{padding:10px 12px;text-align:right;font-size:12.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--secondary-text-color);white-space:nowrap}
  td{padding:11px 12px;text-align:right;white-space:nowrap;color:var(--primary-text-color)}
  th:first-child,td:first-child{text-align:left;white-space:normal;padding-left:2px}
  th button{all:unset;cursor:pointer;font:inherit;letter-spacing:inherit;text-transform:inherit;color:inherit}
  tbody tr{border-top:1px solid var(--divider-color,#444)}
  tr.total td{font-weight:700;border-top:2px solid var(--divider-color,#555);background:color-mix(in srgb,var(--primary-text-color) 5%,transparent)}
  .none{color:var(--secondary-text-color);font-size:14px}
  .est,.part{display:inline-block;font-size:12px;font-weight:500;color:var(--secondary-text-color);border:1px solid var(--divider-color,#666);border-radius:999px;padding:1px 8px;margin-left:6px;white-space:nowrap}
  .kpis3{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px}
  .kbox{padding:14px 16px;border-radius:16px;background:color-mix(in srgb,var(--primary-text-color) 6%,transparent)}
  .kbox .lab{font-size:12.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--secondary-text-color)}
  .kbox .val{font-size:clamp(26px,7.2cqw,42px);font-weight:500;line-height:1.1;margin-top:4px;color:var(--primary-text-color)}
  .kbox .unit{font-size:.4em;color:var(--secondary-text-color);margin-left:.2em}
  .kbox .sub{font-size:14.5px;color:var(--secondary-text-color);margin-top:2px}
  .sankey{display:block;width:100%;max-width:900px;margin:0 auto}
  .sankey text{fill:var(--primary-text-color)}
  .sankey .halo{paint-order:stroke;stroke:var(--card-background-color,#1c1c1c);stroke-width:3px;stroke-linejoin:round}
  .heroes.mini{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
  .heroes.mini .val{font-size:clamp(24px,6.6cqw,36px)}
  .heroes.mini .lab,.heroes.mini .cap{font-size:13px;line-height:1.25}
  .legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:14px;color:var(--secondary-text-color)}
  .legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
  .bars{display:block;width:100%;max-width:640px;margin:0 auto}
  .bars text{fill:var(--secondary-text-color)}.bars .v{fill:var(--primary-text-color)}
  details summary{cursor:pointer;font-size:14px;color:var(--secondary-text-color)}
  details p{margin:8px 0 0}
  h3{margin:6px 0 -4px;font-size:15px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary-text-color)}
  @container (max-width:520px){
    .c-off,.c-peak{display:none}
    table{font-size:14.5px}
    td,th{padding-left:8px;padding-right:8px}
  }
`;

const STYLE = UI_CSS + DE_CSS;

function tableHtml(id, rows, total, sort, partialNote) {
  const arrow = (key) => (sort.key === key ? (sort.direction === "asc" ? " ▲" : " ▼") : "");
  const head = [
    ["name", "Device", ""],
    ["kwh", "kWh", ""],
    ["offCost", "Off-peak $", "c-off"],
    ["peakCost", "Peak $", "c-peak"],
    ["cost", "Total $", ""],
  ]
    .map(([key, text, klass]) => `<th class="${klass}"><button data-table="${id}" data-sort="${key}">${text}${arrow(key)}</button></th>`)
    .join("");
  const body = sortRows(rows, sort.key, sort.direction)
    .map(
      (r) =>
        `<tr><td>${escapeHtml(r.name)}${r.estimated ? ' <span class="est" title="Estimated from measured power">est.</span>' : ""}${r.partialFrom ? ` <span class="part" title="Statistics for this period start later than the period">from ${escapeHtml(r.partialFrom)}</span>` : ""}${r.missingHours ? ` <span class="part" title="Hours inside this period with no recorded statistics (not counted as zero)">${r.missingHours} h missing</span>` : ""}${r.check && r.check.differs ? ` <span class="part" title="Statistics say ${r.check.stats.toFixed(3)} kWh but the device's own counter says ${r.check.counter.toFixed(3)} kWh">≠ device counter</span>` : ""}</td>` +
        (r.data
          ? `<td>${fmtKwh(r.data.kwh)}</td><td class="c-off">${fmtMoney(r.data.offCost, r.data.assumed)}</td><td class="c-peak">${fmtMoney(r.data.peakCost, r.data.assumed)}</td><td>${fmtMoney(r.data.cost, r.data.assumed)}</td>`
          : '<td colspan="4" class="none">no statistics (not zero)</td>') +
        "</tr>"
    )
    .join("");
  const foot = total
    ? `<tr class="total"><td>Total (${total.devices} device${total.devices === 1 ? "" : "s"}${total.missing ? `, ${total.missing} without data` : ""})${total.incomplete ? ' <span class="part" title="At least one device has missing or late-starting statistics in this period">incomplete</span>' : ""}</td><td>${fmtKwh(total.kwh)}</td><td class="c-off">${fmtMoney(total.offCost, total.assumed)}</td><td class="c-peak">${fmtMoney(total.peakCost, total.assumed)}</td><td>${fmtMoney(total.cost, total.assumed)}</td></tr>`
    : '<tr class="total"><td colspan="5" class="none">No data yet</td></tr>';
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div>${partialNote ? `<p class="note">${partialNote}</p>` : ""}`;
}

/** Bar chart (dependency-free). `narrow` uses a taller, smaller canvas so the text stays readable on a phone. */
function barsSvg(items, key, unit, narrow = false) {
  if (!items.length) return "";
  const W = narrow ? 340 : 560;
  const H = narrow ? 210 : 220;
  const base = H - 30;
  const room = base - 34;
  const max = Math.max(...items.map((i) => i[key] || 0), 1e-9);
  const slot = W / items.length;
  const bw = Math.min(64, slot * 0.64);
  const bars = items
    .map((item, index) => {
      const value = item[key];
      const h = value ? Math.max(3, (value / max) * room) : 0;
      const x = index * slot + (slot - bw) / 2;
      const label = value === null || value === undefined ? "—" : unit === "$" ? fmtMoney(value, item.assumed) : value.toFixed(value < 10 ? 1 : 0);
      return (
        `<g><rect x="${x.toFixed(1)}" y="${(base - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="4" fill="var(--primary-color,#03a9f4)" opacity="${item.partial ? 0.5 : 0.95}"/>` +
        `<text class="v" x="${(x + bw / 2).toFixed(1)}" y="${(base - h - 8).toFixed(1)}" text-anchor="middle" font-size="${narrow ? 13 : 14}" font-weight="600">${escapeHtml(label)}</text>` +
        `<text x="${(x + bw / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="${narrow ? 13 : 14}">${escapeHtml(item.label)}</text></g>`
      );
    })
    .join("");
  return `<svg class="bars" viewBox="0 0 ${W} ${H}" role="img" aria-label="Bar chart">${bars}</svg>`;
}

/**
 * A dependency-free Sankey-style diagram of one balance: Solar -> Household / Export, Grid import -> Household,
 * Household -> Monitored devices / Unmeasured. Widths are proportional to kWh. Only drawn for a valid balance.
 * `compact` (phones) drops the in-diagram labels, which would be unreadable, and adds a legend instead.
 */
export function sankeySvg(b, { compact = false } = {}) {
  if (!b || b.status !== "ok") return "";
  const W = compact ? 360 : 760;
  const Ht = compact ? 250 : 300;
  const nodeW = compact ? 12 : 14;
  const gap = 14;
  const pad = 10;
  const left = compact ? 12 : 150;
  const right = compact ? 12 : 214;
  const x0 = left;
  const x2 = W - right - nodeW;
  const x1 = (x0 + x2) / 2;
  const total = b.G + b.I;
  if (!(total > 0)) return "";
  const k = (Ht - 2 * pad - 2 * gap) / total;
  const itemised = b.uStatus === "confirmed" || b.uStatus === "upper_bound";
  const kwh = (v) => `${v.toFixed(v < 10 ? 2 : 1)} kWh`;
  const colors = {
    solar: "var(--energy-solar-color,#ff9800)",
    grid: "var(--energy-grid-consumption-color,#488fc2)",
    export: "var(--energy-grid-return-color,#8353d1)",
    house: "var(--primary-color,#03a9f4)",
    devices: "var(--energy-battery-out-color,#4caf50)",
    other: "var(--disabled-text-color,#9e9e9e)",
  };
  const nodes = {};
  const place = (id, x, y, value, color, label, anchor) => {
    nodes[id] = { id, x, y, h: Math.max(value * k, 2), value, color, label, anchor, out: 0, inn: 0 };
  };
  const y0 = pad;
  place("solar", x0, y0, b.G, colors.solar, `Solar ${kwh(b.G)}`, "end");
  place("import", x0, y0 + b.G * k + gap, b.I, colors.grid, `Import ${kwh(b.I)}`, "end");
  place("house", x1, y0 + b.E * k, b.H, colors.house, `Household ${kwh(b.H)}`, "mid");
  place("export", x2, y0, b.E, colors.export, `Export ${kwh(b.E)}`, "start");
  if (itemised) {
    const top = y0 + b.E * k + gap;
    const mark = b.deviceIncomplete ? "≥ " : b.estimated ? "≈ " : "";
    place("devices", x2, top, b.M, colors.devices, `Devices ${mark}${kwh(b.M)}`, "start");
    place("other", x2, top + b.M * k + gap, b.U, colors.other, `Unmeasured ${b.uStatus === "upper_bound" ? "≤ " : ""}${kwh(b.U)}`, "start");
  }
  const links = [["solar", "export", b.E, colors.solar], ["solar", "house", b.S, colors.solar], ["import", "house", b.I, colors.grid]];
  if (itemised) links.push(["house", "devices", b.M, colors.house], ["house", "other", b.U, colors.house]);
  let paths = "";
  for (const [from, to, value, color] of links) {
    if (!(value > 0)) continue;
    const a = nodes[from];
    const z = nodes[to];
    const thick = Math.max(Math.min(value * k, a.h - a.out, z.h - z.inn), 0.5);
    const ya = a.y + a.out;
    const yz = z.y + z.inn;
    a.out += thick;
    z.inn += thick;
    const xa = a.x + nodeW;
    const xm = (xa + z.x) / 2;
    paths += `<path d="M${xa} ${ya} C${xm} ${ya} ${xm} ${yz} ${z.x} ${yz} L${z.x} ${yz + thick} C${xm} ${yz + thick} ${xm} ${ya + thick} ${xa} ${ya + thick} Z" fill="${color}" opacity="0.38"/>`;
  }
  const fs = compact ? 12 : 16;
  let drawn = "";
  for (const node of Object.values(nodes)) {
    if (!(node.value > 0)) continue;
    const fill = node.id === "other" && b.uStatus === "upper_bound" ? 0.55 : 1;
    drawn += `<rect x="${node.x}" y="${node.y}" width="${nodeW}" height="${node.h}" rx="3" fill="${node.color}" opacity="${fill}"/>`;
    if (compact) continue;
    if (node.id === "house") {
      const ty = node.y + node.h / 2;
      drawn += `<text x="${node.x + nodeW + 7}" y="${ty - 3}" font-size="${fs}" font-weight="600" class="halo">Household</text><text x="${node.x + nodeW + 7}" y="${ty + 15}" font-size="${fs}" class="halo">${escapeHtml(kwh(node.value))}</text>`;
      continue;
    }
    const tx = node.anchor === "end" ? node.x - 8 : node.x + nodeW + 8;
    const ty = node.y + Math.min(node.h / 2, 16) + 5;
    drawn += `<text x="${tx}" y="${ty}" text-anchor="${node.anchor === "end" ? "end" : "start"}" font-size="${fs}" class="halo">${escapeHtml(node.label)}</text>`;
  }
  const summary = `Energy balance: solar ${kwh(b.G)}, grid import ${kwh(b.I)}, grid export ${kwh(b.E)}, household ${kwh(b.H)}`;
  const legend = compact
    ? `<div class="legend">${[["Solar", colors.solar], ["Import", colors.grid], ["Export", colors.export], ["Household", colors.house], ...(itemised ? [["Devices", colors.devices], ["Unmeasured", colors.other]] : [])]
        .map(([name, color]) => `<span><i style="background:${color}"></i>${name}</span>`)
        .join("")}</div>`
    : "";
  return `<svg class="sankey" viewBox="0 0 ${W} ${Ht}" role="img" aria-label="${escapeHtml(summary)}">${paths}${drawn}</svg>${legend}`;
}

const pctText = (v, prefix = "") => (v === null || v === undefined ? "—" : `${prefix}${v.toFixed(0)}%`);

function balanceCell(b, row) {
  if (b.status !== "ok") return `<td class="none" title="${escapeHtml(b.reason || "")}">${b.status === "pending" ? "collecting" : "withheld"}</td>`;
  const lower = b.deviceIncomplete ? "≥ " : b.estimated ? "≈ " : "";
  switch (row) {
    case "G":
      return `<td>${fmtKwh(b.G)}</td>`;
    case "I":
      return `<td>${fmtKwh(b.I)}</td>`;
    case "E":
      return `<td>${fmtKwh(b.E)}</td>`;
    case "S":
      return `<td>${fmtKwh(b.S)}</td>`;
    case "H":
      return `<td>${fmtKwh(b.H)}</td>`;
    case "M":
      return b.M === null ? '<td class="none">no device data</td>' : `<td>${lower}${fmtKwh(b.M)}</td>`;
    case "U":
      if (b.uStatus === "withheld") return `<td class="none" title="${escapeHtml(b.uReason)}">withheld</td>`;
      if (b.U === null) return '<td class="none">—</td>';
      return `<td>${b.uStatus === "upper_bound" ? "≤ " : b.estimated ? "≈ " : ""}${fmtKwh(b.U)}</td>`;
    case "self":
      return `<td${b.selfPct === null ? ' class="none" title="needs at least 1 kWh generated"' : ""}>${pctText(b.selfPct)}</td>`;
    case "indep":
      return `<td${b.indepPct === null ? ' class="none" title="needs at least 0.5 kWh of household consumption"' : ""}>${pctText(b.indepPct)}</td>`;
    default:
      return b.uStatus === "withheld" ? `<td class="none" title="${escapeHtml(b.uReason)}">withheld</td>` : `<td>${pctText(b.monPct, lower)}</td>`;
  }
}

/** The three large numbers above the diagram, for the period being shown. */
function balanceHeroes(b, mini = false) {
  if (!b || b.status !== "ok") return "";
  const num = (v, digits = 1) => (v === null || v === undefined ? "—" : v.toFixed(digits));
  const lower = b.deviceIncomplete ? "≥ " : b.estimated ? "≈ " : "";
  const unmeasured =
    b.uStatus === "withheld" || b.U === null
      ? { value: null, caption: b.uStatus === "withheld" ? "withheld, see below" : "no device data" }
      : { value: `${b.uStatus === "upper_bound" ? "≤ " : b.estimated ? "≈ " : ""}${num(b.U)}`, caption: b.monPct === null ? "" : `${lower}${b.monPct.toFixed(0)}% of the household is monitored` };
  return (
    `<div class="heroes multi${mini ? " mini" : ""}">` +
    `<div class="hero t-info"><div class="lab">Household used</div><div class="val">${num(b.H)}<span class="unit">kWh</span></div><div class="cap">${b.indepPct === null ? "" : `${b.indepPct.toFixed(0)}% of it from solar`}</div></div>` +
    `<div class="hero t-ok"><div class="lab">Solar used directly</div><div class="val">${num(b.S)}<span class="unit">kWh</span></div><div class="cap">${b.selfPct === null ? "" : `${b.selfPct.toFixed(0)}% of generation`}</div></div>` +
    `<div class="hero t-idle"><div class="lab">Unmeasured</div><div class="val">${unmeasured.value === null ? "—" : unmeasured.value}<span class="unit">${unmeasured.value === null ? "" : "kWh"}</span></div><div class="cap">${escapeHtml(unmeasured.caption)}</div></div>` +
    "</div>"
  );
}

/** The balance without the table: three large numbers and the diagram (for the Energy page). */
function balanceMiniHtml(s, view) {
  const head = (toggle = "") => `<div class="head">${iconHtml("mdi:scale-balance")}<div class="title">Whole-house balance</div>${toggle}</div>`;
  if (s.balanceReason) return head() + `<p class="note">Not available: ${escapeHtml(s.balanceReason)}.</p>`;
  const shown = view === "month" ? s.balance.month : s.balance.day;
  const toggle = `<div class="toggle" role="group" aria-label="Balance period"><button data-balance="day" class="${view === "month" ? "" : "on"}">Today</button><button data-balance="month" class="${view === "month" ? "on" : ""}">${escapeHtml(monthLabel(s.generatedAt || Date.now(), s.tz).split(" ")[0])}</button></div>`;
  let html = head(toggle) + balanceHeroes(shown, true);
  const drawing = sankeySvg(shown, { compact: true });
  if (drawing) html += drawing;
  else if (shown.status === "ok") html += '<p class="note">No energy flowed in this period.</p>';
  else html += `<p class="note"><b>${escapeHtml(shown.status === "pending" ? "Collecting: " : "Balance withheld: ")}</b>${escapeHtml(shown.reason)}.</p>`;
  const ended = shown.end > shown.from ? new Date(shown.end).toLocaleTimeString("en-AU", { timeZone: s.tz, hour: "numeric", minute: "2-digit" }) : null;
  html += `<p class="note">Over the same complete hours${ended ? ` (to ${escapeHtml(ended)})` : ""}. Every figure, the table and the cross-check are on the Device energy page.</p>`;
  return html;
}

function balanceHtml(s, view, compact) {
  if (s.balanceReason) return `<div class="head">${iconHtml("mdi:scale-balance")}<div class="title">Whole-house energy balance</div></div><p class="note">Not available: ${escapeHtml(s.balanceReason)}.</p>`;
  const day = s.balance.day;
  const month = s.balance.month;
  const shown = view === "month" ? month : day;
  const endText = (b) => new Date(b.end).toLocaleTimeString("en-AU", { timeZone: s.tz, hour: "numeric", minute: "2-digit" });
  const fromText = (b) => new Date(b.from).toLocaleString("en-AU", { timeZone: s.tz, day: "numeric", month: "short" });
  let html = `<div class="head">${iconHtml("mdi:scale-balance")}<div class="title">Whole-house energy balance</div>`;
  html += `<div class="toggle" role="group" aria-label="Balance period"><button data-balance="day" class="${view === "month" ? "" : "on"}">Today</button><button data-balance="month" class="${view === "month" ? "on" : ""}">${escapeHtml(monthLabel(s.generatedAt || Date.now(), s.tz))}</button></div></div>`;
  html += balanceHeroes(shown);
  const drawing = sankeySvg(shown, { compact });
  if (drawing) html += drawing;
  else if (shown.status === "ok") html += '<p class="note">No energy flowed in this period, so there is nothing to draw.</p>';
  else html += `<p class="note"><b>${escapeHtml(shown.status === "pending" ? "Collecting: " : "Balance withheld: ")}</b>${escapeHtml(shown.reason)}.</p>`;
  const rows = [
    ["G", "Solar generation"],
    ["I", "Grid import"],
    ["E", "Grid export"],
    ["S", "Solar used directly"],
    ["H", "Household consumption"],
    ["M", "Monitored devices"],
    ["U", "Unmeasured consumption"],
    ["self", "Solar self-consumption"],
    ["indep", "Solar independence"],
    ["mon", "Monitored share of household"],
  ];
  html += '<div class="scroll"><table><thead><tr><th>Energy balance</th><th>Today</th><th>Month</th></tr></thead><tbody>';
  for (const [key, text] of rows) html += `<tr><td>${text}</td>${balanceCell(day, key)}${balanceCell(month, key)}</tr>`;
  html += "</tbody></table></div>";
  const ended = day.end > day.from ? endText(day) : null;
  html += `<p class="note">Battery-free balance from the inverter's generation, import and export statistics and the monitored devices, over the same complete hours${ended ? ` (to ${escapeHtml(ended)})` : ""}. Energy only: device costs elsewhere are tariff-valued estimates, not grid spending, and no solar is attributed to individual devices.</p>`;
  for (const [name, b] of [["Today", day], ["Month", month]]) {
    if (b.status === "withheld") html += `<p class="note"><b>${name}:</b> withheld, ${escapeHtml(b.reason)}.</p>`;
    if (b.status === "withheld" && b.gaps && b.gaps.runs.length) {
      const g = describeGaps(b.gaps.runs, s.tz);
      html += `<details class="gaps"><summary>${name}: the ${g.total} hour${g.total === 1 ? "" : "s"} with no ${escapeHtml(b.gaps.source)} statistics</summary><ul>${g.lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ul>` +
        `<p class="note">${g.overnight ? "Every missing hour is overnight, which is typical of an inverter that switches off when there is no sun: while the source is unavailable the recorder writes no row for that hour. " : "Some missing hours fall in daylight, so this is more than an overnight shutdown (a Home Assistant restart, a network drop or a replaced sensor). "}` +
        "Nothing is estimated and no zero is invented. Home Assistant adds the energy a cumulative counter gained across a gap to the first hour after it, so a long period's total normally stays right, but which hours it belongs to is not known; the card therefore withholds the balance instead of assuming the gap was empty.</p></details>";
    }
    else if (b.status === "pending") html += `<p class="note"><b>${name}:</b> collecting, ${escapeHtml(b.reason)}.</p>`;
    else {
      if (b.partial) html += `<p class="note"><b>${name}:</b> covers ${escapeHtml(fromText(b))} onwards: some statistics start later than the period.</p>`;
      for (const note of b.notes) html += `<p class="note"><b>${name}:</b> ${escapeHtml(note)}</p>`;
      if (b.uStatus === "withheld") html += `<p class="note"><b>${name}:</b> ${escapeHtml(b.uReason)}.</p>`;
      if (b.deviceIncomplete) html += `<p class="note"><b>${name}:</b> ${b.devicesWithData} of ${b.devicesTotal} devices have complete statistics, so monitored energy is a lower bound (≥) and unmeasured consumption an upper bound (≤), not a confirmed figure.</p>`;
      if (b.estimated) html += `<p class="note"><b>${name}:</b> includes energy estimated from power (≈).</p>`;
    }
  }
  const cross = s.crossCheck || {};
  const parts = [];
  if (cross.day) parts.push(`today the daily counters of ${cross.day.count} device${cross.day.count === 1 ? "" : "s"} total ${fmtKwh(cross.day.counter)} (statistics: ${fmtKwh(cross.day.stats)})`);
  if (cross.month) parts.push(`this month the monthly counters of ${cross.month.count} device${cross.month.count === 1 ? "" : "s"} total ${fmtKwh(cross.month.counter)} (statistics: ${fmtKwh(cross.month.stats)})`);
  if (parts.length) html += `<p class="note">Cross-check: ${parts.join("; ")}. A device whose statistics disagree with its own counter is marked ≠ device counter. The counters are a check only and are never added to the statistics.</p>`;
  html += '<p class="note">Monitored devices here use complete hours only, so they can be slightly below the Today and month tables, which include the hour in progress.</p>';
  return html;
}

const BaseElement = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

// One load per configuration, shared by every card part on the page (summary, daily, monthly, history).
const SHARED = new Map();

const withTimeout = (promise) =>
  Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error("statistics request timed out")), 60e3))]);

/**
 * Load and value the statistics. Units come from the RECORDER'S statistics metadata (the unit the statistics
 * are stored in), not from the live sensor. Hourly statistics cover the whole history; 5-minute statistics are
 * used only for the last few hours that have no hourly row yet, so no hour is ever counted twice and no
 * retained history is skipped, whatever the recorder's short-term retention is. The whole-house sources
 * (`config.house`) go through the same pipeline, so every balance figure covers the same complete hours.
 */
export async function computeState(hass, c) {
  const found = discoverDevices(hass, c);
  const now = Date.now();
  const tz = c.timezone;
  const dayStart = startOfLocalDay(now, tz);
  const dayEnd = shiftDay(now, 1, tz);
  const monthStart = startOfLocalMonth(now, tz);
  const monthEnd = shiftMonth(now, 1, tz);
  const months = c.history_months ?? 6;
  const historyStart = shiftMonth(now, -months, tz);
  const hourEnd = Math.floor(now / HOUR_MS) * HOUR_MS;
  const fineFrom = hourEnd - 3 * HOUR_MS;

  const house = c.house || null;
  const houseDefs = house ? ["solar", "import", "export"].filter((key) => house[key]) : [];
  const meta = new Map();
  const ids = [...found.devices.map((d) => d.source.entityId), ...houseDefs.map((key) => house[key])];
  if (ids.length) {
    const list = await withTimeout(hass.callWS({ type: "recorder/get_statistics_metadata", statistic_ids: ids }));
    for (const m of Array.isArray(list) ? list : []) meta.set(m.statistic_id, m);
  }
  const devices = [];
  let unsupported = 0;
  for (const d of found.devices) {
    const m = meta.get(d.source.entityId);
    if (!m) {
      devices.push({ ...d, noStatistics: true }); // no statistics recorded yet: shown as "no statistics", not zero
      continue;
    }
    const unit = String(m.statistics_unit_of_measurement || "").toLowerCase();
    const table = d.source.kind === "energy" ? ENERGY_UNITS : POWER_UNITS;
    const capable = d.source.kind === "energy" ? m.has_sum !== false : m.has_mean !== false;
    if (!Object.hasOwn(table, unit) || !capable) {
      unsupported += 1;
      continue;
    }
    devices.push({ ...d, source: { ...d.source, factor: table[unit] } });
  }
  const houseItems = {};
  for (const key of houseDefs) {
    const entityId = house[key];
    const m = meta.get(entityId);
    const unit = m ? String(m.statistics_unit_of_measurement || "").toLowerCase() : "";
    if (!m) houseItems[key] = { reason: `${entityId} has no long-term statistics (it needs a total or total_increasing state class)` };
    else if (!Object.hasOwn(ENERGY_UNITS, unit) || m.has_sum === false) houseItems[key] = { reason: `${entityId} has an unsupported statistics unit or no cumulative statistics` };
    else houseItems[key] = { source: { kind: "energy", entityId, factor: ENERGY_UNITS[unit] } };
  }

  const fetchItems = [
    ...devices.filter((d) => !d.noStatistics).map((d) => ({ id: d.deviceId, source: d.source })),
    ...houseDefs.filter((key) => houseItems[key].source).map((key) => ({ id: `house:${key}`, source: houseItems[key].source })),
  ];
  const buckets = new Map([...devices.map((d) => [d.deviceId, []]), ...houseDefs.map((key) => [`house:${key}`, []])]);
  const query = (queryIds, kind, from, to, period) =>
    queryIds.length
      ? withTimeout(
          hass.callWS({
            type: "recorder/statistics_during_period",
            start_time: new Date(from).toISOString(),
            end_time: new Date(to).toISOString(),
            statistic_ids: queryIds,
            period,
            types: kind === "energy" ? ["change"] : ["mean"],
          })
        )
      : Promise.resolve({});
  for (const kind of ["energy", "power"]) {
    const group = fetchItems.filter((item) => item.source.kind === kind);
    const queryIds = group.map((item) => item.source.entityId);
    const hourly = await query(queryIds, kind, historyStart, hourEnd, "hour");
    const fine = await query(queryIds, kind, fineFrom, now + HOUR_MS, "5minute");
    for (const item of group) {
      const id = item.source.entityId;
      buckets.set(item.id, mergeBuckets(toBuckets((hourly || {})[id], item.source), toBuckets((fine || {})[id], item.source)));
    }
  }

  const ctx = { tariff: c.tariff, rates: c.rates, timeZone: tz };
  const dateLabel = (ms) => new Date(ms).toLocaleString("en-AU", { timeZone: tz, day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const rowsFor = (from, to) =>
    devices.map((d) => {
      const own = buckets.get(d.deviceId);
      const data = accumulate(own, { from, to, ...ctx });
      const cov = coverage(own, from, to, now);
      return {
        deviceId: d.deviceId,
        name: d.name,
        estimated: d.estimated,
        data,
        partialFrom: data && cov.leading > 0 && cov.firstPresent !== null ? dateLabel(cov.firstPresent) : null,
        missingHours: data ? cov.missing : 0,
        check: null,
      };
    });
  const isPartial = (rows, total) => !!total && (total.incomplete || rows.some((r) => r.partialFrom || r.missingHours));
  const daily = rowsFor(dayStart, dayEnd);
  const monthly = rowsFor(monthStart, monthEnd);
  // cross-check each device's statistics against the device's OWN daily / monthly counter (never added together)
  for (const [rows, kind] of [[daily, "day"], [monthly, "month"]]) {
    for (const row of rows) {
      const device = devices.find((d) => d.deviceId === row.deviceId);
      row.check = row.data && device ? crossCheck(row.data.kwh, (device.native || {})[kind], hass, device.powerKw) : null;
    }
  }
  const past = [];
  for (let delta = -1; delta >= -months; delta -= 1) {
    const from = shiftMonth(now, delta, tz);
    const rows = rowsFor(from, shiftMonth(now, delta + 1, tz));
    const total = combine(rows);
    if (total) past.push({ label: monthLabel(from, tz).slice(0, 3), full: monthLabel(from, tz), rows, total, partial: isPartial(rows, total) });
  }
  past.reverse();
  const week = [];
  for (let delta = -6; delta <= 0; delta += 1) {
    const from = shiftDay(now, delta, tz);
    const rows = rowsFor(from, shiftDay(now, delta + 1, tz));
    const total = combine(rows);
    week.push({
      label: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][zonedParts(from, tz).weekday],
      kwh: total ? total.kwh : null,
      cost: total ? total.cost : null,
      partial: isPartial(rows, total),
    });
  }
  const assumed = [daily, monthly, ...past.map((m) => m.rows)].some((rows) => rows.some((r) => r.data && r.data.assumed));

  // whole-house balance over the same complete hours of every source
  const sources = {};
  for (const key of houseDefs) sources[key] = houseItems[key].source ? { buckets: buckets.get(`house:${key}`) } : { reason: houseItems[key].reason };
  const deviceBuckets = devices.map((d) => ({ name: d.name, estimated: d.estimated, buckets: buckets.get(d.deviceId) }));
  const balance = {};
  for (const [name, from, to] of [["day", dayStart, dayEnd], ["month", monthStart, monthEnd]]) {
    balance[name] = energyBalance({ sources, devices: deviceBuckets, from, to, now, battery: house ? house.battery_present : undefined, unusableDevices: unsupported, timeZone: tz });
  }
  return {
    devices,
    withoutMonitoring: found.withoutMonitoring,
    unsupported,
    daily,
    monthly,
    months: past,
    week,
    tz,
    assumed,
    balance,
    balanceReason: house ? null : c.house_problem ? `the whole-house configuration is invalid (${c.house_problem})` : "the whole-house energy mappings are not configured for this dashboard",
    native: nativeTotals(devices, hass),
    crossCheck: {
      day: crossTotals(daily),
      month: crossTotals(monthly),
    },
    error: null,
    generatedAt: now,
  };
}

function sharedFor(config) {
  const { part, ...rest } = config;
  const key = JSON.stringify(rest);
  if (!SHARED.has(key)) SHARED.set(key, { state: null, loadedAt: 0, loading: false, listeners: new Set() });
  return SHARED.get(key);
}

/**
 * Validate the whole-house block. A bad block disables only the balance (with the reason); it never breaks
 * the device tables. Entity IDs must be sensor entity IDs and `battery_present` a boolean or "unknown".
 */
export function normalizeHouse(house) {
  if (house === undefined || house === null) return { house: null, problem: null };
  if (typeof house !== "object" || Array.isArray(house)) return { house: null, problem: "house must be a mapping" };
  const clean = { battery_present: house.battery_present === false ? false : house.battery_present === true ? true : "unknown" };
  for (const key of ["solar", "import", "export"]) {
    if (house[key] === undefined || house[key] === null || house[key] === "") continue;
    if (typeof house[key] !== "string" || !/^sensor\.[a-z0-9_]+$/.test(house[key])) return { house: null, problem: `house.${key} is not a sensor entity ID` };
    clean[key] = house[key];
  }
  return { house: clean, problem: null };
}

export class ThermowattDeviceEnergyCard extends BaseElement {
  setConfig(config) {
    if (!config || !Array.isArray(config.rates) || !config.rates.length) throw new Error("rates are required");
    if (!config.tariff) throw new Error("tariff is required");
    validateRates(config.rates);
    if (this._config) sharedFor(this._config).listeners.delete(this);
    const { house, problem } = normalizeHouse(config.house);
    this._config = { timezone: DEFAULT_TIMEZONE, refresh_minutes: 5, part: "all", ...config, house, house_problem: problem };
    this._renderKey = null;
    this._sort = { daily: { key: "kwh", direction: "desc" }, monthly: { key: "kwh", direction: "desc" } };
    this._balanceView = "day";
  }

  connectedCallback() {
    if (this._config) sharedFor(this._config).listeners.add(this);
  }

  disconnectedCallback() {
    if (this._config) sharedFor(this._config).listeners.delete(this);
    if (this._resize) {
      this._resize.disconnect();
      this._resize = null;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      if (typeof ResizeObserver !== "undefined") {
        // phones get a smaller chart canvas and fewer table columns: redraw when the width class changes
        this._resize = new ResizeObserver(() => {
          const w = this.clientWidth || 0;
          const cls = `${w > 0 && w < 480}|${w > 0 && w < 640}`;
          if (cls !== this._widthClass) {
            this._widthClass = cls;
            this._render();
          }
        });
        this._resize.observe(this);
      }
      this._root.addEventListener("click", (event) => {
        const toggle = event.target.closest("button[data-balance]");
        if (toggle) {
          this._balanceView = toggle.dataset.balance === "month" ? "month" : "day";
          this._render();
          return;
        }
        const button = event.target.closest("button[data-sort]");
        if (!button) return;
        const table = button.dataset.table;
        const key = button.dataset.sort;
        const current = this._sort[table];
        const first = key === "name" ? "asc" : "desc"; // names A-Z first, numbers largest first
        this._sort[table] = { key, direction: current.key === key ? (current.direction === "desc" ? "asc" : "desc") : first };
        this._render();
      });
    }
    const shared = sharedFor(this._config);
    if (this.isConnected !== false) shared.listeners.add(this);
    const stale = !shared.loadedAt || Date.now() - shared.loadedAt > this._config.refresh_minutes * 60e3;
    if (stale && !shared.loading && Date.now() >= (shared.retryAt || 0)) this._load(shared);
    this._render();
  }

  getCardSize() {
    return { summary: 4, balance: 12, balancemini: 7, week: 4, daily: 7, monthly: 9, history: 9 }[this._config && this._config.part] || 14;
  }

  async _load(shared) {
    shared.loading = true;
    try {
      shared.state = await computeState(this._hass, this._config);
      shared.loadedAt = Date.now();
      shared.retryAt = 0;
    } catch (error) {
      shared.state = { ...(shared.state || {}), error: String(error && error.message ? error.message : error) };
      shared.retryAt = Date.now() + 60e3;
    } finally {
      shared.version = (shared.version || 0) + 1;
      shared.loading = false;
      for (const card of shared.listeners) card._render();
    }
  }

  _render() {
    if (!this._root) return;
    const shared = sharedFor(this._config);
    const s = shared.state;
    const part = this._config.part;
    const width = this.clientWidth || 0;
    const narrow = width > 0 && width < 480;
    const compact = width > 0 && width < 640;
    const stale = !!(s && s.generatedAt && !s.error && Date.now() - s.generatedAt > 3 * this._config.refresh_minutes * 60e3);
    const key = `${shared.version || 0}|${JSON.stringify(this._sort)}|${this._balanceView}|${s ? 1 : 0}|${stale ? 1 : 0}|${narrow ? 1 : 0}|${compact ? 1 : 0}`;
    if (key === this._renderKey) return; // nothing changed: keep focus, scroll position and in-flight clicks
    this._renderKey = key;
    const open = `<ha-card><style>${STYLE}</style>`;
    const head = (icon, title, extra = "") => `<div class="head">${iconHtml(icon)}<div class="title">${escapeHtml(title)}</div>${extra}</div>`;
    if (!s) {
      this._root.innerHTML = open + '<p class="note">Loading device energy…</p></ha-card>';
      return;
    }
    if (s.error && !s.devices) {
      this._root.innerHTML = open + `<p class="note">Device energy statistics are unavailable (${escapeHtml(s.error)}). The rest of the dashboard is unaffected.</p></ha-card>`;
      return;
    }
    const dailyTotal = combine(s.daily);
    const monthTotal = combine(s.monthly);
    const partialMonth = s.monthly.some((r) => r.partialFrom);
    const estimated = s.devices.some((d) => d.estimated);
    const label = monthLabel(s.generatedAt || Date.now(), s.tz);
    const want = (name) => part === "all" || part === name;
    const asOf = s.generatedAt ? new Date(s.generatedAt).toLocaleTimeString("en-AU", { timeZone: s.tz, hour: "numeric", minute: "2-digit" }) : "";
    let html = open;
    if (s.error) html += `<p class="note">Latest refresh failed (${escapeHtml(s.error)}). Showing statistics last loaded at ${escapeHtml(asOf)}.</p>`;
    else if (stale) html += `<p class="note">Statistics were last refreshed at ${escapeHtml(asOf)} and may be out of date.</p>`;
    const sections = [];
    if (want("summary")) {
      const kbox = (lab, value, unit, sub) => `<div class="kbox"><div class="lab">${lab}</div><div class="val">${value}${unit ? `<span class="unit">${unit}</span>` : ""}</div><div class="sub">${sub}</div></div>`;
      const kwhParts = (v) => (v === null || v === undefined ? ["—", ""] : [v.toFixed(v < 10 ? 2 : 1), "kWh"]);
      const [dv, du] = kwhParts(dailyTotal && dailyTotal.kwh);
      const [mv, mu] = kwhParts(monthTotal && monthTotal.kwh);
      const devicesSub = [s.withoutMonitoring ? `${s.withoutMonitoring} without energy monitoring (not shown)` : "", s.unsupported ? `${s.unsupported} with unsupported statistics units (not shown)` : ""].filter(Boolean).join("; ") || "all with energy monitoring";
      sections.push(
        head("mdi:meter-electric", "Device energy", `<span class="chip t-idle">As of ${escapeHtml(asOf)}</span>`) +
          '<div class="kpis3">' +
          kbox("Today", dv, du, `${fmtMoney(dailyTotal && dailyTotal.cost)} est. operating cost`) +
          kbox(`${escapeHtml(label)} so far${partialMonth ? " (partial)" : ""}`, mv, mu, `${fmtMoney(monthTotal && monthTotal.cost)} est. operating cost`) +
          kbox("Devices monitored", String(s.devices.length), "", escapeHtml(devicesSub)) +
          "</div>" +
          '<details><summary>How these costs are estimated</summary><p class="note">Costs are <b>estimated tariff-valued operating costs</b> (consumption × the peak/off-peak rate in force when it was used). They are not Aurora charges: no supply charge, no solar feed-in credit, and no assumption that the energy came from the grid.' +
          (estimated ? " Devices marked <i>est.</i> only report power, so their energy is estimated." : "") +
          (s.assumed ? " <b>≈</b> marks costs valued at an <b>assumed</b> rate: the price start date is unconfirmed or earlier than the first dated rate, so they are not verified historical costs." : "") +
          ` Statistics as of ${escapeHtml(asOf)}.</p></details>`
      );
    }
    if (want("balance")) sections.push(balanceHtml(s, this._balanceView, compact));
    if (part === "balancemini") sections.push(balanceMiniHtml(s, this._balanceView));
    if (want("week")) sections.push(head("mdi:chart-bar", "Last seven days (kWh)") + barsSvg(s.week, "kwh", "kWh", narrow));
    if (want("daily")) {
      sections.push(head("mdi:calendar-today", `Today (midnight ${s.tz.split("/")[1] || s.tz} time)`) + tableHtml("daily", s.daily, dailyTotal, this._sort.daily, ""));
    }
    if (want("monthly")) {
      let block =
        head("mdi:calendar-month", `${label} month to date`) +
        tableHtml("monthly", s.monthly, monthTotal, this._sort.monthly, partialMonth ? `Monitoring began partway through ${escapeHtml(label)}: totals cover the recorded part of the month only.` : "");
      if (s.months.length) {
        block += "<h3>Previous completed months</h3>";
        block += '<p class="note">Reconstructed from long-term statistics for the devices and energy sources found today; these are not archived monthly totals, so a device removed or disabled since drops out of earlier months.</p>';
        block += '<div class="scroll"><table><thead><tr><th>Month</th><th>kWh</th><th class="c-off">Off-peak $</th><th class="c-peak">Peak $</th><th>Total $</th></tr></thead><tbody>';
        for (const m of [...s.months].reverse()) {
          block += `<tr><td>${escapeHtml(m.full)}${m.partial ? ' <span class="part">partial</span>' : ""}</td><td>${fmtKwh(m.total.kwh)}</td><td class="c-off">${fmtMoney(m.total.offCost, m.total.assumed)}</td><td class="c-peak">${fmtMoney(m.total.peakCost, m.total.assumed)}</td><td>${fmtMoney(m.total.cost, m.total.assumed)}</td></tr>`;
        }
        block += "</tbody></table></div>";
      } else {
        block += '<p class="note">No completed month of statistics yet: history appears after the first month rollover (or as soon as earlier statistics exist).</p>';
      }
      sections.push(block);
    }
    if (want("history")) {
      let block = head("mdi:chart-timeline-variant", "Monthly history");
      if (s.months.length) {
        block += "<h3>Monthly comparison (kWh)</h3>" + barsSvg(s.months.map((m) => ({ label: m.label, kwh: m.total.kwh, partial: m.partial })), "kwh", "kWh", narrow);
        block += "<h3>Monthly comparison (est. cost)</h3>" + barsSvg(s.months.map((m) => ({ label: m.label, cost: m.total.cost, partial: m.partial, assumed: m.total.assumed })), "cost", "$", narrow);
        block += "<h3>By device (kWh per month)</h3>";
        block += '<div class="scroll"><table><thead><tr><th>Device</th>' + s.months.map((m) => `<th>${escapeHtml(m.label)}</th>`).join("") + "</tr></thead><tbody>";
        for (const d of s.devices) {
          block += `<tr><td>${escapeHtml(d.name)}</td>` + s.months.map((m) => { const row = m.rows.find((r) => r.deviceId === d.deviceId); return `<td>${row && row.data ? row.data.kwh.toFixed(row.data.kwh < 1 ? 3 : 2) : "—"}</td>`; }).join("") + "</tr>";
        }
        block += "</tbody></table></div>";
      } else {
        block += '<p class="note">No completed month of statistics yet.</p>';
      }
      sections.push(block);
    }
    this._root.innerHTML = html + sections.join('<div style="height:6px"></div>') + "</ha-card>";
  }
}

/* ------------------------------------------------------------------------------------------------
 * <thermowatt-device-energy-page>: the whole Device energy view as ONE card for a Home Assistant "panel" view.
 * It lays the parts out itself (balance hero beside a summary column, the Today table and the monthly history
 * underneath) with container queries, so the page does not depend on how many columns Home Assistant's sections
 * grid gives it. The parts are ordinary <thermowatt-device-energy-card> elements sharing one statistics load.
 * ---------------------------------------------------------------------------------------------- */
class ThermowattDeviceEnergyPage extends BaseUi {
  setConfig(config) {
    if (!config || !Array.isArray(config.rates) || !config.rates.length) throw new Error("rates are required");
    const { part, ...rest } = config;
    this._config = rest;
    this._children = null;
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._built) this._build();
    for (const child of this._children || []) child.hass = hass;
  }

  getCardSize() {
    return 24;
  }

  _build() {
    this._built = true;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      :host{display:block}
      .wrap{container-type:inline-size;width:100%}
      .page{display:grid;gap:16px;max-width:1680px;margin:0 auto;padding:0 0 16px;align-items:start;
        grid-template-columns:repeat(3,minmax(0,1fr));
        grid-template-areas:"balance balance stack" "daily daily history"}
      .balance{grid-area:balance}.stack{grid-area:stack;display:flex;flex-direction:column;gap:16px}
      .daily{grid-area:daily}.history{grid-area:history}
      .page>*{min-width:0}
      @container (max-width:1180px){
        .page{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-areas:"balance balance" "stack daily" "history history"}
      }
      @container (max-width:760px){
        .page{grid-template-columns:minmax(0,1fr);grid-template-areas:"balance" "stack" "daily" "history"}
      }
    </style><div class="wrap"><div class="page">
      <div class="balance"></div><div class="stack"></div><div class="daily"></div><div class="history"></div>
    </div></div>`;
    const slots = { balance: root.querySelector(".balance"), stack: root.querySelector(".stack"), daily: root.querySelector(".daily"), history: root.querySelector(".history") };
    const layout = [["balance", "balance"], ["summary", "stack"], ["week", "stack"], ["monthly", "stack"], ["daily", "daily"], ["history", "history"]];
    this._children = [];
    for (const [part, slot] of layout) {
      const child = document.createElement("thermowatt-device-energy-card");
      try {
        child.setConfig({ ...this._config, part });
      } catch (error) {
        slots[slot].textContent = `Device energy could not be shown: ${error.message}`;
        continue;
      }
      slots[slot].appendChild(child);
      this._children.push(child);
    }
  }
}

if (typeof customElements !== "undefined" && !customElements.get("thermowatt-device-energy-card")) {
  customElements.define("thermowatt-device-energy-card", ThermowattDeviceEnergyCard);
  if (!customElements.get("thermowatt-device-energy-page")) customElements.define("thermowatt-device-energy-page", ThermowattDeviceEnergyPage);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "thermowatt-device-energy-card",
    name: "Thermowatt device energy",
    description: "Per-device energy and estimated tariff-valued operating cost from long-term statistics",
  });
}

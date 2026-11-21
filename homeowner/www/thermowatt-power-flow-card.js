/*
 * Thermowatt power-flow card: a lightweight, dependency-free, SEMS+-inspired three-node view.
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
  const unit = String((stateObj.attributes || {}).unit_of_measurement || "W").toLowerCase();
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
 * Returns node values, the grid label and the three line flows (watts, direction fixed per line).
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
  const solarActive = solar !== null && solar > idleW;
  const solarExport = solarActive && exportW ? Math.min(exportW, solar) : 0;
  let solarToHouse = 0;
  if (solarActive) {
    if (house !== null) solarToHouse = Math.min(solar, house);
    else if (exportW !== null) solarToHouse = Math.max(0, solar - exportW);
  }
  const gridToHouse = importW && importW > idleW ? importW : 0;
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
    lines: {
      solarToHouse: solarToHouse > idleW ? solarToHouse : 0,
      solarToGrid: solarExport > idleW ? solarExport : 0,
      gridToHouse,
    },
  };
}

// Line geometry in a 400 x 322 viewBox; every path is drawn in its flow direction.
const PATHS = {
  solarToHouse: "M178 98 C140 150 100 170 88 205",
  solarToGrid: "M222 98 C260 150 300 170 312 205",
  gridToHouse: "M285 245 L115 245",
};
const COLOURS = { solarToHouse: GREEN, solarToGrid: GREEN, gridToHouse: ORANGE };

function chevrons(id, kw, colour, reduceMotion) {
  const dur = travelSeconds(kw);
  const shape = `<path d="M-5 -5 L3 0 L-5 5" fill="none" stroke="${colour}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`;
  const items = [];
  for (let i = 0; i < 3; i += 1) {
    if (reduceMotion) {
      items.push(`<g transform="translate(${60 + i * 80} 0)">${shape}</g>`);
    } else {
      items.push(
        `<g>${shape}<animateMotion dur="${dur.toFixed(2)}s" begin="-${((dur * i) / 3).toFixed(2)}s" repeatCount="indefinite" rotate="auto"><mpath href="#${id}"/></animateMotion></g>`
      );
    }
  }
  return reduceMotion ? "" : items.join("");
}

export function renderSvg(model, reduceMotion = false) {
  const lines = Object.keys(PATHS)
    .map((key) => {
      const watts = model.lines[key];
      const active = watts > 0;
      const colour = active ? COLOURS[key] : GREY;
      const moving = active ? chevrons(`tw-${key}`, watts / 1000, colour, reduceMotion) : "";
      return `<path id="tw-${key}" d="${PATHS[key]}" fill="none" stroke="${colour}" stroke-width="${active ? 3 : 2}" stroke-linecap="round" opacity="${active ? 0.9 : 0.55}"/>${moving}`;
    })
    .join("");
  const gridColour = { import: ORANGE, export: GREEN }[model.gridState] || GREY;
  const solarColour = model.solarW > 5 ? GREEN : GREY;
  const node = (cx, cy, colour, icon, title, value) =>
    `<circle cx="${cx}" cy="${cy}" r="42" fill="var(--card-background-color,#fff)" stroke="${colour}" stroke-width="3"/>` +
    `<g transform="translate(${cx} ${cy - 8})" fill="none" stroke="${colour}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${icon}</g>` +
    `<text x="${cx}" y="${cy + 22}" text-anchor="middle" font-size="13" font-weight="600" fill="var(--primary-text-color,#212121)">${value}</text>` +
    `<text x="${cx}" y="${cy + 62}" text-anchor="middle" font-size="12.5" fill="var(--secondary-text-color,#727272)">${title}</text>`;
  const sun = '<circle r="7"/><path d="M0 -14V-11M0 11V14M-14 0H-11M11 0H14M-10 -10l2 2M8 8l2 2M-10 10l2 -2M8 -8l2 -2"/>';
  const house = '<path d="M-13 3L0 -9L13 3M-9 0V12H9V0"/>';
  const grid = '<path d="M0 -13V13M-9 -6H9M-6 1H6M-11 13L0 -13L11 13"/>';
  return (
    `<svg viewBox="0 0 400 322" xmlns="http://www.w3.org/2000/svg" width="100%" role="img" aria-label="${ariaLabel(model)}">` +
    lines +
    node(200, 62, solarColour, sun, "Solar", formatKw(model.solarW)) +
    node(72, 245, model.lines.solarToHouse || model.lines.gridToHouse ? (model.lines.gridToHouse ? ORANGE : GREEN) : GREY, house, "House", formatKw(model.houseW)) +
    node(328, 245, gridColour, grid, model.gridLabel, formatKw(model.gridW)) +
    "</svg>"
  );
}

function ariaLabel(model) {
  return `Solar ${formatKw(model.solarW)}, house ${formatKw(model.houseW)}, ${model.gridLabel} ${formatKw(model.gridW)}`;
}

const Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

class ThermowattPowerFlowCard extends Base {
  setConfig(config) {
    for (const key of ["solar_entity", "house_entity", "grid_entity"]) {
      if (!config || !config[key]) throw new Error(`Missing ${key}`);
    }
    this._config = {
      grid_export_positive: true,
      idle_threshold_w: 5,
      stale_seconds: 900,
      ...config,
    };
    this._key = null;
  }

  set hass(hass) {
    const c = this._config;
    if (!c) return;
    const stale = c.stale_seconds;
    const model = computeFlows({
      solarW: readWatts(hass.states[c.solar_entity], stale),
      houseW: readWatts(hass.states[c.house_entity], stale),
      gridW: readWatts(hass.states[c.grid_entity], stale),
      exportPositive: c.grid_export_positive !== false,
      idleW: c.idle_threshold_w,
    });
    const reduce = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const key = JSON.stringify([model, reduce]);
    if (key === this._key) return; // nothing changed: keep animations running, no DOM work
    this._key = key;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
    }
    this._root.innerHTML =
      `<ha-card><style>:host{display:block}.wrap{padding:8px 12px 12px;max-width:520px;margin:0 auto}</style>` +
      `<div class="wrap">${renderSvg(model, reduce)}</div></ha-card>`;
  }

  getCardSize() {
    return 5;
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

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

// Line geometry in a 400 x 322 viewBox; every path is drawn in its flow direction.
const GEOMETRY = {
  solarToHouse: { p: [[178, 98], [140, 150], [100, 170], [88, 205]] },
  solarToGrid: { p: [[222, 98], [260, 150], [300, 170], [312, 205]] },
  gridToHouse: { p: [[285, 245], [115, 245]] },
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
    (model.inconsistent
      ? '<text x="200" y="316" text-anchor="middle" font-size="12" fill="var(--secondary-text-color,#727272)">Readings not in sync</text>'
      : "") +
    "</svg>"
  );
}

function ariaLabel(model) {
  const sync = model.inconsistent ? ", readings not in sync" : "";
  return `Solar ${formatKw(model.solarW)}, house ${formatKw(model.houseW)}, ${model.gridLabel} ${formatKw(model.gridW)}${sync}`;
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

/*
 * Thermowatt cards (one resource): <thermowatt-power-flow-card> and <thermowatt-device-energy-card>.
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
    `<circle cx="${cx}" cy="${cy}" r="38" fill="var(--card-background-color,#fff)" stroke="${colour}" stroke-width="3"/>` +
    `<g transform="translate(${cx} ${cy - 10})" fill="none" stroke="${colour}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${icon}</g>` +
    `<text x="${cx}" y="${cy + 18}" text-anchor="middle" font-size="13" font-weight="600" fill="var(--primary-text-color,#212121)">${value}</text>` +
    `<text x="${cx}" y="${cy + 53}" text-anchor="middle" font-size="12.5" fill="var(--secondary-text-color,#727272)">${title}</text>`;
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
      ? '<text x="200" y="254" text-anchor="middle" font-size="12" fill="var(--secondary-text-color,#727272)">Readings not in sync</text>'
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

/** Rank an energy sensor as the one cumulative lifetime source for its device (higher = better). */
function energyScore(entityId, entry, state) {
  const key = String(entry.translation_key || entry.tk || "").toLowerCase();
  const text = `${entityId} ${(state.attributes || {}).friendly_name || ""} ${key}`.toLowerCase();
  if (key === "total_consumption") return 100;
  if (/\b(total|lifetime|cumulative)\b|_total|total_/.test(text)) return 80;
  if (/today|daily|month|week|yesterday/.test(text)) return 10;
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
    const group = byDevice.get(deviceId) || { energy: [], power: [], labels: new Set(), entities: [] };
    byDevice.set(deviceId, group);
    group.entities.push(entityId);
    for (const l of entry.labels || entry.lb || []) group.labels.add(l);
    if (attrs.device_class === "energy" && Object.hasOwn(ENERGY_UNITS, unit) && ["total", "total_increasing"].includes(attrs.state_class)) {
      group.energy.push({ entityId, factor: ENERGY_UNITS[unit], score: energyScore(entityId, entry, state) });
    } else if (attrs.device_class === "power" && Object.hasOwn(POWER_UNITS, unit)) {
      group.power.push({ entityId, factor: POWER_UNITS[unit] });
    }
  }
  const devices = [];
  let withoutMonitoring = 0;
  for (const deviceId of monitoredPlatform) {
    const group = byDevice.get(deviceId) || { energy: [], power: [], labels: new Set(), entities: [] };
    const device = (hass.devices || {})[deviceId] || {};
    const name = device.name_by_user || device.name || (group.entities[0] || deviceId);
    const keys = [name, ...group.entities].map((x) => String(x).toLowerCase());
    if (label && group.labels.has(label)) continue;
    if (keys.some((k) => exclude.has(k))) continue;
    if (only.size && !keys.some((k) => only.has(k))) continue;
    const energy = [...group.energy].sort((a, b) => b.score - a.score || a.entityId.localeCompare(b.entityId))[0];
    const power = [...group.power].sort((a, b) => a.entityId.localeCompare(b.entityId))[0];
    if (energy) {
      devices.push({ deviceId, name, source: { kind: "energy", entityId: energy.entityId, factor: energy.factor }, estimated: false });
    } else if (power) {
      devices.push({ deviceId, name, source: { kind: "power", entityId: power.entityId, factor: power.factor }, estimated: true });
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

function tableHtml(id, rows, total, sort, partialNote) {
  const arrow = (key) => (sort.key === key ? (sort.direction === "asc" ? " ▲" : " ▼") : "");
  const head = [
    ["name", "Device"],
    ["kwh", "kWh"],
    ["offCost", "Off-peak $"],
    ["peakCost", "Peak $"],
    ["cost", "Total $"],
  ]
    .map(([key, text]) => `<th><button data-table="${id}" data-sort="${key}">${text}${arrow(key)}</button></th>`)
    .join("");
  const body = sortRows(rows, sort.key, sort.direction)
    .map(
      (r) =>
        `<tr><td>${escapeHtml(r.name)}${r.estimated ? ' <span class="est" title="Estimated from measured power">est.</span>' : ""}${r.partialFrom ? ` <span class="part" title="Statistics for this period start later than the period">from ${escapeHtml(r.partialFrom)}</span>` : ""}${r.missingHours ? ` <span class="part" title="Hours inside this period with no recorded statistics (not counted as zero)">${r.missingHours} h missing</span>` : ""}</td>` +
        (r.data
          ? `<td>${fmtKwh(r.data.kwh)}</td><td>${fmtMoney(r.data.offCost, r.data.assumed)}</td><td>${fmtMoney(r.data.peakCost, r.data.assumed)}</td><td>${fmtMoney(r.data.cost, r.data.assumed)}</td>`
          : '<td colspan="4" class="none">no statistics (not zero)</td>') +
        "</tr>"
    )
    .join("");
  const foot = total
    ? `<tr class="total"><td>Total (${total.devices} device${total.devices === 1 ? "" : "s"}${total.missing ? `, ${total.missing} without data` : ""})${total.incomplete ? ' <span class="part" title="At least one device has missing or late-starting statistics in this period">incomplete</span>' : ""}</td><td>${fmtKwh(total.kwh)}</td><td>${fmtMoney(total.offCost, total.assumed)}</td><td>${fmtMoney(total.peakCost, total.assumed)}</td><td>${fmtMoney(total.cost, total.assumed)}</td></tr>`
    : '<tr class="total"><td colspan="5" class="none">No data yet</td></tr>';
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div>${partialNote ? `<p class="note">${partialNote}</p>` : ""}`;
}

function barsSvg(items, key, unit) {
  if (!items.length) return "";
  const max = Math.max(...items.map((i) => i[key] || 0), 1e-9);
  const w = 56;
  const gap = 10;
  const height = 124;
  const bars = items
    .map((item, index) => {
      const value = item[key];
      const h = value ? Math.max(2, (value / max) * 80) : 0;
      const x = index * (w + gap) + gap;
      return (
        `<g><rect x="${x}" y="${height - 22 - h}" width="${w}" height="${h}" rx="3" fill="var(--primary-color,#03a9f4)" opacity="${item.partial ? 0.55 : 0.95}"/>` +
        `<text x="${x + w / 2}" y="${height - 26 - h}" text-anchor="middle" font-size="10" fill="var(--primary-text-color)">${value === null ? "—" : unit === "$" ? fmtMoney(value, item.assumed) : value.toFixed(value < 10 ? 1 : 0)}</text>` +
        `<text x="${x + w / 2}" y="${height - 6}" text-anchor="middle" font-size="10" fill="var(--secondary-text-color)">${escapeHtml(item.label)}</text></g>`
      );
    })
    .join("");
  const width = items.length * (w + gap) + gap;
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" style="max-width:${width * 1.4}px" role="img" aria-label="Bar chart">${bars}</svg>`;
}

const STYLE = `
  :host{display:block}
  ha-card{padding:12px 14px}
  h3{margin:10px 0 6px;font-size:14px;font-weight:600}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
  .box{border:1px solid var(--divider-color,#ddd);border-radius:10px;padding:8px 10px}
  .box b{display:block;font-size:20px}.box span{font-size:12px;color:var(--secondary-text-color)}
  .scroll{overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{padding:5px 8px;text-align:right;white-space:nowrap}
  th:first-child,td:first-child{text-align:left;white-space:normal}
  th button{all:unset;cursor:pointer;font-weight:600;color:var(--primary-text-color)}
  th button:focus-visible{outline:2px solid var(--primary-color)}
  tbody tr{border-top:1px solid var(--divider-color,#ddd)}
  tr.total{border-top:2px solid var(--divider-color,#bbb);font-weight:600}
  .none,.note{color:var(--secondary-text-color);font-size:12px}
  .est,.part{font-size:11px;color:var(--secondary-text-color);border:1px solid var(--divider-color,#ccc);border-radius:8px;padding:0 5px}
  .warn{font-size:12px;color:var(--secondary-text-color);margin:6px 0}
  @media (max-width:520px){th,td{padding:4px 5px;font-size:12px}}
`;

const BaseElement = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

// One load per configuration, shared by every card part on the page (summary, daily, monthly, history).
const SHARED = new Map();

const withTimeout = (promise) =>
  Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error("statistics request timed out")), 60e3))]);

/**
 * Load and value the statistics. Units come from the RECORDER'S statistics metadata (the unit the statistics
 * are stored in), not from the live sensor. Hourly statistics cover the whole history; 5-minute statistics are
 * used only for the last few hours that have no hourly row yet, so no hour is ever counted twice and no
 * retained history is skipped, whatever the recorder's short-term retention is.
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

  const meta = new Map();
  if (found.devices.length) {
    const list = await withTimeout(hass.callWS({ type: "recorder/get_statistics_metadata", statistic_ids: found.devices.map((d) => d.source.entityId) }));
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

  const buckets = new Map(devices.map((d) => [d.deviceId, []]));
  const query = (ids, kind, from, to, period) =>
    ids.length
      ? withTimeout(
          hass.callWS({
            type: "recorder/statistics_during_period",
            start_time: new Date(from).toISOString(),
            end_time: new Date(to).toISOString(),
            statistic_ids: ids,
            period,
            types: kind === "energy" ? ["change"] : ["mean"],
          })
        )
      : Promise.resolve({});
  for (const kind of ["energy", "power"]) {
    const group = devices.filter((d) => !d.noStatistics && d.source.kind === kind);
    const ids = group.map((d) => d.source.entityId);
    const hourly = await query(ids, kind, historyStart, hourEnd, "hour");
    const fine = await query(ids, kind, fineFrom, now + HOUR_MS, "5minute");
    for (const d of group) {
      const id = d.source.entityId;
      buckets.set(d.deviceId, mergeBuckets(toBuckets((hourly || {})[id], d.source), toBuckets((fine || {})[id], d.source)));
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
      };
    });
  const isPartial = (rows, total) => !!total && (total.incomplete || rows.some((r) => r.partialFrom || r.missingHours));
  const daily = rowsFor(dayStart, dayEnd);
  const monthly = rowsFor(monthStart, monthEnd);
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
  return { devices, withoutMonitoring: found.withoutMonitoring, unsupported, daily, monthly, months: past, week, tz, assumed, error: null, generatedAt: now };
}

function sharedFor(config) {
  const { part, ...rest } = config;
  const key = JSON.stringify(rest);
  if (!SHARED.has(key)) SHARED.set(key, { state: null, loadedAt: 0, loading: false, listeners: new Set() });
  return SHARED.get(key);
}

export class ThermowattDeviceEnergyCard extends BaseElement {
  setConfig(config) {
    if (!config || !Array.isArray(config.rates) || !config.rates.length) throw new Error("rates are required");
    if (!config.tariff) throw new Error("tariff is required");
    validateRates(config.rates);
    if (this._config) sharedFor(this._config).listeners.delete(this);
    this._config = { timezone: DEFAULT_TIMEZONE, refresh_minutes: 5, part: "all", ...config };
    this._renderKey = null;
    this._sort = { daily: { key: "kwh", direction: "desc" }, monthly: { key: "kwh", direction: "desc" } };
  }

  connectedCallback() {
    if (this._config) sharedFor(this._config).listeners.add(this);
  }

  disconnectedCallback() {
    if (this._config) sharedFor(this._config).listeners.delete(this);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.addEventListener("click", (event) => {
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
    return { summary: 3, daily: 4, monthly: 6, history: 8 }[this._config && this._config.part] || 12;
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
    const stale = !!(s && s.generatedAt && !s.error && Date.now() - s.generatedAt > 3 * this._config.refresh_minutes * 60e3);
    const key = `${shared.version || 0}|${JSON.stringify(this._sort)}|${s ? 1 : 0}|${stale ? 1 : 0}`;
    if (key === this._renderKey) return; // nothing changed: keep focus, scroll position and in-flight clicks
    this._renderKey = key;
    let html = `<ha-card><style>${STYLE}</style>`;
    if (!s) {
      this._root.innerHTML = html + '<p class="note">Loading device energy…</p></ha-card>';
      return;
    }
    if (s.error && !s.devices) {
      this._root.innerHTML = html + `<p class="warn">Device energy statistics are unavailable (${escapeHtml(s.error)}). The rest of the dashboard is unaffected.</p></ha-card>`;
      return;
    }
    const dailyTotal = combine(s.daily);
    const monthTotal = combine(s.monthly);
    const partialMonth = s.monthly.some((r) => r.partialFrom);
    const estimated = s.devices.some((d) => d.estimated);
    const label = monthLabel(s.generatedAt || Date.now(), s.tz);
    const want = (name) => part === "all" || part === name;
    const asOf = s.generatedAt ? new Date(s.generatedAt).toLocaleTimeString("en-AU", { timeZone: s.tz, hour: "numeric", minute: "2-digit" }) : "";
    if (s.error) html += `<p class="warn">Latest refresh failed (${escapeHtml(s.error)}). Showing statistics last loaded at ${escapeHtml(asOf)}.</p>`;
    else if (stale) html += `<p class="warn">Statistics were last refreshed at ${escapeHtml(asOf)} and may be out of date.</p>`;
    if (want("summary")) {
      html += '<div class="cards">';
      html += `<div class="box"><span>Today</span><b>${fmtKwh(dailyTotal && dailyTotal.kwh)}</b><span>${fmtMoney(dailyTotal && dailyTotal.cost)} est. operating cost</span></div>`;
      html += `<div class="box"><span>${escapeHtml(label)} so far${partialMonth ? " (partial)" : ""}</span><b>${fmtKwh(monthTotal && monthTotal.kwh)}</b><span>${fmtMoney(monthTotal && monthTotal.cost)} est. operating cost</span></div>`;
      html += `<div class="box"><span>Devices monitored</span><b>${s.devices.length}</b><span>${[s.withoutMonitoring ? `${s.withoutMonitoring} without energy monitoring (not shown)` : "", s.unsupported ? `${s.unsupported} with unsupported statistics units (not shown)` : ""].filter(Boolean).join("; ") || "all with energy monitoring"}</span></div>`;
      html += "</div>";
      html += '<p class="warn">Costs are <b>estimated tariff-valued operating costs</b> (consumption × the peak/off-peak rate in force when it was used). They are not Aurora charges: no supply charge, no solar feed-in credit, and no assumption that the energy came from the grid.' + (estimated ? " Devices marked <i>est.</i> only report power, so their energy is estimated." : "") + (s.assumed ? " <b>≈</b> marks costs valued at an <b>assumed</b> rate: the price start date is unconfirmed or earlier than the first dated rate, so they are not verified historical costs." : "") + ` Statistics as of ${escapeHtml(asOf)}.</p>`;
    }
    if (want("daily")) {
      html += `<h3>Today (midnight ${escapeHtml(s.tz.split("/")[1] || s.tz)} time)</h3>` + tableHtml("daily", s.daily, dailyTotal, this._sort.daily, "");
    }
    if (want("monthly")) {
      html +=
        `<h3>${escapeHtml(label)} month to date</h3>` +
        tableHtml("monthly", s.monthly, monthTotal, this._sort.monthly, partialMonth ? `Monitoring began partway through ${escapeHtml(label)}: totals cover the recorded part of the month only.` : "");
      if (s.months.length) {
        html += "<h3>Previous completed months</h3>";
        html += '<p class="note">Reconstructed from long-term statistics for the devices and energy sources found today; these are not archived monthly totals, so a device removed or disabled since drops out of earlier months.</p>';
        html += '<div class="scroll"><table><thead><tr><th>Month</th><th>kWh</th><th>Off-peak $</th><th>Peak $</th><th>Total $</th></tr></thead><tbody>';
        for (const m of [...s.months].reverse()) {
          html += `<tr><td>${escapeHtml(m.full)}${m.partial ? ' <span class="part">partial</span>' : ""}</td><td>${fmtKwh(m.total.kwh)}</td><td>${fmtMoney(m.total.offCost, m.total.assumed)}</td><td>${fmtMoney(m.total.peakCost, m.total.assumed)}</td><td>${fmtMoney(m.total.cost, m.total.assumed)}</td></tr>`;
        }
        html += "</tbody></table></div>";
      } else {
        html += '<p class="note">No completed month of statistics yet: history appears after the first month rollover (or as soon as earlier statistics exist).</p>';
      }
    }
    if (want("history")) {
      if (s.months.length) {
        html += "<h3>Monthly comparison (kWh)</h3>" + barsSvg(s.months.map((m) => ({ label: m.label, kwh: m.total.kwh, partial: m.partial })), "kwh", "kWh");
        html += "<h3>Monthly comparison (est. cost)</h3>" + barsSvg(s.months.map((m) => ({ label: m.label, cost: m.total.cost, partial: m.partial, assumed: m.total.assumed })), "cost", "$");
        html += "<h3>By device (kWh per month)</h3>";
        html += '<div class="scroll"><table><thead><tr><th>Device</th>' + s.months.map((m) => `<th>${escapeHtml(m.label)}</th>`).join("") + "</tr></thead><tbody>";
        for (const d of s.devices) {
          html += `<tr><td>${escapeHtml(d.name)}</td>` + s.months.map((m) => { const row = m.rows.find((r) => r.deviceId === d.deviceId); return `<td>${row && row.data ? row.data.kwh.toFixed(row.data.kwh < 1 ? 3 : 2) : "—"}</td>`; }).join("") + "</tr>";
        }
        html += "</tbody></table></div>";
      }
      html += "<h3>Last seven days (kWh)</h3>" + barsSvg(s.week, "kwh", "kWh");
    }
    this._root.innerHTML = html + "</ha-card>";
  }
}

if (typeof customElements !== "undefined" && !customElements.get("thermowatt-device-energy-card")) {
  customElements.define("thermowatt-device-energy-card", ThermowattDeviceEnergyCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "thermowatt-device-energy-card",
    name: "Thermowatt device energy",
    description: "Per-device energy and estimated tariff-valued operating cost from long-term statistics",
  });
}

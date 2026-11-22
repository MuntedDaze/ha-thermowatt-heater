// Shared fixtures: a fake Home Assistant (registry, states, recorder statistics) and the loaded card module.
import assert from "node:assert/strict";

globalThis.window = globalThis;
class FakeElement {
  attachShadow() {
    this.sr = { innerHTML: "", listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
    return this.sr;
  }
}
globalThis.HTMLElement = FakeElement;
const registry = new Map();
globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c) };
export const mod = await import("../../../homeowner/www/thermowatt-power-flow-card.js");
export const Card = registry.get("thermowatt-device-energy-card");

export const TZ = "Australia/Hobart";
export const HOUR = 3600e3;
let counter = 0;
export const config = (extra = {}) => ({
  rates: [{ effective_from: "2000-01-01", offpeak: 0.1419, peak: 0.1907 }],
  tariff: { clock: "standard", utc_offset_hours: 10, peak_windows: [{ days: [0, 1, 2, 3, 4], start: "07:00", end: "10:00" }] },
  timezone: TZ,
  history_months: 6,
  platforms: ["tplink"],
  tag: ++counter, // a distinct shared-cache key per test
  ...extra,
});

/**
 * A fake Home Assistant. `spec` maps a device key to { name, kind: "energy"|"power", unit, hour(t) }: `hour`
 * returns the value for the hour starting at t (energy: the change in `unit`; power: the mean in `unit`), or
 * undefined for no statistics. It emulates the recorder: hourly rows for completed hours (compiled five minutes
 * after the hour) at any age, 5-minute rows only inside the short-term retention window.
 */
export function hassFor(spec, { now = Date.now(), retainMs = 10 * 24 * HOUR, log = [] } = {}) {
  const entities = {};
  const states = {};
  const devices = {};
  const byId = {};
  for (const [key, d] of Object.entries(spec)) {
    const entityId = d.entityId || `sensor.${key}_${d.kind}`;
    byId[entityId] = d;
    if (d.platform) {
      entities[entityId] = { platform: d.platform }; // not a Tapo device (for example the inverter)
    } else {
      entities[entityId] = { platform: "tplink", device_id: key };
      devices[key] = { name: d.name };
    }
    states[entityId] = {
      state: "1",
      attributes:
        d.kind === "energy"
          ? { device_class: "energy", unit_of_measurement: "kWh", state_class: "total_increasing" }
          : { device_class: "power", unit_of_measurement: "W", state_class: "measurement" },
    };
  }
  return {
    entities,
    states,
    devices,
    log,
    async callWS(message) {
      log.push(message);
      if (message.type === "recorder/get_statistics_metadata") {
        return message.statistic_ids
          .filter((id) => byId[id] && !byId[id].noMetadata)
          .map((id) => ({
            statistic_id: id,
            statistics_unit_of_measurement: byId[id].unit ?? (byId[id].kind === "energy" ? "kWh" : "W"),
            has_sum: byId[id].kind === "energy",
            has_mean: byId[id].kind === "power",
          }));
      }
      assert.equal(message.type, "recorder/statistics_during_period");
      const from = Date.parse(message.start_time);
      const to = Date.parse(message.end_time);
      const fine = message.period === "5minute";
      const step = fine ? 300e3 : HOUR;
      const out = {};
      for (const id of message.statistic_ids) {
        const d = byId[id];
        const rows = [];
        for (let t = Math.ceil(from / step) * step; t < to; t += step) {
          if (fine ? t + step > now || t < now - retainMs : t + step + 300e3 > now) continue;
          const hourStart = Math.floor(t / HOUR) * HOUR;
          const value = d.hour(hourStart);
          if (value === undefined) continue;
          const scaled = fine && d.kind === "energy" ? value / 12 : value;
          rows.push({ start: t, end: t + step, [d.kind === "energy" ? "change" : "mean"]: scaled });
        }
        out[id] = rows;
      }
      return out;
    },
  };
}
export const one = () => 1; // 1 kWh every hour
export const monthLabelOf = (offset, now) => mod.monthLabel(mod.shiftMonth(now, offset, TZ), TZ);
export const text = (card) => card.sr.innerHTML.replace(/<style>[\s\S]*?<\/style>/, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
export const settle = () => new Promise((r) => setTimeout(r, 30));
export const near = (a, b, tolerance = 1.01) => assert.ok(Math.abs(a - b) <= tolerance, `${a} vs ${b}`);


/** Run `fn` with the clock fixed at `ms` (the card reads Date.now()). */
export async function atTime(ms, fn) {
  const real = Date.now;
  Date.now = () => ms;
  try {
    return await fn();
  } finally {
    Date.now = real;
  }
}

/** Simulate a click on the first element matching a data attribute in the card's shadow root. */
export function click(card, selector, dataset) {
  card.sr.listeners.click({ target: { closest: (query) => (query.includes(selector) ? { dataset } : null) } });
}

export const Lights = registry.get("thermowatt-lights-card");
export const Panel = registry.get("thermowatt-panel-card");

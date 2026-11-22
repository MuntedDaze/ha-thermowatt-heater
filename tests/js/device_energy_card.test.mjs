// Behaviour of the card element itself (statistics loading, seam, shared cache, failure handling).
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis;
class FakeElement {
  attachShadow() {
    this.sr = { innerHTML: "", addEventListener() {} };
    return this.sr;
  }
}
globalThis.HTMLElement = FakeElement;
const registry = new Map();
globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c) };
const mod = await import("../../homeowner/www/thermowatt-power-flow-card.js");
const Card = registry.get("thermowatt-device-energy-card");

const ENERGY = { device_class: "energy", unit_of_measurement: "kWh", state_class: "total_increasing" };
let counter = 0;
const config = (extra = {}) => ({
  rates: [{ effective_from: "2000-01-01", offpeak: 0.1419, peak: 0.1907 }],
  tariff: { clock: "standard", utc_offset_hours: 10, peak_windows: [{ days: [0, 1, 2, 3, 4], start: "07:00", end: "10:00" }] },
  timezone: "Australia/Hobart",
  history_months: 6,
  tag: ++counter, // a distinct shared-cache key per test
  ...extra,
});
const device = (states = true) => ({
  entities: { "sensor.x_total": { platform: "tplink", device_id: "d1" } },
  states: states ? { "sensor.x_total": { state: "1", attributes: ENERGY } } : {},
  devices: { d1: { name: "Dev" } },
});
const text = (card) => card.sr.innerHTML.replace(/<style>[\s\S]*?<\/style>/, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const settle = () => new Promise((r) => setTimeout(r, 30));
// Emulates Home Assistant: rows with start >= start_time and start < end_time, 1 kWh per hour.
const statistics = (now, log) => async (message) => {
  log?.push(message);
  const from = Date.parse(message.start_time);
  const to = Date.parse(message.end_time);
  const step = message.period === "hour" ? 3600e3 : 300e3;
  const rows = [];
  for (let t = Math.ceil(from / step) * step; t < to && t <= now; t += step) rows.push({ start: t, end: t + step, change: step / 3600e3 });
  return { "sensor.x_total": rows };
};

test("the hourly and 5-minute ranges do not overlap (no hour is counted twice)", async () => {
  const now = Date.now();
  const log = [];
  const state = await mod.computeState({ ...device(), callWS: statistics(now, log) }, { ...config(), platforms: ["tplink"] });
  const hourly = log.find((m) => m.period === "hour");
  const recent = log.find((m) => m.period === "5minute");
  assert.equal(Date.parse(hourly.end_time), Date.parse(recent.start_time));
  assert.equal(Date.parse(recent.start_time) % 3600e3, 0);
  const parts = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Hobart", day: "numeric" }).format(now);
  assert.ok(Number(parts) >= 1);
  const monthKwh = state.monthly[0].data.kwh;
  const { zonedParts, localMidnight } = mod;
  const p = zonedParts(now, "Australia/Hobart");
  const expected = (now - localMidnight(p.year, p.month, 1, "Australia/Hobart")) / 3600e3;
  assert.ok(Math.abs(monthKwh - expected) <= 1.01, `${monthKwh} vs ${expected}`);
});

test("a registry device without any entity state does not break discovery", async () => {
  const found = mod.discoverDevices({ ...device(false) }, {});
  assert.equal(found.devices.length, 0);
  assert.equal(found.withoutMonitoring, 1);
});

test("a failing load backs off instead of retrying on every update, and keeps earlier data", async () => {
  let calls = 0;
  const hass = { ...device(), callWS: async () => { calls += 1; throw new Error("recorder down"); } };
  const card = new Card();
  card.setConfig(config());
  card.connectedCallback();
  for (let i = 0; i < 8; i += 1) {
    card.hass = hass;
    await settle();
  }
  assert.ok(calls <= 4, `callWS invoked ${calls} times`); // one load = a few requests, but only one load
  assert.match(text(card), /unavailable/);
});

test("parts share one statistics load", async () => {
  const log = [];
  const hass = { ...device(), callWS: statistics(Date.now(), log) };
  const cards = ["summary", "daily", "monthly", "history"].map((part) => {
    const card = new Card();
    card.setConfig(config({ tag: "shared", part }));
    card.connectedCallback();
    return card;
  });
  for (const card of cards) card.hass = hass;
  await settle();
  const first = log.length;
  for (const card of cards) card.hass = hass; // more state updates: no further queries
  await settle();
  assert.equal(log.length, first);
  assert.ok(first > 0 && first <= 8);
  assert.match(text(cards[0]), /Devices monitored/);
  assert.match(text(cards[1]), /Today/);
  assert.doesNotMatch(text(cards[1]), /Devices monitored/);
});

test("an unchanged state does not rebuild the DOM", async () => {
  const hass = { ...device(), callWS: statistics(Date.now()) };
  const card = new Card();
  card.setConfig(config());
  card.connectedCallback();
  card.hass = hass;
  await settle();
  card.hass = hass;
  const marker = "<!--keep-->";
  card.sr.innerHTML += marker;
  card.hass = hass;
  assert.ok(card.sr.innerHTML.includes(marker)); // not re-rendered
});

test("a rate without a price is rejected instead of rendering NaN", () => {
  const card = new Card();
  assert.throws(() => card.setConfig(config({ rates: [{ effective_from: "2000-01-01", offpeak: 0.14 }] })), /numeric/);
});

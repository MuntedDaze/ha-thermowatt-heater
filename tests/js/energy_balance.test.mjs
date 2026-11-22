// Whole-house energy balance and the 12-device Tapo configuration (daily / monthly counters, no lifetime counter).
import test from "node:test";
import assert from "node:assert/strict";
import { Card, HOUR, atTime, click, config, hassFor, mod, near, settle, text } from "./support/fake_ha.mjs";

const NOW = Date.parse("2026-11-22T07:20:00Z"); // Sunday 22 Nov, 18:20 in Hobart (AEDT): 18 complete hours today
const SOLAR = "sensor.goodwe_inverter_today_s_pv_generation";
const IMPORT = "sensor.goodwe_inverter_meter_total_energy_import";
const EXPORT = "sensor.goodwe_inverter_meter_total_energy_export";
const HOUSE = { solar: SOLAR, import: IMPORT, export: EXPORT, battery_present: false };
const inverter = (g = 0.5, i = 0.4, e = 0.1) => ({
  solar: { platform: "goodwe", entityId: SOLAR, kind: "energy", name: "Solar", hour: () => g },
  imp: { platform: "goodwe", entityId: IMPORT, kind: "energy", name: "Import", hour: () => i },
  exp: { platform: "goodwe", entityId: EXPORT, kind: "energy", name: "Export", hour: () => e },
});
const plug = (name, perHour, extra = {}) => ({ name, kind: "energy", hour: () => perHour, ...extra });
const withHouse = (extra = {}) => config({ house: HOUSE, ...extra });
const load = (spec, options = {}) => {
  const hass = hassFor(spec, { now: NOW, ...options });
  return { hass, state: () => atTime(NOW, () => mod.computeState(hass, withHouse())) };
};

// ---------------------------------------------------------------------------- the maths, directly
const hours = (from, count, kwh) => Array.from({ length: count }, (_, i) => ({ start: from + i * HOUR, end: from + (i + 1) * HOUR, kwh }));
const FROM = Date.parse("2026-11-21T13:00:00Z");
const END = FROM + 10 * HOUR;
const balance = (over = {}) =>
  mod.energyBalance({
    sources: { solar: { buckets: hours(FROM, 10, 1) }, import: { buckets: hours(FROM, 10, 0.6) }, export: { buckets: hours(FROM, 10, 0.2) } },
    devices: [{ name: "A", estimated: false, buckets: hours(FROM, 10, 0.5) }],
    from: FROM,
    to: FROM + 24 * HOUR,
    now: END + 1200e3,
    battery: false,
    ...over,
  });

test("battery-free balance: solar used, household, unmeasured and the three percentages", () => {
  const b = balance();
  assert.equal(b.status, "ok");
  near(b.G, 10, 1e-9);
  near(b.I, 6, 1e-9);
  near(b.E, 2, 1e-9);
  near(b.S, 8, 1e-9); // solar used = generation - export
  near(b.H, 14, 1e-9); // household = generation + import - export
  near(b.M, 5, 1e-9);
  near(b.U, 9, 1e-9); // unmeasured = household - monitored
  near(b.selfPct, 80, 1e-9); // solar used / generation
  near(b.indepPct, (8 / 14) * 100, 1e-9); // solar used / household
  near(b.monPct, (5 / 14) * 100, 1e-9); // monitored / household
  assert.equal(b.uStatus, "confirmed");
  assert.equal(b.deviceIncomplete, false);
  assert.equal(b.end, END); // the running hour is never part of the balance
});

test("the running hour and any bucket beyond the last complete hour are excluded", () => {
  const b = balance({ sources: { solar: { buckets: hours(FROM, 11, 1) }, import: { buckets: hours(FROM, 10, 0.6) }, export: { buckets: hours(FROM, 10, 0.2) } } });
  near(b.G, 10, 1e-9); // the 11th (running) hour is ignored, so every source covers the same hours
});

test("a battery that is not confirmed absent withholds the whole balance", () => {
  for (const battery of [true, "unknown", undefined]) {
    const b = balance({ battery });
    assert.equal(b.status, "withheld");
    assert.match(b.reason, /battery/);
  }
});

test("a source with an interior gap, a late start or no statistics withholds the balance with the reason", () => {
  const gap = hours(FROM, 10, 1).filter((_, i) => i !== 4);
  const late = hours(FROM, 10, 1).slice(2);
  for (const bad of [gap, late]) {
    const b = balance({ sources: { solar: { buckets: bad }, import: { buckets: hours(FROM, 10, 0.6) }, export: { buckets: hours(FROM, 10, 0.2) } } });
    assert.equal(b.status, "withheld");
    assert.match(b.reason, /solar generation statistics are incomplete/);
  }
  const none = balance({ sources: { solar: { buckets: [] }, import: { buckets: hours(FROM, 10, 0.6) }, export: { buckets: hours(FROM, 10, 0.2) } } });
  assert.match(none.reason, /solar generation has no statistics/);
  const unconfigured = balance({ sources: { solar: { buckets: hours(FROM, 10, 1) }, import: { buckets: hours(FROM, 10, 0.6) } } });
  assert.match(unconfigured.reason, /grid export: not configured/);
  const unavailable = balance({ sources: { solar: { buckets: hours(FROM, 10, 1) }, import: { reason: "sensor.x has no long-term statistics" }, export: { buckets: hours(FROM, 10, 0.2) } } });
  assert.match(unavailable.reason, /grid import: sensor.x has no long-term statistics/);
});

test("export above generation is withheld, not clamped; a difference within counter resolution is rounded with a note", () => {
  const over = balance({ sources: { solar: { buckets: hours(FROM, 10, 1) }, import: { buckets: hours(FROM, 10, 0.6) }, export: { buckets: hours(FROM, 10, 1.1) } } });
  assert.equal(over.status, "withheld");
  assert.match(over.reason, /grid export \(11\.00 kWh\) exceeds solar generation \(10\.00 kWh\)/);
  const hair = balance({ sources: { solar: { buckets: hours(FROM, 10, 1) }, import: { buckets: hours(FROM, 10, 0.6) }, export: { buckets: hours(FROM, 10, 1.02) } } });
  assert.equal(hair.status, "ok");
  assert.equal(hair.S, 0);
  assert.match(hair.notes.join(" "), /within counter resolution/);
  near(hair.H, 6, 1e-9);
});

test("monitored energy above household consumption withholds the unmeasured figure and explains why", () => {
  const b = balance({ devices: [{ name: "A", estimated: false, buckets: hours(FROM, 10, 2) }] }); // 20 kWh vs household 14 kWh
  assert.equal(b.status, "ok"); // the inverter balance itself is valid
  assert.equal(b.uStatus, "withheld");
  assert.equal(b.U, null);
  assert.equal(b.monPct, null);
  assert.match(b.uReason, /exceeds household consumption/);
  const closeEnough = balance({ devices: [{ name: "A", estimated: false, buckets: hours(FROM, 10, 1.45) }] }); // 14.5 vs 14: within error
  assert.equal(closeEnough.uStatus, "confirmed");
  assert.equal(closeEnough.U, 0);
  assert.match(closeEnough.notes.join(" "), /within measurement error/);
});

test("incomplete or missing device statistics give a lower bound and an upper bound, never a confirmed figure", () => {
  const gappy = hours(FROM, 10, 0.5).filter((_, i) => i !== 3);
  const b = balance({ devices: [{ name: "A", estimated: false, buckets: gappy }, { name: "B", estimated: false, buckets: [] }] });
  assert.equal(b.uStatus, "upper_bound");
  assert.equal(b.deviceIncomplete, true);
  assert.equal(b.devicesWithData, 1);
  assert.equal(b.devicesTotal, 2);
  near(b.M, 4.5, 1e-9); // only what was measured: a lower bound
  near(b.U, 14 - 4.5, 1e-9);
  const none = balance({ devices: [] });
  assert.equal(none.M, null);
  assert.equal(none.uStatus, "none");
  assert.equal(none.U, null);
});

test("estimated device energy is flagged and thresholds keep percentages honest", () => {
  const estimated = balance({ devices: [{ name: "Server", estimated: true, buckets: hours(FROM, 10, 0.5) }] });
  assert.equal(estimated.estimated, true);
  const tiny = balance({ sources: { solar: { buckets: hours(FROM, 10, 0.05) }, import: { buckets: hours(FROM, 10, 0.01) }, export: { buckets: hours(FROM, 10, 0.01) } }, devices: [] });
  assert.equal(tiny.selfPct, null); // under 1 kWh generated
  assert.equal(tiny.indepPct, null); // under 0.5 kWh of household consumption
});

test("a period with no complete hour is pending, not zero", () => {
  const b = balance({ now: FROM + 1800e3 });
  assert.equal(b.status, "pending");
});

// ---------------------------------------------------------------------------- the live Tapo configuration
const LIVE = [
  ["Dishwasher", 1.102, 22.1, 20],
  ["Fridge", 0.874, 18.4, 85.5],
  ["Washing Machine", 1.456, 31.2, 0],
  ["JRIG", 3.21, 60.5, 210],
  ["Server", 1.05, 24.3, 40],
  ["Dryer", 1.332, 28.7, 46.6],
  ["Network Cupboard", 0.98, 22.0, 61],
  ["Main Towel Rail", 0.512, 11.3, 7.3],
  ["Main Fan", 0.288, 6.4, 4.2],
  ["Garage", 0.402, 9.1, 12],
  ["Ensuite Towel Rail", 1.1, 25.346, 52.5],
  ["Ensuite Fan", 0.41, 23.0, 20],
];
const slug = (name) => name.toLowerCase().replaceAll(" ", "_");
/** The 12 live devices: each exposes current power (W), today's and this month's counters (kWh); no lifetime counter. */
function liveTapo({ perHour = 0.05 } = {}) {
  const spec = {};
  for (const [name] of LIVE) spec[slug(name)] = { name, kind: "energy", entityId: `sensor.${slug(name)}_this_month_s_consumption`, hour: () => perHour };
  const hass = hassFor(spec, { now: NOW });
  const counter = (state) => ({ state: String(state), attributes: { device_class: "energy", unit_of_measurement: "kWh", state_class: "total_increasing" } });
  for (const [name, day, month, watts] of LIVE) {
    const key = slug(name);
    hass.states[`sensor.${key}_this_month_s_consumption`] = counter(month);
    hass.entities[`sensor.${key}_today_s_consumption`] = { platform: "tplink", device_id: key };
    hass.states[`sensor.${key}_today_s_consumption`] = counter(day);
    hass.entities[`sensor.${key}_current_consumption`] = { platform: "tplink", device_id: key };
    hass.states[`sensor.${key}_current_consumption`] = { state: String(watts), attributes: { device_class: "power", unit_of_measurement: "W", state_class: "measurement" } };
  }
  // a finished-period counter must never be chosen
  hass.entities["sensor.dryer_yesterday_s_consumption"] = { platform: "tplink", device_id: "dryer" };
  hass.states["sensor.dryer_yesterday_s_consumption"] = counter(2.2);
  return hass;
}

test("the 12 live Tapo devices each get ONE source (the monthly counter), never daily + monthly together", async () => {
  const hass = liveTapo();
  const found = mod.discoverDevices(hass, { platforms: ["tplink"] });
  assert.equal(found.devices.length, 12);
  assert.deepEqual(found.devices.map((d) => d.name).sort(), LIVE.map(([n]) => n).sort());
  for (const device of found.devices) {
    assert.match(device.source.entityId, /_this_month_s_consumption$/);
    assert.equal(device.estimated, false);
    assert.match(device.native.day.entityId, /_today_s_consumption$/); // kept only as a cross-check
    assert.match(device.native.month.entityId, /_this_month_s_consumption$/);
  }
  // only the 12 monthly counters are queried: the daily counters and yesterday's counter are not
  const log = [];
  hass.log = log;
  const wrapped = hass.callWS;
  hass.callWS = (m) => (log.push(m), wrapped(m));
  const state = await atTime(NOW, () => mod.computeState(hass, config({ platforms: ["tplink"] })));
  const queried = new Set(log.filter((m) => m.type === "recorder/statistics_during_period").flatMap((m) => m.statistic_ids));
  assert.equal(queried.size, 12);
  for (const id of queried) assert.match(id, /_this_month_s_consumption$/);
  const month = mod.combine(state.monthly);
  const monthStart = mod.startOfLocalMonth(NOW, "Australia/Hobart");
  near(month.kwh, 12 * 0.05 * ((NOW - monthStart) / HOUR), 12 * 0.06); // 12 devices, each counted once
});

test("the devices' own counters reproduce the owner's reference snapshot (a fixture, not a hardcoded value)", () => {
  const hass = liveTapo();
  const found = mod.discoverDevices(hass, { platforms: ["tplink"] });
  const totals = mod.nativeTotals(found.devices, hass);
  near(totals.dailyKwh, 12.716, 1e-9);
  near(totals.monthlyKwh, 282.346, 1e-9);
  near(totals.powerKw * 1000, 559.1, 1e-9);
  assert.equal(totals.dailyCount, 12);
  assert.equal(totals.monthlyCount, 12);
});

test("source ranking: lifetime beats monthly beats daily; yesterday is never a source", () => {
  const entry = (tk) => ({ translation_key: tk });
  const rank = (id, tk) => mod.energyScore(id, entry(tk), { attributes: {} });
  assert.ok(rank("sensor.x_total_consumption", "total_consumption") > rank("sensor.x_this_month_s_consumption", "this_month_s_consumption"));
  assert.ok(rank("sensor.x_this_month_s_consumption", "") > rank("sensor.x_today_s_consumption", ""));
  assert.equal(mod.counterKind("sensor.x_yesterday_s_consumption", entry(""), { attributes: {} }), "skip");
  assert.equal(mod.counterKind("sensor.x_today_s_consumption", entry(""), { attributes: {} }), "day");
  assert.equal(mod.counterKind("sensor.x_this_month_s_consumption", entry(""), { attributes: {} }), "month");
  // a device that has a lifetime counter AND the resetting ones uses the lifetime counter only
  const hass = {
    entities: { "sensor.p_total": { platform: "tplink", device_id: "p" }, "sensor.p_today": { platform: "tplink", device_id: "p" }, "sensor.p_month": { platform: "tplink", device_id: "p" } },
    states: Object.fromEntries(
      ["sensor.p_total", "sensor.p_today", "sensor.p_month"].map((id) => [id, { state: "1", attributes: { device_class: "energy", unit_of_measurement: "kWh", state_class: "total_increasing" } }])
    ),
    devices: { p: { name: "P" } },
  };
  assert.equal(mod.discoverDevices(hass, {}).devices[0].source.entityId, "sensor.p_total");
});

test("cross-check: statistics agree with the device's own daily and monthly counters, and a mismatch is flagged", async () => {
  const hass = liveTapo();
  const config12 = config({ platforms: ["tplink"] });
  const first = await atTime(NOW, () => mod.computeState(hass, config12));
  // make every device's own counters equal what the statistics say
  for (const [rows, suffix] of [[first.daily, "today_s_consumption"], [first.monthly, "this_month_s_consumption"]]) {
    for (const row of rows) hass.states[`sensor.${slug(row.name)}_${suffix}`].state = String(row.data.kwh);
  }
  const agree = await atTime(NOW, () => mod.computeState(hass, config12));
  assert.equal([...agree.daily, ...agree.monthly].filter((r) => r.check && r.check.differs).length, 0);
  assert.equal([...agree.daily, ...agree.monthly].every((r) => r.check), true);
  // one device's daily counter disagrees by 1 kWh
  const dryer = agree.daily.find((r) => r.name === "Dryer");
  hass.states["sensor.dryer_today_s_consumption"].state = String(dryer.data.kwh + 1);
  const differ = await atTime(NOW, () => mod.computeState(hass, config12));
  assert.deepEqual(differ.daily.filter((r) => r.check.differs).map((r) => r.name), ["Dryer"]);
  assert.equal(differ.monthly.filter((r) => r.check.differs).length, 0);
  const card = new Card();
  card.setConfig(withHouse({ platforms: ["tplink"] }));
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  assert.match(text(card), /≠ device counter/);
});

// ---------------------------------------------------------------------------- end to end through the card
test("the card computes the balance from recorder statistics over the same complete hours", async () => {
  const { state } = load({ ...inverter(), a: plug("A", 0.2), b: plug("B", 0.1) });
  const s = await state();
  const day = s.balance.day;
  assert.equal(day.status, "ok");
  near(day.G, 9, 1e-9); // 18 complete hours x 0.5
  near(day.I, 7.2, 1e-9);
  near(day.E, 1.8, 1e-9);
  near(day.S, 7.2, 1e-9);
  near(day.H, 14.4, 1e-9);
  near(day.M, 5.4, 1e-9);
  near(day.U, 9, 1e-9);
  const month = s.balance.month;
  near(month.G, 261, 1e-6); // 522 complete hours since midnight on 1 Nov (Hobart)
  near(month.H, 417.6, 1e-6);
  near(month.M, 156.6, 1e-6);
  assert.equal(s.balanceReason, null);
  assert.equal(s.devices.some((d) => d.name === "Solar"), false); // the inverter is not a Tapo device
});

test("the newest hour is only used once its hourly row can exist, so latency never withholds or distorts the balance", async () => {
  // two minutes past the hour: the 06:00-07:00 row is not compiled yet, so the balance stops at 06:00
  const early = Date.parse("2026-11-22T07:02:00Z");
  for (const retainMs of [10 * 24 * HOUR, 0]) {
    const hass = hassFor({ ...inverter(), a: plug("A", 0.3) }, { now: early, retainMs });
    const s = await atTime(early, () => mod.computeState(hass, withHouse()));
    assert.equal(s.balance.day.status, "ok", `retainMs ${retainMs}`);
    assert.equal(s.balance.day.end, Date.parse("2026-11-22T06:00:00Z"));
    near(s.balance.day.G, 8.5, 1e-9); // 17 complete hours x 0.5, every source over the same hours
    near(s.balance.day.M, 5.1, 1e-9);
  }
  // an hourly row that is genuinely missing inside the period still withholds the balance
  const spec = { ...inverter(), a: plug("A", 0.3) };
  spec.solar.hour = (t) => (t === Date.parse("2026-11-22T02:00:00Z") ? undefined : 0.5);
  const gap = await atTime(NOW, () => mod.computeState(hassFor(spec, { now: NOW }), withHouse()));
  assert.equal(gap.balance.day.status, "withheld");
  assert.match(gap.balance.day.reason, /solar generation statistics are incomplete \(1 h without data\)/);
  // just after local midnight on the 1st: nothing is complete yet
  const midnight = Date.parse("2026-11-30T13:30:00Z"); // 1 Dec 00:30 Hobart
  const fresh = hassFor({ ...inverter() }, { now: midnight });
  const pending = await atTime(midnight, () => mod.computeState(fresh, withHouse()));
  assert.equal(pending.balance.day.status, "pending");
  assert.equal(pending.balance.month.status, "pending");
});

test("the daylight-saving day has 23 hours and the balance follows local midnight", async () => {
  const now = Date.parse("2026-10-04T10:30:00Z"); // 4 Oct 21:30 Hobart (+11): DST began at 02:00 today
  const hass = hassFor({ ...inverter(), a: plug("A", 0.3) }, { now });
  const s = await atTime(now, () => mod.computeState(hass, withHouse()));
  assert.equal(s.balance.day.from, Date.parse("2026-10-03T14:00:00Z")); // midnight was still +10
  near(s.balance.day.G, 0.5 * 20, 1e-9); // 14:00Z to 10:00Z
});

test("invalid balances are withheld in the card with the reason and no diagram", async () => {
  const hass = hassFor({ ...inverter(0.5, 0.4, 0.8), a: plug("A", 0.2) }, { now: NOW }); // export above generation
  const card = new Card();
  card.setConfig(withHouse());
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  const html = text(card);
  assert.match(html, /Balance withheld/);
  assert.match(html, /exceeds solar generation/);
  assert.equal(card.sr.innerHTML.includes("<svg class=\"sankey\""), false);
  assert.match(html, /withheld/);
});

test("the balance section: ten figures for today and the month, a Sankey diagram, a period toggle, no costs", async () => {
  const hass = hassFor({ ...inverter(), a: plug("A", 0.2), b: plug("B", 0.1) }, { now: NOW });
  const card = new Card();
  card.setConfig(withHouse({ part: "balance" }));
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  const html = text(card);
  for (const label of [
    "Solar generation",
    "Grid import",
    "Grid export",
    "Solar used directly",
    "Household consumption",
    "Monitored devices",
    "Unmeasured consumption",
    "Solar self-consumption",
    "Solar independence",
    "Monitored share of household",
  ]) {
    assert.ok(html.includes(label), label);
  }
  assert.match(html, /9\.00 kWh/); // today's generation
  assert.match(html, /261(\.0)? kWh|261\.00 kWh/); // the month's generation
  assert.match(html, /80%/); // self-consumption
  assert.match(html, /50%/); // independence
  assert.match(html, /37%|38%/); // monitored share
  assert.equal(html.includes("$"), false); // energy only: tariff-valued device costs stay separate
  assert.match(html, /no solar is attributed to individual devices/);
  assert.match(card.sr.innerHTML, /<svg class="sankey"/);
  assert.equal((card.sr.innerHTML.match(/<path /g) || []).length, 5); // solar->export, solar->house, import->house, house->devices, house->unmeasured
  assert.match(card.sr.innerHTML, /Solar 9\.00 kWh/);
  click(card, "data-balance", { balance: "month" });
  assert.match(card.sr.innerHTML, /Solar 261\.0 kWh/); // the diagram follows the toggle
  click(card, "data-balance", { balance: "day" });
  assert.match(card.sr.innerHTML, /Solar 9\.00 kWh/);
  assert.equal(html.includes("NaN"), false);
});

test("incomplete device statistics are shown as a bound in the card, not as confirmed unmeasured consumption", async () => {
  const hass = hassFor({ ...inverter(), a: plug("A", 0.2), silent: { name: "Silent", kind: "energy", hour: () => undefined, noMetadata: true } }, { now: NOW });
  const card = new Card();
  card.setConfig(withHouse({ part: "balance" }));
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  const html = text(card);
  assert.match(html, /≥ 3\.60 kWh/); // monitored: a lower bound
  assert.match(html, /≤ 10\.80 kWh/); // unmeasured: an upper bound
  assert.match(html, /1 of 2 devices have complete statistics/);
  assert.match(html, /not a confirmed figure/);
});

test("without whole-house mappings the section says so and nothing is invented", async () => {
  const hass = hassFor({ a: plug("A", 0.2) }, { now: NOW });
  const card = new Card();
  card.setConfig(config({ part: "balance" })); // no `house`
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  assert.match(text(card), /Not available: the whole-house energy mappings are not configured/);
});

test("a whole-house source without long-term statistics is named in the withheld reason", async () => {
  const spec = { ...inverter(), a: plug("A", 0.2) };
  spec.exp.noMetadata = true;
  const hass = hassFor(spec, { now: NOW });
  const s = await atTime(NOW, () => mod.computeState(hass, withHouse()));
  assert.equal(s.balance.day.status, "withheld");
  assert.match(s.balance.day.reason, new RegExp(`grid export: ${EXPORT} has no long-term statistics`));
});

test("the Sankey diagram is dependency free and only drawn for a valid balance", () => {
  assert.equal(mod.sankeySvg({ status: "withheld", reason: "x" }), "");
  const svg = mod.sankeySvg(balance());
  assert.match(svg, /^<svg class="sankey"/);
  assert.equal(svg.includes("<script"), false);
  assert.match(svg, /aria-label="Energy balance: solar 10\.0 kWh/);
  const bounded = mod.sankeySvg(balance({ devices: [] }));
  assert.equal(bounded.includes("Unmeasured"), false); // no device data: nothing is itemised
});

test("a monitored device whose statistics cannot be used makes unmeasured an upper bound, not a confirmed figure", async () => {
  const spec = { ...inverter(), a: plug("A", 0.2), odd: plug("Odd unit", 0.1, { unit: "BTU" }) };
  const s = await atTime(NOW, () => mod.computeState(hassFor(spec, { now: NOW }), withHouse()));
  assert.equal(s.unsupported, 1);
  assert.equal(s.balance.day.uStatus, "upper_bound");
  assert.equal(s.balance.day.deviceIncomplete, true);
  assert.equal(s.balance.day.devicesTotal, 2);
  assert.equal(s.balance.day.devicesWithData, 1);
});

test("weekly and yearly counters are never sources and a device name cannot change a counter's kind", () => {
  const kind = (id, tk = "") => mod.counterKind(id, { translation_key: tk }, { attributes: {} });
  assert.equal(kind("sensor.heater_this_week_s_consumption"), "skip");
  assert.equal(kind("sensor.heater_this_year_s_consumption"), "skip");
  assert.equal(kind("sensor.monthly_room_total_energy"), "lifetime"); // the NAME says monthly, the counter is a total
  assert.equal(kind("sensor.today_room_total_energy"), "lifetime");
  assert.equal(kind("sensor.dryer_this_month_s_consumption"), "month");
  assert.equal(kind("sensor.dryer_today_s_consumption"), "day");
  assert.equal(kind("sensor.x", "total_consumption"), "lifetime");
  const hass = {
    entities: Object.fromEntries(["sensor.h_this_week_energy", "sensor.h_this_month_s_consumption"].map((id) => [id, { platform: "tplink", device_id: "h" }])),
    states: Object.fromEntries(
      ["sensor.h_this_week_energy", "sensor.h_this_month_s_consumption"].map((id) => [id, { state: "1", attributes: { device_class: "energy", unit_of_measurement: "kWh", state_class: "total_increasing" } }])
    ),
    devices: { h: { name: "Heater" } },
  };
  assert.equal(mod.discoverDevices(hass, {}).devices[0].source.entityId, "sensor.h_this_month_s_consumption");
});

test("a valid balance with nothing flowing says so instead of reporting a withheld balance", async () => {
  const hass = hassFor({ ...inverter(0, 0, 0), a: plug("A", 0) }, { now: NOW });
  const card = new Card();
  card.setConfig(withHouse({ part: "balance" }));
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  const html = text(card);
  assert.match(html, /nothing to draw/);
  assert.equal(html.includes("undefined"), false);
  assert.equal(html.includes("NaN"), false);
});

test("the household label fits between the columns and links never exceed their node", () => {
  const svg = mod.sankeySvg(balance({ devices: [{ name: "A", estimated: false, buckets: hours(FROM, 10, 1.45) }] })); // monitored just above household
  assert.match(svg, />Household<\/text>/);
  assert.match(svg, />14\.0 kWh<\/text>/);
  for (const [, height] of svg.matchAll(/height="(-?[\d.]+)"/g)) assert.ok(Number(height) > 0, `non-positive height ${height}`);
  const month = mod.sankeySvg(balance({ sources: { solar: { buckets: hours(FROM, 10, 130) }, import: { buckets: hours(FROM, 10, 90) }, export: { buckets: hours(FROM, 10, 20) } }, devices: [] }));
  for (const [, x] of month.matchAll(/<text x="([\d.]+)" y="[\d.]+" text-anchor="start"/g)) assert.ok(Number(x) < 480, "label starts inside the viewBox");
});

test("the cross-check note compares the same devices over the same window", async () => {
  const hass = liveTapo();
  delete hass.states["sensor.garage_today_s_consumption"]; // one device has no readable daily counter
  const state = await atTime(NOW, () => mod.computeState(hass, config({ platforms: ["tplink"] })));
  assert.equal(state.crossCheck.day.count, 11);
  assert.equal(state.crossCheck.month.count, 12);
  const sums = (rows) => rows.filter((r) => r.check).reduce((t, r) => t + r.check.stats, 0);
  near(state.crossCheck.day.stats, sums(state.daily), 1e-9);
});

test("a malformed whole-house block disables only the balance, never the device tables", async () => {
  assert.deepEqual(mod.normalizeHouse(undefined), { house: null, problem: null });
  assert.match(mod.normalizeHouse(42).problem, /mapping/);
  assert.match(mod.normalizeHouse({ solar: 7 }).problem, /house\.solar/);
  assert.match(mod.normalizeHouse({ import: "light.kitchen" }).problem, /house\.import/);
  assert.equal(mod.normalizeHouse({ solar: SOLAR, battery_present: "maybe" }).house.battery_present, "unknown");
  const hass = hassFor({ a: plug("A", 0.2) }, { now: NOW });
  const card = new Card();
  card.setConfig(config({ part: "all", house: { solar: { not: "a string" } } }));
  card.connectedCallback();
  await atTime(NOW, async () => {
    card.hass = hass;
    await settle();
  });
  const html = text(card);
  assert.match(html, /whole-house configuration is invalid/);
  assert.match(html, /Today \(midnight/); // the device tables still render
});

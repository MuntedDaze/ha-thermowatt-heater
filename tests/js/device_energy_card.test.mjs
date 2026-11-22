// Behaviour of the Device Energy card: statistics loading, units, coverage, rates, shared cache, failures.
import test from "node:test";
import assert from "node:assert/strict";
import { Card, HOUR, TZ, config, hassFor, mod, monthLabelOf, near, one, settle, text } from "./support/fake_ha.mjs";

test("hourly statistics cover the whole history: short 5-minute retention loses no days and double counts none", async () => {
  const now = Date.now();
  const log = [];
  // only three days of 5-minute statistics retained, where the previous design assumed 9.5 days
  const hass = hassFor({ a: { name: "A", kind: "energy", hour: one } }, { now, retainMs: 3 * 24 * HOUR, log });
  const state = await mod.computeState(hass, config());
  const monthStart = mod.startOfLocalMonth(now, TZ);
  near(state.monthly[0].data.kwh, (now - monthStart) / HOUR);
  assert.equal(state.monthly[0].missingHours, 0);
  assert.equal(state.monthly[0].partialFrom, null);
  const hourly = log.find((m) => m.period === "hour");
  const recent = log.find((m) => m.period === "5minute");
  assert.ok(Date.parse(hourly.end_time) <= Date.parse(recent.start_time) + 3 * HOUR);
  assert.equal(Date.parse(hourly.end_time) % HOUR, 0);
  // the previous completed month is whole: 24 h x days in the month
  const prev = state.months.at(-1);
  const days = (mod.shiftMonth(now, 0, TZ) - mod.shiftMonth(now, -1, TZ)) / (24 * HOUR);
  near(prev.rows[0].data.kwh, days * 24, 1.01 + (days === 30 ? 1 : 0)); // DST months differ by an hour
  assert.equal(prev.partial, false);
  assert.equal(state.generatedAt >= now, true);
});

test("an hour with an hourly row is never also taken from the 5-minute rows", () => {
  const merged = mod.mergeBuckets(
    [{ start: 0, end: HOUR, kwh: 1 }],
    [
      { start: 0, end: 300e3, kwh: 0.1 }, // same hour as the hourly row: ignored
      { start: HOUR, end: HOUR + 300e3, kwh: 0.1 }, // hour with no hourly row yet: used
    ]
  );
  assert.deepEqual(merged.map((b) => b.start), [0, HOUR]);
  assert.equal(merged.reduce((t, b) => t + b.kwh, 0), 1.1);
});

test("coverage separates a recorded zero, a gap, a late start and no data", () => {
  const h = (n, kwh = 1) => ({ start: n * HOUR, end: (n + 1) * HOUR, kwh });
  const now = 10 * HOUR + 1800e3; // half way through hour 10: hours 0-9 are complete
  const full = Array.from({ length: 10 }, (_, i) => h(i));
  assert.deepEqual(mod.coverage(full, 0, 24 * HOUR, now), { expected: 10, present: 10, leading: 0, missing: 0, firstPresent: 0 });
  const gap = full.filter((_, i) => i !== 4 && i !== 5);
  assert.equal(mod.coverage(gap, 0, 24 * HOUR, now).missing, 2);
  const late = full.slice(3);
  const lateCoverage = mod.coverage(late, 0, 24 * HOUR, now);
  assert.equal(lateCoverage.leading, 3);
  assert.equal(lateCoverage.missing, 0);
  assert.equal(mod.coverage([], 0, 24 * HOUR, now).leading, 10); // no data at all
  // an hour fed by 5-minute rows counts only when all twelve are present; the running hour is never expected
  const fine = (n, count) => Array.from({ length: count }, (_, i) => ({ start: n * HOUR + i * 300e3, end: n * HOUR + (i + 1) * 300e3, kwh: 0.1 }));
  assert.equal(mod.coverage([...full.slice(0, 9), ...fine(9, 12)], 0, 24 * HOUR, now).missing, 0);
  assert.equal(mod.coverage([...full.slice(0, 9), ...fine(9, 11)], 0, 24 * HOUR, now).missing, 1);
  const zero = mod.accumulate([h(0, 0)], { from: 0, to: HOUR, tariff: config().tariff, rates: config().rates, timeZone: TZ });
  assert.equal(zero.kwh, 0); // a recorded zero is data, not "no data"
  assert.equal(mod.accumulate([], { from: 0, to: HOUR, tariff: config().tariff, rates: config().rates, timeZone: TZ }), null);
});

test("interior gaps, late starts and devices without statistics make the aggregate incomplete, never zero", async () => {
  const now = Date.now();
  const prevStart = mod.shiftMonth(now, -1, TZ);
  const hass = hassFor(
    {
      whole: { name: "Whole", kind: "energy", hour: one },
      gappy: { name: "Gappy", kind: "energy", hour: (t) => (t >= prevStart + 10 * 24 * HOUR && t < prevStart + 10 * 24 * HOUR + 5 * HOUR ? undefined : 1) },
      late: { name: "Late", kind: "energy", hour: (t) => (t < prevStart + 5 * 24 * HOUR ? undefined : 1) },
      silent: { name: "Silent", kind: "energy", hour: () => undefined, noMetadata: true },
    },
    { now }
  );
  const state = await mod.computeState(hass, config());
  const prev = state.months.at(-1);
  const row = (name) => prev.rows.find((r) => r.name === name);
  assert.equal(row("Gappy").missingHours, 5);
  assert.equal(row("Gappy").data.kwh > 0, true);
  assert.ok(row("Late").partialFrom);
  assert.equal(row("Late").missingHours, 0);
  assert.equal(row("Silent").data, null); // no statistics: not zero
  assert.equal(row("Whole").missingHours, 0);
  assert.equal(prev.partial, true);
  assert.equal(prev.total.missing, 1);
  assert.equal(prev.total.devices, 3); // the silent device is not part of the total
  assert.equal(state.monthly.find((r) => r.name === "Whole").partialFrom, null);
  // rendered: badges, "no statistics (not zero)" and an "incomplete" total
  const card = new Card();
  card.setConfig(config());
  card.connectedCallback();
  card.hass = hass;
  await settle();
  const html = text(card);
  assert.match(html, /no statistics \(not zero\)/);
  assert.match(html, /incomplete/);
  assert.match(html, /partial/);
});

test("statistics units come from the recorder metadata, not the live sensor", async () => {
  const now = Date.now();
  const hass = hassFor(
    {
      wh: { name: "Wh plug", kind: "energy", unit: "Wh", hour: () => 1000 }, // 1 kWh per hour
      mwh: { name: "MWh meter", kind: "energy", unit: "MWh", hour: () => 0.001 }, // 1 kWh per hour
      kwh: { name: "kWh plug", kind: "energy", unit: "kWh", hour: one },
      watts: { name: "Watt plug", kind: "power", unit: "W", hour: () => 1000 }, // 1 kW for an hour
      kilowatts: { name: "kW plug", kind: "power", unit: "kW", hour: one },
      odd: { name: "Odd unit", kind: "energy", unit: "BTU", hour: one },
    },
    { now }
  );
  const state = await mod.computeState(hass, config());
  const prevKwh = (name) => state.months.at(-1).rows.find((r) => r.name === name).data.kwh;
  for (const name of ["Wh plug", "MWh meter", "kWh plug", "Watt plug", "kW plug"]) near(prevKwh(name), prevKwh("kWh plug"), 0.5);
  assert.equal(state.unsupported, 1);
  assert.equal(state.devices.some((d) => d.name === "Odd unit"), false); // not guessed
  assert.equal(state.devices.find((d) => d.name === "Wh plug").source.factor, 0.001);
  const watts = state.devices.find((d) => d.name === "Watt plug");
  assert.equal(watts.estimated, true);
  // the live sensor says kWh for the Wh statistics: the metadata wins
  assert.equal(hass.states["sensor.wh_energy"].attributes.unit_of_measurement, "kWh");
});

test("rates: unconfirmed start dates are labelled assumed, history is never silently re-priced, no rate means no cost", () => {
  const undated = [{ effective_from: null, offpeak: 0.1419, peak: 0.1907 }];
  const may = Date.UTC(2026, 4, 15, 3);
  assert.deepEqual(mod.ratesAt(may, undated, TZ), { effective_from: null, offpeak: 0.1419, peak: 0.1907, assumed: true });
  const dated = [{ effective_from: "2026-07-01", offpeak: 0.15, peak: 0.2 }];
  assert.equal(mod.ratesAt(may, dated, TZ).assumed, true); // before the first dated price: valued at it, flagged
  assert.equal(mod.ratesAt(Date.UTC(2026, 8, 1), dated, TZ).assumed, false);
  assert.equal(mod.ratesAt(may, [], TZ), null);
  const bucket = [{ start: may, end: may + HOUR, kwh: 2 }];
  const range = { from: may - HOUR, to: may + HOUR, tariff: config().tariff, timeZone: TZ };
  const priced = mod.accumulate(bucket, { ...range, rates: undated });
  assert.equal(priced.assumed, true);
  assert.ok(priced.cost > 0);
  const unpriced = mod.accumulate(bucket, { ...range, rates: [] });
  assert.equal(unpriced.kwh, 2);
  assert.equal(unpriced.cost, null); // withheld, never zero
  assert.equal(mod.fmtMoney(unpriced.cost), "—");
  assert.equal(mod.fmtMoney(1.234, true), "≈$1.23");
  assert.equal(mod.combine([{ data: unpriced }, { data: priced }]).cost, null);
});

test("rate entries are validated", () => {
  const ok = { effective_from: "2026-07-01", offpeak: 0.1, peak: 0.2 };
  assert.doesNotThrow(() => mod.validateRates([ok, { effective_from: null, offpeak: 0, peak: 0 }]));
  for (const bad of [
    [],
    [{ ...ok, offpeak: -0.1 }],
    [{ ...ok, peak: NaN }],
    [{ ...ok, peak: Infinity }],
    [{ ...ok, offpeak: undefined }],
    [{ ...ok, peak: "cheap" }],
    [{ ...ok, effective_from: "2026-02-30" }],
    [{ ...ok, effective_from: "1 July 2026" }],
    [ok, ok],
    [{ ...ok, effective_from: null }, { ...ok, effective_from: null }],
  ]) {
    assert.throws(() => mod.validateRates(bad), undefined, JSON.stringify(bad));
  }
  const card = new Card();
  assert.throws(() => card.setConfig(config({ rates: [{ effective_from: null, offpeak: 0.14 }] })), /peak/);
});

test("a registry device without any entity state does not break discovery", () => {
  const found = mod.discoverDevices(
    { entities: { "sensor.x_total": { platform: "tplink", device_id: "d1" } }, states: {}, devices: { d1: { name: "Dev" } } },
    {}
  );
  assert.equal(found.devices.length, 0);
  assert.equal(found.withoutMonitoring, 1);
});

test("a failing load backs off instead of retrying on every update", async () => {
  let calls = 0;
  const hass = { ...hassFor({ a: { name: "A", kind: "energy", hour: one } }), callWS: async () => { calls += 1; throw new Error("recorder down"); } };
  const card = new Card();
  card.setConfig(config());
  card.connectedCallback();
  for (let i = 0; i < 8; i += 1) {
    card.hass = hass;
    await settle();
  }
  assert.ok(calls <= 2, `callWS invoked ${calls} times`); // one load fails at its first request, then it backs off
  assert.match(text(card), /unavailable/);
});

test("when a refresh fails the last good data stays with the time it was loaded", async () => {
  const good = hassFor({ a: { name: "Alpha", kind: "energy", hour: one } });
  const card = new Card();
  card.setConfig(config({ refresh_minutes: 0 }));
  card.connectedCallback();
  card.hass = good;
  await settle();
  assert.match(text(card), /Alpha/);
  card.hass = { ...good, callWS: async () => { throw new Error("recorder down"); } };
  await settle();
  const html = text(card);
  assert.match(html, /Latest refresh failed \(recorder down\)\. Showing statistics last loaded at/);
  assert.match(html, /Alpha/); // still showing the previous figures
  assert.match(html, /Statistics as of/);
});

test("parts share one statistics load", async () => {
  const hass = hassFor({ a: { name: "A", kind: "energy", hour: one } });
  const cards = ["summary", "daily", "monthly", "history"].map((part) => {
    const card = new Card();
    card.setConfig(config({ tag: "shared", part }));
    card.connectedCallback();
    return card;
  });
  for (const card of cards) card.hass = hass;
  await settle();
  const first = hass.log.length;
  for (const card of cards) card.hass = hass; // more state updates: no further queries
  await settle();
  assert.equal(hass.log.length, first);
  assert.ok(first > 0 && first <= 8);
  assert.match(text(cards[0]), /Devices monitored/);
  assert.match(text(cards[1]), /Today/);
  assert.doesNotMatch(text(cards[1]), /Devices monitored/);
});

test("an unchanged state does not rebuild the DOM", async () => {
  const hass = hassFor({ a: { name: "A", kind: "energy", hour: one } });
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

test("the previous-months table says it is reconstructed, and assumed rates are marked", async () => {
  const hass = hassFor({ a: { name: "A", kind: "energy", hour: one } });
  const card = new Card();
  card.setConfig(config({ rates: [{ effective_from: null, offpeak: 0.1419, peak: 0.1907 }] }));
  card.connectedCallback();
  card.hass = hass;
  await settle();
  const html = text(card);
  assert.match(html, /Reconstructed from long-term statistics/);
  assert.match(html, /not archived monthly totals/);
  assert.match(html, /≈\$\d/);
  assert.match(html, /assumed/);
  assert.match(html, new RegExp(monthLabelOf(-1, Date.now())));
});

import test from "node:test";
import assert from "node:assert/strict";
import {
  accumulate,
  combine,
  discoverDevices,
  fmtKwh,
  fmtMoney,
  localMidnight,
  monthLabel,
  ratesAt,
  shiftDay,
  shiftMonth,
  sortRows,
  startOfLocalDay,
  startOfLocalMonth,
  tariffAt,
  toBuckets,
  zonedParts,
} from "../../homeowner/www/thermowatt-power-flow-card.js";

const TZ = "Australia/Hobart";
const TARIFF = {
  clock: "standard",
  utc_offset_hours: 10,
  peak_windows: [
    { days: [0, 1, 2, 3, 4], start: "07:00", end: "10:00" },
    { days: [0, 1, 2, 3, 4], start: "16:00", end: "21:00" },
  ],
};
const RATES = [{ effective_from: "2000-01-01", offpeak: 0.1419, peak: 0.1907 }];
const utc = (text) => Date.parse(text);
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

// ------------------------------------------------------------------ discovery
function registry() {
  const entities = {
    // P110 style device with every counter: lifetime, today, month, plus power
    "sensor.dryer_total_consumption": { platform: "tplink", device_id: "d1", translation_key: "total_consumption" },
    "sensor.dryer_today_s_consumption": { platform: "tplink", device_id: "d1", translation_key: "today_s_consumption" },
    "sensor.dryer_this_month_s_consumption": { platform: "tplink", device_id: "d1", translation_key: "this_month_s_consumption" },
    "sensor.dryer_current_consumption": { platform: "tplink", device_id: "d1", translation_key: "current_consumption" },
    // device that only reports power
    "sensor.server_current_consumption": { platform: "tplink", device_id: "d2" },
    // Tapo device with NO energy capability (a bulb): must never appear as zero consumption
    "light.hall": { platform: "tplink", device_id: "d3" },
    // another platform, ignored
    "sensor.other_energy": { platform: "shelly", device_id: "d4" },
    // hidden duplicate
    "sensor.dryer_total_consumption_2": { platform: "tplink", device_id: "d1", hidden: true },
    // custom-integration style naming, no translation keys
    "sensor.fridge_total_energy": { platform: "tapo", device_id: "d5" },
    "sensor.fridge_today_energy": { platform: "tapo", device_id: "d5" },
  };
  const kwh = (cls = "energy", klass = "total_increasing", unit = "kWh") => ({ state: "1", attributes: { device_class: cls, state_class: klass, unit_of_measurement: unit } });
  const states = {
    "sensor.dryer_total_consumption": kwh(),
    "sensor.dryer_today_s_consumption": kwh(),
    "sensor.dryer_this_month_s_consumption": kwh(),
    "sensor.dryer_current_consumption": kwh("power", "measurement", "W"),
    "sensor.server_current_consumption": kwh("power", "measurement", "W"),
    "light.hall": { state: "on", attributes: {} },
    "sensor.other_energy": kwh(),
    "sensor.dryer_total_consumption_2": kwh(),
    "sensor.fridge_total_energy": kwh("energy", "total_increasing", "Wh"),
    "sensor.fridge_today_energy": kwh("energy", "total_increasing", "Wh"),
  };
  const devices = {
    d1: { name: "Tapo P110", name_by_user: "Dryer" },
    d2: { name: "Server plug" },
    d3: { name: "Hall light" },
    d4: { name: "Shelly" },
    d5: { name: "Fridge plug", name_by_user: null },
  };
  return { entities, states, devices };
}

test("discovery uses registries, real device names and one source per device", () => {
  const { devices, withoutMonitoring } = discoverDevices(registry(), {});
  assert.deepEqual(devices.map((d) => d.name), ["Dryer", "Fridge plug", "Server plug"]);
  const dryer = devices.find((d) => d.name === "Dryer");
  // the lifetime counter, never today/month, and never several counters of one device added together
  assert.equal(dryer.source.entityId, "sensor.dryer_total_consumption");
  assert.equal(dryer.source.kind, "energy");
  assert.equal(dryer.estimated, false);
  assert.equal(devices.find((d) => d.name === "Fridge plug").source.entityId, "sensor.fridge_total_energy");
  assert.equal(devices.find((d) => d.name === "Fridge plug").source.factor, 0.001); // Wh -> kWh
  assert.equal(withoutMonitoring, 1); // the bulb: counted, never listed with zero kWh
});

test("a power-only device is used and flagged as an estimate", () => {
  const server = discoverDevices(registry(), {}).devices.find((d) => d.name === "Server plug");
  assert.equal(server.source.kind, "power");
  assert.equal(server.estimated, true);
  assert.equal(server.source.factor, 0.001); // W -> kW
});

test("only configured platforms are considered; nothing is hardcoded", () => {
  const onlyTapo = discoverDevices(registry(), { platforms: ["tapo"] }).devices;
  assert.deepEqual(onlyTapo.map((d) => d.name), ["Fridge plug"]);
  assert.deepEqual(discoverDevices({ entities: {}, states: {}, devices: {} }, {}).devices, []);
});

test("devices can be excluded by name, entity id or label, or the list limited", () => {
  const reg = registry();
  reg.entities["sensor.server_current_consumption"].labels = ["no_energy_report"];
  assert.deepEqual(discoverDevices(reg, { exclude: ["dryer"] }).devices.map((d) => d.name), ["Fridge plug", "Server plug"]);
  assert.deepEqual(discoverDevices(reg, { exclude: ["sensor.fridge_total_energy"] }).devices.map((d) => d.name), ["Dryer", "Server plug"]);
  assert.deepEqual(discoverDevices(reg, { exclude_label: "no_energy_report" }).devices.map((d) => d.name), ["Dryer", "Fridge plug"]);
  assert.deepEqual(discoverDevices(reg, { include_only: ["Fridge plug"] }).devices.map((d) => d.name), ["Fridge plug"]);
});

test("a renamed device is shown under its new name and keeps its source", () => {
  const reg = registry();
  reg.devices.d1.name_by_user = "Clothes dryer";
  const dryer = discoverDevices(reg, {}).devices.find((d) => d.name === "Clothes dryer");
  assert.equal(dryer.deviceId, "d1");
});

test("an energy sensor with the wrong unit or no state class is ignored, not guessed", () => {
  const reg = registry();
  reg.states["sensor.dryer_total_consumption"].attributes.unit_of_measurement = "A";
  reg.states["sensor.dryer_today_s_consumption"].attributes.state_class = "measurement";
  reg.states["sensor.dryer_this_month_s_consumption"].attributes.state_class = undefined;
  const dryer = discoverDevices(reg, {}).devices.find((d) => d.name === "Dryer");
  assert.equal(dryer.source.kind, "power"); // fell back to measured power, flagged as estimate
});

// ------------------------------------------------------------------ Australia/Hobart days and months
test("local days: normal, daylight-saving start (23 h) and end (25 h)", () => {
  const hours = (from) => (shiftDay(from, 1, TZ) - from) / 3600e3;
  const normal = startOfLocalDay(utc("2026-11-22T05:00:00Z"), TZ);
  assert.equal(hours(normal), 24);
  assert.equal(zonedParts(normal, TZ).hour, 0);
  const dstStart = localMidnight(2026, 10, 4, TZ); // clocks go forward at 02:00
  assert.equal(hours(dstStart), 23);
  const dstEnd = localMidnight(2026, 4, 5, TZ); // clocks go back at 03:00
  assert.equal(hours(dstEnd), 25);
  assert.equal(zonedParts(dstEnd, TZ).hour, 0);
});

test("month boundaries follow the Hobart calendar, including the year boundary", () => {
  const now = utc("2026-12-31T20:00:00Z"); // 1 Jan 2027 07:00 in Hobart (AEDT)
  assert.equal(zonedParts(now, TZ).year, 2027);
  const start = startOfLocalMonth(now, TZ);
  assert.deepEqual([zonedParts(start, TZ).year, zonedParts(start, TZ).month, zonedParts(start, TZ).day, zonedParts(start, TZ).hour], [2027, 1, 1, 0]);
  const dec = shiftMonth(now, -1, TZ);
  assert.deepEqual([zonedParts(dec, TZ).year, zonedParts(dec, TZ).month], [2026, 12]);
  assert.equal((start - dec) / 86400e3, 31);
  assert.equal(monthLabel(dec, TZ), "December 2026");
  // February in a non-leap year
  assert.equal((shiftMonth(utc("2026-03-10T00:00:00Z"), 0, TZ) - shiftMonth(utc("2026-03-10T00:00:00Z"), -1, TZ)) / 86400e3, 28);
});

test("midnight rollover: 23:59 and 00:01 Hobart time fall on different days", () => {
  const before = utc("2026-11-22T12:59:00Z"); // 23:59 AEDT on the 22nd
  const after = utc("2026-11-22T13:01:00Z"); // 00:01 AEDT on the 23rd
  assert.notEqual(startOfLocalDay(before, TZ), startOfLocalDay(after, TZ));
  assert.equal(startOfLocalDay(after, TZ), utc("2026-11-22T13:00:00Z"));
});

// ------------------------------------------------------------------ tariff allocation
test("peak windows follow the fixed-AEST tariff clock, on weekdays only", () => {
  const at = (iso) => tariffAt(utc(iso), TARIFF, TZ);
  // Monday 23 Nov 2026. AEST = UTC+10; Hobart is AEDT (UTC+11) so local time is one hour later.
  assert.equal(at("2026-11-22T20:59:00Z"), "offpeak"); // 06:59 AEST
  assert.equal(at("2026-11-22T21:00:00Z"), "peak"); // 07:00 AEST = 08:00 Hobart local
  assert.equal(at("2026-11-23T00:00:00Z"), "offpeak"); // 10:00 AEST
  assert.equal(at("2026-11-23T05:59:00Z"), "offpeak"); // 15:59 AEST
  assert.equal(at("2026-11-23T06:00:00Z"), "peak"); // 16:00 AEST
  assert.equal(at("2026-11-23T10:59:00Z"), "peak");
  assert.equal(at("2026-11-23T11:00:00Z"), "offpeak"); // 21:00 AEST
  // Saturday 28 Nov: never peak
  assert.equal(at("2026-11-27T21:00:00Z"), "offpeak");
  assert.equal(at("2026-11-28T06:00:00Z"), "offpeak");
  // Friday night into Saturday morning
  assert.equal(at("2026-11-26T21:00:00Z"), "peak"); // Fri 07:00 AEST
  assert.equal(at("2026-11-27T21:00:00Z"), "offpeak"); // Sat 07:00 AEST
});

test("the same peak window is used in winter and summer (daylight saving does not move it)", () => {
  // Monday 6 July 2026 (AEST = Hobart standard time): 07:00 local = 21:00Z previous day
  assert.equal(tariffAt(utc("2026-07-05T21:00:00Z"), TARIFF, TZ), "peak");
  // Monday 23 Nov (AEDT): 07:00 local is NOT peak, 08:00 local is
  assert.equal(tariffAt(utc("2026-11-22T20:00:00Z"), TARIFF, TZ), "offpeak"); // 07:00 AEDT = 06:00 AEST
  assert.equal(tariffAt(utc("2026-11-22T21:00:00Z"), TARIFF, TZ), "peak"); // 08:00 AEDT
});

test("a local-clock tariff follows Hobart local time", () => {
  const local = { ...TARIFF, clock: "local" };
  assert.equal(tariffAt(utc("2026-11-22T20:00:00Z"), local, TZ), "peak"); // 07:00 AEDT
});

test("energy is allocated to the tariff in force when it was consumed, bucket by bucket", () => {
  // Monday 23 Nov, 5-minute buckets straddling 07:00 AEST (= 21:00Z): 1 kWh before, 1 kWh after
  const buckets = [
    { start: utc("2026-11-22T20:55:00Z"), end: utc("2026-11-22T21:00:00Z"), kwh: 1 },
    { start: utc("2026-11-22T21:00:00Z"), end: utc("2026-11-22T21:05:00Z"), kwh: 1 },
  ];
  const r = accumulate(buckets, { from: utc("2026-11-22T13:00:00Z"), to: utc("2026-11-23T13:00:00Z"), tariff: TARIFF, rates: RATES, timeZone: TZ });
  near(r.offKwh, 1);
  near(r.peakKwh, 1);
  near(r.offCost, 0.1419);
  near(r.peakCost, 0.1907);
  near(r.cost, 0.3326);
});

test("a day of constant 1 kW is costed hour by hour, not at the current tariff", () => {
  const buckets = [];
  const start = utc("2026-11-22T13:00:00Z"); // Mon 23 Nov 00:00 Hobart
  for (let h = 0; h < 24; h += 1) buckets.push({ start: start + h * 3600e3, end: start + (h + 1) * 3600e3, kwh: 1 });
  const r = accumulate(buckets, { from: start, to: start + 24 * 3600e3, tariff: TARIFF, rates: RATES, timeZone: TZ });
  near(r.kwh, 24);
  near(r.peakKwh, 8); // 3 h morning + 5 h evening
  near(r.offKwh, 16);
  near(r.cost, 16 * 0.1419 + 8 * 0.1907);
});

test("a 23-hour and a 25-hour day each count only their own hours", () => {
  for (const [y, m, d, hours] of [[2026, 10, 4, 23], [2026, 4, 5, 25]]) {
    const from = localMidnight(y, m, d, TZ);
    const to = shiftDay(from, 1, TZ);
    const buckets = [];
    for (let t = from - 3600e3; t < to + 3600e3; t += 3600e3) buckets.push({ start: t, end: t + 3600e3, kwh: 1 });
    near(accumulate(buckets, { from, to, tariff: TARIFF, rates: RATES, timeZone: TZ }).kwh, hours);
  }
});

test("a price change applies only from its effective date; history keeps the old rate", () => {
  const rates = [
    { effective_from: "2000-01-01", offpeak: 0.1419, peak: 0.1907 },
    { effective_from: "2027-01-01", offpeak: 0.2, peak: 0.3 },
  ];
  const old = utc("2026-12-30T00:00:00Z"); // off-peak (Wed 11:00 AEST)
  const bucket = (start) => [{ start, end: start + 3600e3, kwh: 1 }];
  const range = { from: old - 86400e3 * 3, to: old + 86400e3 * 30, tariff: TARIFF, rates, timeZone: TZ };
  near(accumulate(bucket(old), range).cost, 0.1419); // before the change: unchanged
  near(accumulate(bucket(utc("2027-01-05T00:00:00Z")), range).cost, 0.2);
  assert.equal(ratesAt(utc("2026-12-31T12:00:00Z"), rates, TZ).offpeak, 0.1419); // 31 Dec 23:00 Hobart
  assert.equal(ratesAt(utc("2026-12-31T13:00:00Z"), rates, TZ).offpeak, 0.2); // 1 Jan 00:00 Hobart
});

// ------------------------------------------------------------------ data quality
test("missing, negative or invalid readings are skipped and never become zero", () => {
  const source = { kind: "energy", factor: 1 };
  const rows = [
    { start: 0, end: 3600e3, change: null },
    { start: 3600e3, end: 7200e3, change: undefined },
    { start: 7200e3, end: 10800e3, change: -4 },
    { start: 10800e3, end: 14400e3, change: "x" },
    { start: 14400e3, end: 18000e3, change: 0.5 },
  ];
  assert.deepEqual(toBuckets(rows, source).map((b) => b.kwh), [0.5]);
  assert.equal(accumulate([], { from: 0, to: 1e9, tariff: TARIFF, rates: RATES, timeZone: TZ }), null);
  assert.equal(accumulate(toBuckets([{ start: 0, end: 3600e3, change: null }], source), { from: 0, to: 1e9, tariff: TARIFF, rates: RATES, timeZone: TZ }), null);
});

test("device counter resets are already folded into statistics `change`: a reset day adds up", () => {
  // counter 9.8 -> 10.0 (+0.2), device reset to 0.0, +0.3: statistics report +0.2, +0.0 (reset), +0.3
  const base = utc("2026-11-22T13:00:00Z");
  const rows = [0.2, 0.0, 0.3].map((change, i) => ({ start: base + i * 3600e3, end: base + (i + 1) * 3600e3, change }));
  near(accumulate(toBuckets(rows, { kind: "energy", factor: 1 }), { from: base, to: base + 86400e3, tariff: TARIFF, rates: RATES, timeZone: TZ }).kwh, 0.5);
});

test("power-only devices integrate mean power over each bucket and are estimates", () => {
  const base = utc("2026-11-22T13:00:00Z");
  const rows = [
    { start: base, end: base + 3600e3, mean: 500 }, // 500 W for an hour
    { start: base + 3600e3, end: base + 3600e3 + 300e3, mean: 1200 }, // 1.2 kW for 5 minutes
  ];
  const b = toBuckets(rows, { kind: "power", factor: 0.001 });
  near(b[0].kwh, 0.5);
  near(b[1].kwh, 0.1);
});

test("statistics timestamps may be milliseconds, seconds or ISO strings", () => {
  const s = { kind: "energy", factor: 1 };
  const ms = toBuckets([{ start: 1.7e12, end: 1.7e12 + 3600e3, change: 1 }], s);
  const sec = toBuckets([{ start: 1.7e9, end: 1.7e9 + 3600, change: 1 }], s);
  const iso = toBuckets([{ start: "2026-11-22T13:00:00Z", end: "2026-11-22T14:00:00Z", change: 1 }], s);
  assert.equal(ms.length + sec.length + iso.length, 3);
  assert.equal(sec[0].start, 1.7e12);
});

test("totals count devices without data instead of treating them as zero", () => {
  const rows = [
    { name: "a", data: { kwh: 1, offCost: 0.1, peakCost: 0.2, cost: 0.3 } },
    { name: "b", data: null },
    { name: "c", estimated: true, data: { kwh: 2, offCost: 0.2, peakCost: 0.1, cost: 0.3 } },
  ];
  const t = combine(rows);
  assert.equal(t.devices, 2);
  assert.equal(t.missing, 1);
  near(t.kwh, 3);
  near(t.cost, 0.6);
  assert.equal(t.estimated, true);
  assert.equal(combine([{ name: "b", data: null }]), null);
});

test("a month that started mid-way is reported only for the recorded part", () => {
  const monthStart = utc("2026-10-31T13:00:00Z"); // 1 Nov 00:00 Hobart
  const buckets = [];
  for (let h = 24 * 10; h < 24 * 12; h += 1) buckets.push({ start: monthStart + h * 3600e3, end: monthStart + (h + 1) * 3600e3, kwh: 0.1 });
  const r = accumulate(buckets, { from: monthStart, to: monthStart + 30 * 86400e3, tariff: TARIFF, rates: RATES, timeZone: TZ });
  near(r.kwh, 4.8);
  assert.ok(r.firstStart > monthStart + 3600e3); // the card marks this as partial from 11 Nov
});

// ------------------------------------------------------------------ presentation helpers
test("energy to a sensible precision and costs to two decimals", () => {
  assert.equal(fmtKwh(0.1234), "0.123 kWh");
  assert.equal(fmtKwh(12.3456), "12.35 kWh");
  assert.equal(fmtKwh(null), "—");
  assert.equal(fmtMoney(1.005 + 0.2), "$1.20");
  assert.equal(fmtMoney(0), "$0.00");
  assert.equal(fmtMoney(undefined), "—");
});

test("sorting: by value both ways, rows without data always last", () => {
  const rows = [
    { name: "b", data: { kwh: 2, cost: 1 } },
    { name: "none", data: null },
    { name: "a", data: { kwh: 5, cost: 0.5 } },
  ];
  assert.deepEqual(sortRows(rows, "kwh", "desc").map((r) => r.name), ["a", "b", "none"]);
  assert.deepEqual(sortRows(rows, "kwh", "asc").map((r) => r.name), ["b", "a", "none"]);
  assert.deepEqual(sortRows(rows, "cost", "desc").map((r) => r.name), ["b", "a", "none"]);
  assert.deepEqual(sortRows(rows, "name", "asc").map((r) => r.name), ["a", "b", "none"]);
});

// The tablet Home page models, the lights diagnostics, solar-used-directly and the gap listing for the balance.
import test from "node:test";
import assert from "node:assert/strict";
import { HOUR, mod } from "./support/fake_ha.mjs";

const st = (state, attributes = {}) => ({ state, attributes });

// ----------------------------------------------------------------------------- solar boost wording
test("solar boost reads Active, Waiting or Off, in the integration's own words", () => {
  assert.deepEqual(mod.solarBoostLabel("Active", "on"), { text: "Active", tone: "ok" });
  assert.equal(mod.solarBoostLabel("Waiting", "on").text, "Waiting");
  assert.equal(mod.solarBoostLabel("Waiting to restart", "on").text, "Waiting"); // cooldown
  assert.equal(mod.solarBoostLabel("OFF unconfirmed", "on").text, "Stopping");
  assert.equal(mod.solarBoostLabel("Active", "off").text, "Off"); // the setting wins: boosting is disabled
  assert.equal(mod.solarBoostLabel(undefined, "on").text, "—"); // unknown is a dash, not a guess
});

// ----------------------------------------------------------------------------- hot water card
const HW = {
  temperature: "sensor.t", mode: "sensor.mode", target: "sensor.target", automatic: "switch.auto", operating: "sensor.op",
  tariff: "sensor.tariff", boost: "sensor.boost", boost_enabled: "switch.boost", next_action: "sensor.next", last_poll: "sensor.last", next_poll: "sensor.poll",
};
const hwStates = (over = {}) => ({
  "sensor.t": st("52.44"), "sensor.mode": st("manual"), "sensor.target": st("62.0"), "switch.auto": st("on"), "sensor.op": st("automatic"),
  "sensor.tariff": st("off_peak"), "sensor.boost": st("Waiting"), "switch.boost": st("on"), "sensor.next": st("normal_storage_62"),
  "sensor.last": st("2026-11-22T03:05:00+00:00"), "sensor.poll": st("2026-11-22T03:30:00+00:00"), ...over,
});

test("the hot-water card shows temperature, heater, tariff, boost, polls and the next action in plain English", () => {
  const m = mod.hotWaterModel({ states: hwStates() }, HW, "Australia/Hobart");
  assert.equal(m.temperature, "52.4");
  assert.equal(m.mode, "Manual");
  assert.equal(m.target, 62);
  assert.deepEqual(m.control, { text: "Automatic on", tone: "ok" });
  assert.deepEqual(m.tariff, { text: "Off-peak", tone: "ok" });
  assert.equal(m.boost.text, "Waiting");
  assert.equal(m.nextAction, "Heat to 62 °C");
  assert.equal(m.lastPoll, "14:05"); // 03:05 UTC = 14:05 AEDT
  assert.equal(m.nextPoll, "14:30");
  assert.ok(!JSON.stringify(m).includes("_"), "no internal identifiers");
});

test("hot-water status: override, automatic off, and unavailable data are shown honestly", () => {
  const model = (over) => mod.hotWaterModel({ states: hwStates(over) }, HW);
  assert.deepEqual(model({ "sensor.op": st("guest") }).control, { text: "12 h override", tone: "warn" });
  assert.deepEqual(model({ "switch.auto": st("off") }).control, { text: "Automatic off", tone: "warn" });
  assert.equal(model({ "switch.auto": st("unavailable") }).control.text, "Status unknown");
  const blank = model({ "sensor.t": st("unavailable"), "sensor.last": st("unknown"), "sensor.next": st("unavailable"), "sensor.tariff": st("unavailable") });
  assert.equal(blank.temperature, null); // a dash on screen, never 0
  assert.equal(blank.lastPoll, null);
  assert.equal(blank.nextAction, null);
  assert.equal(blank.tariff.text, "—");
  assert.equal(model({ "switch.boost": st("off") }).boost.text, "Off");
});

// ----------------------------------------------------------------------------- manual fan button
test("the fan button runs for the configured minutes, cancels with the time left, and is inert when status is unknown", () => {
  assert.deepEqual(mod.fanButton("off", null, 20, "off"), { kind: "run", label: "Run fan — 20 min" });
  assert.equal(mod.fanButton("off", null, 45, "on").label, "Run fan — 45 min"); // the Bathrooms-page setting shows here
  assert.equal(mod.fanButton("off", null, undefined, "off").label, "Run fan — 20 min"); // the documented default
  assert.deepEqual(mod.fanButton("on", 17 * 60 - 20, 20, "on"), { kind: "cancel", label: "Cancel fan — 17 min left" });
  assert.equal(mod.fanButton("on", 30, 20, "on").label, "Cancel fan — 1 min left");
  assert.equal(mod.fanButton("on", null, 20, "on").label, "Cancel fan");
  assert.equal(mod.fanButton("unavailable", null, 20, "off").kind, "inert");
  assert.equal(mod.fanButton("off", null, 20, "unknown").kind, "inert"); // never a command on an unknown state
});

// ----------------------------------------------------------------------------- bathroom card
const BATH = {
  name: "Main Bathroom", humidity: "sensor.h", temperature: "sensor.bt", shower: "binary_sensor.s", fan_running: "binary_sensor.f",
  towel_heating: "binary_sensor.w", towel_remaining: "sensor.r", fan_switch: "switch.m",
};
const bathStates = (over = {}) => ({
  "sensor.h": st("58.4"), "sensor.bt": st("22.44"), "binary_sensor.s": st("off"),
  "binary_sensor.f": st("on", { summary: "Running — automatic: shower detected" }),
  "binary_sensor.w": st("on", { summary: "On — drying after the shower" }),
  "sensor.r": st("2h 40m", { remaining_seconds: 9600, waiting_for_off_peak: false }),
  "switch.m": st("off", { configured_minutes: 20, remaining_seconds: null }), ...over,
});

test("a bathroom shows its numbers, the ACTUAL fan and towel-rail state and the drying time left", () => {
  const m = mod.bathroomModel({ states: bathStates() }, BATH);
  assert.equal(m.humidity, "58");
  assert.equal(m.temperature, "22.4");
  assert.equal(m.shower, false);
  assert.equal(m.fanText, "Running — automatic: shower detected");
  assert.equal(m.towelText, "On — drying after the shower");
  assert.equal(m.dryingLeft, "2 h 40 min left");
  assert.equal(m.button.label, "Run fan — 20 min");
});

test("drying time left says when the rail is waiting for off-peak, and is absent when nothing is scheduled", () => {
  const waiting = mod.bathroomModel({ states: bathStates({ "sensor.r": st("3h", { remaining_seconds: 10800, waiting_for_off_peak: true }) }) }, BATH);
  assert.equal(waiting.dryingLeft, "3 h 0 min left · waiting for off-peak");
  const none = mod.bathroomModel({ states: bathStates({ "sensor.r": st("0m", { remaining_seconds: 0 }) }) }, BATH);
  assert.equal(none.dryingLeft, null);
});

test("unavailable bathroom readings are dashes and unknown, never zero", () => {
  const m = mod.bathroomModel({ states: bathStates({ "sensor.h": st("unavailable"), "binary_sensor.f": st("unknown"), "binary_sensor.s": st("unavailable") }) }, BATH);
  assert.equal(m.humidity, null);
  assert.equal(m.shower, null);
  assert.equal(m.fanText, "Status unknown");
  assert.equal(m.button.kind, "inert");
});

// ----------------------------------------------------------------------------- the page card is read-only except the fan switch
test("the Home page card calls only switch.turn_on / switch.turn_off, and only on the configured manual fan switch", async () => {
  const fs = await import("node:fs");
  const js = fs.readFileSync(new URL("../../homeowner/www/thermowatt-power-flow-card.js", import.meta.url), "utf8");
  const page = js.slice(js.indexOf("class ThermowattHomePage"), js.indexOf('if (typeof customElements !== "undefined") {\n  if (!customElements.get("thermowatt-panel-card"))'));
  assert.equal(page.split("callService(").length - 1, 1);
  assert.ok(page.includes('callService("switch", button.classList.contains("cancel") ? "turn_off" : "turn_on", { entity_id: b.fan_switch })'));
  for (const forbidden of ["callWS", "fetch(", "setInterval", "button.press", "towel_switch", "towel_rail_manual_override"]) assert.ok(!page.includes(forbidden), forbidden);
});

test("the Home page needs a flow and a hot-water entity map", () => {
  const Page = globalThis.customElements.get("thermowatt-home-page");
  assert.ok(Page);
  assert.throws(() => new Page().setConfig({}), /flow and hot_water/);
  assert.doesNotThrow(() => new Page().setConfig({ flow: {}, hot_water: {} }));
});

// ----------------------------------------------------------------------------- solar used directly today
test("solar used directly shows only while the package says its daily meters are complete", () => {
  const today = { used: "sensor.used", status: "sensor.status" };
  const states = (status, used = st("9.8", { unit_of_measurement: "kWh" })) => ({ states: { "sensor.used": used, "sensor.status": st(status) } });
  assert.equal(mod.directUseKwh(states("ready"), today), 9.8);
  assert.equal(mod.directUseKwh(states("collecting_first_day"), today), null); // never implies a complete day
  assert.equal(mod.directUseKwh(states("inconsistent"), today), null);
  assert.equal(mod.directUseKwh(states("ready", st("unavailable")), today), null);
  assert.equal(mod.directUseKwh({ states: {} }, today), null);
  assert.equal(mod.directUseKwh(states("ready"), { solar: "x" }), null); // not configured
});

// ----------------------------------------------------------------------------- lights: why a light is missing
const light = (name, state = "on", extra = {}) => st(state, { friendly_name: name, supported_color_modes: ["brightness"], ...extra });

test("every excluded light is listed with its reason, and the third light is explained", () => {
  const hass = {
    states: {
      "light.a": light("Dining room"), "light.b": light("Living room"),
      "light.hid": light("Hidden one"), "light.diag": light("Diag one"), "light.off": light("Gone", "unavailable"),
      "light.lab": light("Labelled"), "light.grp": light("All", "on", { entity_id: ["light.a", "light.b"] }),
      "switch.garden_lamp": st("off", { friendly_name: "Garden lamp" }), "switch.kettle": st("off", { friendly_name: "Kettle" }),
    },
    entities: { "light.hid": { hidden: true }, "light.diag": { entity_category: "diagnostic" }, "light.lab": { labels: ["hide_from_dashboard"] } },
  };
  const found = mod.discoverLights(hass, { discover: true, exclude_label: "hide_from_dashboard" });
  assert.deepEqual(found.lights.map((l) => l.name), ["Dining room", "Living room"]);
  const why = Object.fromEntries(found.excluded.map((r) => [r.entityId, r.reason]));
  assert.match(why["light.hid"], /Hidden/);
  assert.match(why["light.diag"], /diagnostic/);
  assert.match(why["light.off"], /Currently unavailable/);
  assert.match(why["light.lab"], /hide_from_dashboard/);
  assert.match(why["light.grp"], /group/);
  // a lamp on a smart plug is a SWITCH: listed as a hint, never shown automatically
  assert.deepEqual(found.candidates.map((c) => c.entityId), ["switch.garden_lamp"]);
});

test("a switch the owner labels show_as_light is shown (toggle only, no brightness); an unlabelled one never is", () => {
  const hass = {
    states: { "light.a": light("Dining room"), "switch.garden_lamp": st("off", { friendly_name: "Garden lamp" }), "switch.heater": st("on", { friendly_name: "Heater" }) },
    entities: { "switch.garden_lamp": { labels: ["show_as_light"] } },
  };
  const found = mod.discoverLights(hass, { discover: true });
  assert.deepEqual(found.lights.map((l) => [l.entityId, l.domain]), [["light.a", "light"], ["switch.garden_lamp", "switch"]]);
  assert.ok(!found.lights.some((l) => l.entityId === "switch.heater"));
  const none = mod.discoverLights(hass, { discover: true, show_as_light_label: "" });
  assert.deepEqual(none.lights.map((l) => l.entityId), ["light.a"]);
});

// ----------------------------------------------------------------------------- the November gap
const hoursOf = (from, count, kwh) => Array.from({ length: count }, (_, i) => ({ start: from + i * HOUR, end: from + (i + 1) * HOUR, kwh }));

test("missing hours are listed exactly, in runs, and nothing is filled in", () => {
  const from = Date.parse("2026-11-01T00:00:00Z");
  const buckets = [...hoursOf(from, 5, 1), ...hoursOf(from + 8 * HOUR, 4, 1)]; // hours 5, 6, 7 are missing
  const runs = mod.missingRuns(buckets, from, from + 12 * HOUR, from + 13 * HOUR);
  assert.deepEqual(runs, [{ start: from + 5 * HOUR, end: from + 8 * HOUR, hours: 3 }]);
  assert.equal(mod.missingRuns(hoursOf(from, 12, 1), from, from + 12 * HOUR, from + 13 * HOUR).length, 0);
});

test("a solar source that is silent every night is reported as an overnight gap, and the balance is still withheld", () => {
  // Hobart is UTC+11 in November: local 18:00-07:00 is 07:00-20:00 UTC. A source with rows only 20:00Z..07:00Z is silent overnight.
  const from = Date.parse("2026-11-01T00:00:00Z") - 11 * HOUR; // local midnight, 1 Nov
  const days = 3;
  const solar = [];
  for (let h = 0; h < days * 24; h += 1) {
    const local = h % 24;
    if (local >= 7 && local < 18) solar.push({ start: from + h * HOUR, end: from + (h + 1) * HOUR, kwh: 1 });
  }
  const full = hoursOf(from, days * 24, 0.5);
  const b = mod.energyBalance({
    sources: { solar: { buckets: solar }, import: { buckets: full }, export: { buckets: full } },
    devices: [],
    from: solar[0].start,
    to: from + days * 24 * HOUR,
    now: from + days * 24 * HOUR + 3600e3,
    battery: false,
    timeZone: "Australia/Hobart",
  });
  assert.equal(b.status, "withheld");
  assert.match(b.reason, /solar generation statistics are incomplete/);
  assert.equal(b.gaps.source, "solar generation");
  const g = mod.describeGaps(b.gaps.runs, "Australia/Hobart");
  assert.equal(g.overnight, true); // every missing hour is between 18:00 and 07:00 local
  assert.equal(g.total, b.gaps.runs.reduce((n, r) => n + r.hours, 0));
  assert.ok(g.lines.every((line) => /\(\d+ h\)$/.test(line) || /^and \d+ more$/.test(line)));
});

test("a gap in daylight is not called an overnight shutdown", () => {
  const from = Date.parse("2026-11-01T00:00:00Z") - 11 * HOUR;
  const buckets = [...hoursOf(from, 10, 1), ...hoursOf(from + 14 * HOUR, 8, 1)]; // local 10:00-13:00 missing
  const runs = mod.missingRuns(buckets, from, from + 22 * HOUR, from + 23 * HOUR);
  assert.equal(mod.describeGaps(runs, "Australia/Hobart").overnight, false);
});

import test from "node:test";
import assert from "node:assert/strict";
import {
  computeFlows,
  formatKw,
  readWatts,
  renderSvg,
  travelSeconds,
  GREEN,
  ORANGE,
  GREY,
} from "../../homeowner/www/thermowatt-power-flow-card.js";

const base = { exportPositive: true, idleW: 5 };
const NOW = Date.parse("2026-11-22T10:00:00Z");
const st = (state, extra = {}) => ({ state, attributes: {}, last_reported: "2026-11-22T10:00:00Z", ...extra });

test("solar exporting to the grid", () => {
  const m = computeFlows({ ...base, solarW: 4000, houseW: 1200, gridW: 2800 });
  assert.equal(m.gridState, "export");
  assert.equal(m.gridLabel, "Grid Export");
  assert.equal(m.lines.solarToHouse, 1200);
  assert.equal(m.lines.solarToGrid, 2800);
  assert.equal(m.lines.gridToHouse, 0);
});

test("simultaneous solar generation and grid import", () => {
  const m = computeFlows({ ...base, solarW: 800, houseW: 3000, gridW: -2200 });
  assert.equal(m.gridLabel, "Grid Import");
  assert.equal(m.lines.solarToHouse, 800);
  assert.equal(m.lines.gridToHouse, 2200);
  assert.equal(m.lines.solarToGrid, 0);
});

test("night-time consumption is all grid import with a grey, stationary solar side", () => {
  const m = computeFlows({ ...base, solarW: 0, houseW: 450, gridW: -450 });
  assert.equal(m.lines.solarToHouse, 0);
  assert.equal(m.lines.solarToGrid, 0);
  assert.equal(m.lines.gridToHouse, 450);
  const svg = renderSvg(m);
  assert.ok(svg.includes(ORANGE));
  assert.ok(!svg.includes("tw-solarToHouse\"/><g"));
});

test("zero flow is idle and nothing moves", () => {
  const m = computeFlows({ ...base, solarW: 0, houseW: 0, gridW: 0 });
  assert.equal(m.gridLabel, "Grid Idle");
  assert.deepEqual(m.lines, { solarToHouse: 0, solarToGrid: 0, gridToHouse: 0 });
  const svg = renderSvg(m);
  assert.ok(!svg.includes("animateMotion"));
  assert.ok(!svg.includes(GREEN) && !svg.includes(ORANGE));
  assert.ok(svg.includes(GREY));
});

test("grid readings inside the idle threshold are idle (meter noise)", () => {
  assert.equal(computeFlows({ ...base, solarW: 0, houseW: 0, gridW: -4 }).gridState, "idle");
  assert.equal(computeFlows({ ...base, solarW: 0, houseW: 0, gridW: 4 }).gridState, "idle");
});

test("unavailable readings are shown as -- and never as zero", () => {
  const m = computeFlows({ ...base, solarW: null, houseW: null, gridW: null });
  assert.equal(m.gridLabel, "Grid Unavailable");
  assert.equal(formatKw(m.gridW), "--");
  assert.equal(formatKw(m.solarW), "--");
  const svg = renderSvg(m);
  assert.ok(!svg.includes("0.000 kW"));
  assert.ok(!svg.includes("animateMotion"));
});

test("missing house reading falls back to solar minus export, never invents consumption", () => {
  const m = computeFlows({ ...base, solarW: 3000, houseW: null, gridW: 1000 });
  assert.equal(m.lines.solarToHouse, 2000);
  assert.equal(m.houseW, null);
});

test("grid sign convention is configurable", () => {
  const m = computeFlows({ solarW: 0, houseW: 500, gridW: 500, exportPositive: false, idleW: 5 });
  assert.equal(m.gridState, "import");
});

test("kW is shown to three decimal places", () => {
  assert.equal(formatKw(1234.6), "1.235 kW");
  assert.equal(formatKw(-2800), "2.800 kW");
  assert.equal(formatKw(0), "0.000 kW");
});

test("chevron speed is proportional to power inside the clamp", () => {
  assert.equal(travelSeconds(0), null);
  assert.ok(Math.abs(travelSeconds(1) / travelSeconds(2) - 2) < 1e-9);
  assert.ok(Math.abs(travelSeconds(1.5) / travelSeconds(3) - 2) < 1e-9);
  assert.equal(travelSeconds(0.001), 8); // slowest
  assert.equal(travelSeconds(100), 0.5); // fastest
});

test("active lines animate with the right colours and direction", () => {
  const svg = renderSvg(computeFlows({ ...base, solarW: 4000, houseW: 1200, gridW: 2800 }));
  assert.equal((svg.match(/animateMotion/g) || []).length, 12); // 2 active lines x 3 chevrons x open+close
  assert.ok(svg.includes(GREEN));
  assert.ok(!svg.includes(ORANGE));
  const imp = renderSvg(computeFlows({ ...base, solarW: 0, houseW: 900, gridW: -900 }));
  assert.ok(imp.includes(ORANGE) && !imp.includes(GREEN));
});

test("reduced motion renders no animation", () => {
  const svg = renderSvg(computeFlows({ ...base, solarW: 4000, houseW: 1200, gridW: 2800 }), true);
  assert.ok(!svg.includes("animateMotion"));
});

test("readWatts handles units, unavailable and stale values", () => {
  assert.equal(readWatts(st("1500"), 900, NOW), 1500);
  assert.equal(readWatts(st("1.5", { attributes: { unit_of_measurement: "kW" } }), 900, NOW), 1500);
  assert.equal(readWatts(st("unavailable"), 900, NOW), null);
  assert.equal(readWatts(st("unknown"), 900, NOW), null);
  assert.equal(readWatts(st("abc"), 900, NOW), null);
  assert.equal(readWatts(undefined, 900, NOW), null);
  assert.equal(readWatts(st("100", { last_reported: "2026-11-22T09:00:00Z" }), 900, NOW), null);
});

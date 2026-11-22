// The Lights card: automatic discovery, filtering, brightness only where it dims, and layout at any count.
import test from "node:test";
import assert from "node:assert/strict";
import { Lights, mod, text } from "./support/fake_ha.mjs";

const light = (name, state = "on", { dimmable = true, brightness = 255, extra = {} } = {}) => ({
  state,
  attributes: { friendly_name: name, supported_color_modes: dimmable ? ["brightness"] : ["onoff"], ...(dimmable && state === "on" ? { brightness } : {}), ...extra },
});
const homeWith = (lights, registry = {}) => {
  const calls = [];
  const states = {};
  const entities = {};
  for (const [id, l] of Object.entries(lights)) {
    states[id] = l;
    entities[id] = registry[id] || {};
  }
  return { states, entities, calls, callService: (domain, service, data) => calls.push([domain, service, data]) };
};
const names = (hass, config = {}) => mod.discoverLights(hass, { discover: true, ...config }).lights.map((l) => l.name);
const make = (hass, config = {}) => {
  const card = new Lights();
  card.setConfig(config);
  card.hass = hass;
  return card;
};
const tiles = (card) => (card.sr.innerHTML.match(/class="light[ "]/g) || []).length;

test("every light is discovered automatically, sorted by name, with no list to maintain", () => {
  const hass = homeWith({ "light.living_room": light("Living room"), "light.dining_room": light("Dining room"), "light.hall": light("Hall", "off") });
  assert.deepEqual(names(hass), ["Dining room", "Hall", "Living room"]);
  hass.states["light.study"] = light("Study"); // a light added later appears on the next update, nothing regenerated
  assert.deepEqual(names(hass), ["Dining room", "Hall", "Living room", "Study"]);
  const numbered = homeWith({ "light.l10": light("Lamp 10"), "light.l2": light("Lamp 2"), "light.l1": light("Lamp 1") });
  assert.deepEqual(names(numbered), ["Lamp 1", "Lamp 2", "Lamp 10"]); // natural ordering for numbered lights
});

test("a third light appears in the rendered card without reconfiguring it", () => {
  const hass = homeWith({ "light.dining_room": light("Dining room"), "light.living_room": light("Living room") });
  const card = make(hass);
  assert.equal(tiles(card), 2);
  assert.match(text(card), /2 of 2 on/);
  hass.states["light.third"] = light("Third light", "off");
  hass.entities["light.third"] = {};
  card.hass = { ...hass }; // Home Assistant pushes a new hass object when states change
  assert.equal(tiles(card), 3);
  assert.match(text(card), /Third light/);
  assert.match(text(card), /2 of 3 on/);
});

test("hidden, disabled, diagnostic, unavailable, grouped, duplicate and excluded lights are not shown", () => {
  const hass = homeWith(
    {
      "light.ok": light("Kitchen"),
      "light.hidden": light("Hidden one"),
      "light.diag": light("Diagnostic one"),
      "light.gone": light("Unavailable one", "unavailable"),
      "light.unknown": light("Unknown one", "unknown"),
      "light.group": light("All downstairs", "on", { extra: { entity_id: ["light.ok", "light.other"] } }),
      "light.dup_a": light("Bulb", "on"),
      "light.dup_b": light("Bulb", "on"),
      "light.excluded": light("Not wanted"),
      "light.labelled": light("Labelled out"),
      "light.other": light("Other"),
    },
    {
      "light.hidden": { hidden: true },
      "light.diag": { entity_category: "diagnostic" },
      "light.dup_a": { device_id: "d1" },
      "light.dup_b": { device_id: "d1" },
      "light.labelled": { labels: ["hide_from_dashboard"] },
    }
  );
  // disabled entities have no state object at all, so they never appear
  const found = mod.discoverLights(hass, { discover: true, exclude: ["light.excluded"], exclude_label: "hide_from_dashboard" });
  assert.deepEqual(found.lights.map((l) => l.name).sort(), ["Bulb", "Kitchen", "Other"]);
  assert.equal(found.unavailable, 2); // reported, so the omission is visible
  const shown = mod.discoverLights(hass, { discover: true, exclude: ["light.excluded"], exclude_label: "hide_from_dashboard", show_unavailable: true });
  assert.ok(shown.lights.some((l) => l.name === "Unavailable one"));
  assert.ok(mod.discoverLights(hass, { discover: true, exclude_groups: false }).lights.some((l) => l.name === "All downstairs")); // groups can be kept
  const card = make(hass, { exclude: ["light.excluded"] });
  assert.match(text(card), /2 unavailable lights are not shown/);
});

test("the label that hides a light is configurable and defaults to hide_from_dashboard", () => {
  const hass = homeWith({ "light.a": light("A"), "light.b": light("B") }, { "light.b": { labels: ["hide_from_dashboard"] } });
  assert.equal(tiles(make(hass)), 1);
  assert.equal(tiles(make(hass, { exclude_label: "something_else" })), 2);
  assert.equal(tiles(make(hass, { exclude_label: "" })), 2);
});

test("brightness controls appear only for lights that can dim, and only while they are on", () => {
  const hass = homeWith({
    "light.dim": light("Dimmable", "on", { brightness: 128 }),
    "light.plain": light("Plain", "on", { dimmable: false }),
    "light.off": light("Switched off", "off"),
    "light.ct": { state: "on", attributes: { friendly_name: "Colour temp", supported_color_modes: ["color_temp"], brightness: 255 } },
  });
  const html = make(hass).sr.innerHTML;
  assert.equal((html.match(/type="range"/g) || []).length, 2); // dimmable + colour-temperature
  assert.match(html, /data-brightness="light.dim"/);
  assert.match(html, /value="50"/); // 128 / 255
  assert.equal(html.includes('data-brightness="light.plain"'), false);
  assert.equal(html.includes('data-brightness="light.off"'), false);
  assert.equal(mod.isDimmable({ attributes: { supported_color_modes: ["onoff"] } }), false);
  assert.equal(mod.isDimmable({ attributes: { supported_color_modes: ["rgb"] } }), true);
  assert.equal(mod.isDimmable({ attributes: {} }), false);
});

test("tapping toggles the light; moving the slider sets its brightness; an unavailable light is inert", () => {
  const hass = homeWith({ "light.dim": light("Dimmable", "on", { brightness: 255 }), "light.gone": light("Gone", "unavailable") });
  const card = make(hass, { show_unavailable: true });
  assert.match(card.sr.innerHTML, /data-toggle="light.gone" disabled/);
  card.sr.listeners.click({ target: { closest: () => ({ dataset: { toggle: "light.dim" }, disabled: false }) } });
  card.sr.listeners.click({ target: { closest: () => ({ dataset: { toggle: "light.gone" }, disabled: true }) } });
  card.sr.listeners.change({ target: { closest: () => ({ dataset: { brightness: "light.dim" }, value: "40" }) } });
  assert.deepEqual(hass.calls, [["light", "toggle", { entity_id: "light.dim" }], ["light", "turn_on", { entity_id: "light.dim", brightness_pct: 40 }]]);
});

test("pinned lights keep their order and names; names can be overridden", () => {
  const hass = homeWith({ "light.a": light("Alpha"), "light.b": light("Bravo"), "light.c": light("Charlie") });
  assert.deepEqual(names(hass, { lights: [{ entity: "light.c", name: "Pinned first" }] }), ["Pinned first", "Alpha", "Bravo"]);
  assert.deepEqual(names(hass, { names: { "light.b": "Renamed" } }), ["Alpha", "Charlie", "Renamed"]);
  assert.throws(() => new Lights().setConfig({ lights: [{ entity: "switch.x" }] }), /light entity/);
});

test("the layout scales from two to ten lights: density steps down and every light is shown", () => {
  for (const count of [2, 3, 5, 10]) {
    const spec = {};
    for (let i = 1; i <= count; i += 1) spec[`light.l${i}`] = light(`Light ${i}`, i % 2 ? "on" : "off");
    const card = make(homeWith(spec));
    assert.equal(tiles(card), count, `${count} lights`);
    const density = count > 8 ? "dense" : count > 4 ? "medium" : "roomy";
    assert.match(card.sr.innerHTML, new RegExp(`class="lights ${density}"`), `${count} lights use ${density}`);
    assert.match(text(card), new RegExp(`${Math.ceil(count / 2)} of ${count} on`));
  }
});

test("no lights at all says so instead of rendering an empty card", () => {
  assert.match(text(make(homeWith({}))), /No lights were found/);
});

test("a light without a friendly name gets a readable name, not its entity ID", () => {
  const hass = homeWith({ "light.hall_light": { state: "on", attributes: { supported_color_modes: ["onoff"] } } });
  assert.deepEqual(names(hass), ["Hall light"]);
  assert.equal(mod.prettyEntityName("light.kitchen_island_lamp"), "Kitchen island lamp");
});

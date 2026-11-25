/* Real Home Assistant Lovelace only: renders the generated Home dashboard at four representative widths
 * (1920 desktop, 1366 laptop, 1280 desktop, 390 phone), measures layout, checks light/dark themes and
 * reduced motion, drives state through a test-only view and verifies which service call a tap WOULD
 * send. Calls are recorded by the disposable server, never executed. Synthetic states only. */
const { chromium, expect } = require("@playwright/test");
const fs = require("node:fs");
const fixture = JSON.parse(fs.readFileSync("/private/browser.json", "utf8"));
const output = "/results";
const MODE = "sensor.thermann_shadow_hot_water_operating_mode";
const CONTROL = "sensor.thermann_shadow_automatic_control_state";
const START = "button.thermann_shadow_start_guest_mode_12_h";
const CANCEL = "button.thermann_shadow_cancel_guest_mode";
const HOLD = "button.thermann_shadow_hold_heater_owner_override";
const RESUME = "button.thermann_shadow_resume_automatic_control";
const AUTOMATIC = "switch.thermann_shadow_automatic_heater_control";
const BOOST_ENABLED = "switch.thermann_shadow_enable_optional_solar_boost";
const STATUS = "sensor.home_energy_status";
const FAN = "binary_sensor.tapo_smart_controller_main_bathroom_fan_running";
const FAN_SWITCH = "switch.tapo_smart_controller_main_bathroom_fan_manual_override";
const TOWEL = "binary_sensor.tapo_smart_controller_main_bathroom_towel_rail_heating";
const TOWEL_SWITCH = "switch.tapo_smart_controller_main_bathroom_towel_rail_manual_override";
// The Galaxy Tab S7 FE is 2560x1600 physical at a device pixel ratio of 2, so its CSS viewport is about 1280x800:
// 1280x800 with the browser's bars hidden or as an installed app (desktop-1280), about 1280x704 with Chrome's tab
// strip and address bar showing (tablet-1280x704). Home Assistant docks its 256 px sidebar from 870 px wide.
const WIDTHS = [
  { width: 1920, height: 1080, name: "desktop-1920", interactive: true },
  { width: 1366, height: 768, name: "laptop-1366", interactive: false },
  { width: 1280, height: 800, name: "desktop-1280", interactive: false },
  { width: 1280, height: 704, name: "tablet-1280x704", interactive: false },
  { width: 390, height: 844, name: "mobile-390", interactive: true },
];
// The Home page is ONE card that fits the viewport: no scrolling at any width of 760 px or more.
const HOME_FITS = new Set(["desktop-1920", "laptop-1366", "desktop-1280", "tablet-1280x704"]);

async function main() {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const newContext = (extra = {}) =>
    browser.newContext({ viewport: { width: 1280, height: 960 }, locale: "en-AU", ...extra });
  const prepare = async (context) => {
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      return url.hostname === "127.0.0.1" ? route.continue() : route.abort();
    });
    await context.addInitScript((auth) => {
      localStorage.setItem("hassTokens", JSON.stringify(auth));
      localStorage.setItem("selectedLanguage", "en");
    }, fixture.auth);
  };
  const context = await newContext();
  await prepare(context);
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const hassCall = (method, path, body) =>
    page.evaluate(([m, p, b]) => document.querySelector("home-assistant").hass.callApi(m, p, b), [method, path, body]);
  const setState = (entity_id, state, attributes = {}) => hassCall("POST", "home_ui_state", { entity_id, state, attributes });
  const power = (entity_id, state) => setState(entity_id, state, { unit_of_measurement: "W" });
  const calls = () => hassCall("GET", "home_ui_calls");
  const clearCalls = () => hassCall("DELETE", "home_ui_calls");
  // A fresh disposable HA asks to confirm its loopback-only HTTP binding a few seconds after load; it
  // blocks every click, so wait for it the first time and check for it again before each interaction.
  let httpDialogSeen = false;
  const dismissHttpDialog = async () => {
    const confirm = page.locator("dialog-http-pending-config").getByRole("button", { name: "Confirm", exact: true });
    if (!httpDialogSeen) await confirm.waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
    if (await confirm.isVisible().catch(() => false)) {
      httpDialogSeen = true;
      await confirm.click({ force: true });
      await expect(confirm).not.toBeVisible();
    }
  };
  const confirmIfAsked = async () => {
    for (const name of ["Yes", "OK", "Confirm", "Continue"]) {
      for (const candidate of [page.getByRole("button", { name, exact: true }), page.getByText(name, { exact: true })]) {
        const visible = candidate.filter({ visible: true }).first();
        if (await visible.isVisible()) {
          await visible.click({ force: true });
          return true;
        }
      }
    }
    return false;
  };
  // A tap on an inert tile opens that entity's more-info dialog (which may open nested ones): close them all so
  // the next tap is not blocked.
  const closeDialogs = async () => {
    for (let i = 0; i < 4; i += 1) {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(250);
    }
  };
  const tap = async (text, { first = false } = {}) => {
    await dismissHttpDialog();
    await clearCalls();
    const target = first ? page.getByText(text).first() : page.getByText(text);
    let confirmationShown = false;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      await target.evaluate((el) => el.scrollIntoView({ block: "center" })).catch(() => {});
      await page.waitForTimeout(700);
      await target.click({ force: true });
      await page.waitForTimeout(1200);
      if (await confirmIfAsked()) confirmationShown = true;
      await page.waitForTimeout(800);
      const recorded = await calls();
      if (recorded.length || confirmationShown) {
        await closeDialogs();
        return { calls: recorded, confirmationShown };
      }
    }
    await closeDialogs();
    return { calls: await calls(), confirmationShown };
  };
  // Layout facts measured in the real rendered DOM (open shadow roots are searched).
  const layout = () =>
    page.evaluate(() => {
      const all = (root, selector, out = []) => {
        for (const el of root.querySelectorAll("*")) {
          if (el.matches(selector)) out.push(el);
          if (el.shadowRoot) all(el.shadowRoot, selector, out);
        }
        return out;
      };
      const homeCard = all(document, "thermowatt-home-page")[0];
      if (homeCard) {
        // a panel view: ONE card, measured against the space the browser really gives it
        const box = homeCard.getBoundingClientRect();
        let scrollOverflow = 0;
        for (let node = homeCard; node; node = node.parentNode || node.host) {
          if (node.nodeType !== 1) continue;
          const overflowY = getComputedStyle(node).overflowY;
          if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight - node.clientHeight > scrollOverflow) scrollOverflow = node.scrollHeight - node.clientHeight;
        }
        const clipped = [];
        for (const el of homeCard.shadowRoot.querySelectorAll("ha-card, .cell")) {
          if (el.scrollHeight > el.clientHeight + 1) clipped.push(`${el.id || el.className || el.tagName}:${el.scrollHeight - el.clientHeight}`);
        }
        const wide = [];
        for (const el of [...homeCard.shadowRoot.querySelectorAll("*")]) {
          const r = el.getBoundingClientRect();
          if (r.right > window.innerWidth + 1) wide.push(`${el.tagName.toLowerCase()}.${el.className || el.id}:${Math.round(r.right - window.innerWidth)}`);
        }
        const flowCard = homeCard.shadowRoot.querySelector("thermowatt-power-flow-card");
        const lightsCard = homeCard.shadowRoot.querySelector("thermowatt-lights-card");
        const text = [...(flowCard ? flowCard.shadowRoot.querySelectorAll("text") : [])].map((t) => t.getBoundingClientRect().height);
        const smallest = [
          ...homeCard.shadowRoot.querySelectorAll(".line, .lab, .fact .k, .fact .s, .foot, .t, .chip, .strip .k"),
          ...(flowCard ? flowCard.shadowRoot.querySelectorAll(".kpi .lab, .kpi .val, .title, .chip") : []),
          ...(lightsCard ? lightsCard.shadowRoot.querySelectorAll(".lt .n, .lt .s, .small, .title, .chip") : []),
        ].map((el) => parseFloat(getComputedStyle(el).fontSize));
        const truncatedTitles = [...homeCard.shadowRoot.querySelectorAll(".t")]
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map((el) => el.textContent.trim());
        const wxCard = all(homeCard.shadowRoot, "hui-weather-forecast-card")[0];
        let weatherForecast = null;
        if (wxCard && wxCard.shadowRoot) {
          const wxBox = wxCard.getBoundingClientRect();
          const forecast = wxCard.shadowRoot.querySelector(".forecast");
          const days = forecast ? [...forecast.children] : [];
          const clippedDays = days.filter((d) => d.getBoundingClientRect().right > wxBox.right + 1).length;
          weatherForecast = {
            cardWidth: Math.round(wxBox.width),
            days: days.length,
            clippedDays,
            overflowX: forecast ? Math.round(forecast.scrollWidth - forecast.clientWidth) : 0,
          };
        }
        return {
          panel: true,
          viewTop: Math.round(box.top),
          viewport: [window.innerWidth, window.innerHeight],
          cardBottom: Math.round(box.bottom),
          contentHeight: Math.round(box.height),
          availableHeight: Math.round(window.innerHeight - box.top),
          ratio: Number((box.bottom / window.innerHeight).toFixed(2)),
          documentScroll: document.documentElement.scrollHeight - window.innerHeight,
          scrollOverflow,
          clipped,
          wide: wide.slice(0, 8),
          columns: 3,
          overlaps: 0,
          overflowX: document.documentElement.scrollWidth - window.innerWidth,
          minSvgTextHeight: text.length ? Math.min(...text) : null,
          smallestFontPx: smallest.length ? Number(Math.min(...smallest).toFixed(2)) : null,
          truncatedTitles,
          weatherForecast,
        };
      }
      const view = all(document, "hui-sections-view")[0];
      const sections = all(view.shadowRoot, "hui-section").map((s) => s.getBoundingClientRect());
      const top = view.getBoundingClientRect().top;
      const contentBottom = Math.max(...sections.map((r) => r.bottom));
      let overlaps = 0;
      for (let i = 0; i < sections.length; i += 1)
        for (let j = i + 1; j < sections.length; j += 1) {
          const a = sections[i];
          const b = sections[j];
          const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (w > 4 && h > 4) overlaps += 1;
        }
      const svgText = all(document, "thermowatt-power-flow-card")
        .flatMap((c) => [...c.shadowRoot.querySelectorAll("text")])
        .map((t) => t.getBoundingClientRect().height);
      return {
        viewTop: Math.round(top),
        contentHeight: Math.round(contentBottom - top),
        availableHeight: Math.round(window.innerHeight - top),
        ratio: Number(((contentBottom - top) / (window.innerHeight - top)).toFixed(2)),
        columns: new Set(sections.map((r) => Math.round(r.left))).size,
        overlaps,
        overflowX: document.documentElement.scrollWidth - window.innerWidth,
        minSvgTextHeight: svgText.length ? Math.min(...svgText) : null,
      };
    });
  const flowMotion = () =>
    page.evaluate(async () => {
      const find = (root) => {
        for (const el of root.querySelectorAll("*")) {
          if (el.tagName === "THERMOWATT-POWER-FLOW-CARD") return el;
          if (el.shadowRoot) {
            const hit = find(el.shadowRoot);
            if (hit) return hit;
          }
        }
        return null;
      };
      const el = find(document);
      const groups = [...el.shadowRoot.querySelectorAll("animateMotion")].map((a) => a.parentElement);
      const at = () => groups.map((g) => g.getBoundingClientRect().x);
      const a = at();
      await new Promise((r) => setTimeout(r, 600));
      const b = at();
      return { chevrons: groups.length, moved: a.filter((x, i) => x !== b[i]).length };
    });
  const goHome = async (path = "home") => {
    await page.goto(`http://127.0.0.1:8123/home-test/${path}`);
    await dismissHttpDialog();
    await page.waitForFunction(() => !!document.querySelector("home-assistant")?.hass?.callApi);
    await expect(page.locator("hui-error-card")).toHaveCount(0);
    await page.waitForTimeout(1200);
    // No card on ANY view may show a configuration error (a tile without an entity, a bad option...).
    await expect(page.getByText("Configuration error", { exact: false })).toHaveCount(0);
  };
  const deepFind = (tag) => `(() => {
    const out = [];
    const walk = (root) => {
      for (const el of root.querySelectorAll("*")) {
        if (el.tagName === "${tag}") out.push(el);
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(document);
    return out;
  })()`;
  const report = [];

  try {
    for (const size of WIDTHS) {
      await page.setViewportSize({ width: size.width, height: size.height });
      await goHome("home");
      await expect(page.getByText("kW", { exact: false }).first()).toBeVisible();
      expect(await page.getByText("Configuration error", { exact: false }).count()).toBe(0);
      await page.waitForFunction(() => !!customElements.get("thermowatt-power-flow-card"));
      await expect(page.getByText("4.123 kW")).toBeVisible();
      await expect(page.getByText("Grid Export", { exact: true }).first()).toBeVisible();
      await page.waitForTimeout(1500); // let cards finish their first layout
      const facts = await layout();
      console.log(JSON.stringify({ layout: size.name, ...facts }));
      expect(facts.overflowX).toBeLessThanOrEqual(2); // no horizontal overflow
      expect(facts.overlaps).toBe(0); // no overlapping sections
      if (facts.minSvgTextHeight !== null) expect(facts.minSvgTextHeight).toBeGreaterThanOrEqual(8);
      if (HOME_FITS.has(size.name)) {
        expect(facts.panel, "Home is a panel view").toBe(true);
        expect(facts.cardBottom, "the Home card ends inside the viewport").toBeLessThanOrEqual(size.height);
        expect(facts.documentScroll, "the page does not scroll").toBeLessThanOrEqual(2);
        expect(facts.scrollOverflow, "no scroll container around the Home card scrolls").toBeLessThanOrEqual(2);
        expect(facts.clipped, "no Home card has clipped content").toEqual([]);
        expect(facts.smallestFontPx, "meaningful tablet text stays >= 13 px").toBeGreaterThanOrEqual(13);
        expect(facts.truncatedTitles, "no Home card header title is truncated").toEqual([]);
        if (facts.weatherForecast) {
          expect(facts.weatherForecast.days, "all 5 forecast days render").toBeGreaterThanOrEqual(5);
          expect(facts.weatherForecast.clippedDays, "no weather forecast day is clipped at the right edge").toBe(0);
          expect(facts.weatherForecast.overflowX, "weather forecast does not horizontally overflow").toBeLessThanOrEqual(2);
        }
      }

      // Compact hot-water summary and energy panel are on the main screen.
      await expect(page.getByText("Water temperature", { exact: false }).first()).toBeVisible();
      await expect(page.getByText("Tank bottom", { exact: false })).toHaveCount(0);
      await expect(page.getByText("52.4").first()).toBeVisible();
      await expect(page.getByText("Solar today").first()).toBeVisible(); // today's strip under the flow diagram
      await expect(page.getByText("Used directly").first()).toBeVisible(); // solar used directly (withheld until a full day)
      await expect(page.getByText("Imported today").first()).toBeVisible();
      await expect(page.getByText("Exported today").first()).toBeVisible();
      await expect(page.getByText("Automatic on", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Run fan — 20 min")).toHaveCount(2); // one per bathroom, the default length
      await expect(page.getByText("Main Bathroom", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Ensuite", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Garage closed").first()).toBeVisible(); // doors: a small status only
      await expect(page.getByText("12-hour", { exact: false })).toHaveCount(0); // no hot-water override on Home
      await expect(page.getByText("override", { exact: false })).toHaveCount(0);
      await expect(page.getByText("Weather: mapping needed")).toHaveCount(0);
      const weather = await page.evaluate(() => {
        const deepText = (root) => {
          let out = "";
          for (const el of root.querySelectorAll("*")) {
            if (el.shadowRoot) out += " " + deepText(el.shadowRoot);
          }
          return out + " " + (root.textContent || "");
        };
        const find = (root) => {
          for (const el of root.querySelectorAll("*")) {
            if (el.tagName === "HUI-WEATHER-FORECAST-CARD") return el;
            if (el.shadowRoot) {
              const hit = find(el.shadowRoot);
              if (hit) return hit;
            }
          }
          return null;
        };
        const card = find(document);
        return card ? deepText(card.shadowRoot).replace(/\s+/g, " ") : "";
      });
      console.log("weather card text:", JSON.stringify(weather.slice(0, 120)));
      expect(weather).toMatch(/°/);
      const motion = await flowMotion();
      expect(motion.chevrons).toBeGreaterThan(0);
      expect(motion.moved).toBeGreaterThan(0);

      await page.screenshot({ path: `${output}/home-${size.name}.png`, fullPage: true });
      await page.emulateMedia({ colorScheme: "dark" });
      await page.waitForTimeout(1200);
      await page.screenshot({ path: `${output}/home-${size.name}-dark.png`, fullPage: true });
      await page.emulateMedia({ colorScheme: "light" });

      if (size.interactive) {
        // Power flow reacts: import, simultaneous solar + import, unavailable.
        await power("sensor.goodwe_inverter_meter_active_power", "-2200");
        await power("sensor.goodwe_inverter_pv_power", "800");
        await power("sensor.goodwe_inverter_house_consumption", "3000");
        await expect(page.getByText("Grid Import", { exact: true }).first()).toBeVisible();
        await expect(page.getByText("3.000 kW")).toBeVisible();
        await power("sensor.goodwe_inverter_meter_active_power", "unavailable");
        await expect(page.getByText("Grid Unavailable", { exact: true }).first()).toBeVisible();
        await power("sensor.goodwe_inverter_meter_active_power", "2923");
        await power("sensor.goodwe_inverter_pv_power", "4123");
        await power("sensor.goodwe_inverter_house_consumption", "1200");

        // First-day energy initialisation vs full-day figures (the Energy page's "Today's energy" panel).
        await goHome("energy");
        await expect(page.getByText("Collecting daily data", { exact: true }).first()).toBeVisible();
        await setState(STATUS, "ready");
        await expect(page.getByText("Household today").first()).toBeVisible();
        await expect(page.getByText("Collecting daily data", { exact: true })).toHaveCount(0);
        await setState(STATUS, "sources_unavailable");
        await expect(page.getByText("figures are withheld, not zero", { exact: false }).first()).toBeVisible();
        await setState(STATUS, "collecting_first_day");
        await goHome("home");

        let result;
        // Lights are DISCOVERED: the two seeded lights show, a third appears with no reconfiguration, and the
        // card scales to ten. Unavailable lights and light groups are not shown.
        const lightFacts = () =>
          page.evaluate(`(() => {
            const card = ${deepFind("THERMOWATT-LIGHTS-CARD")}[0];
            const host = card.getBoundingClientRect();
            const tiles = [...card.shadowRoot.querySelectorAll(".light")].map((t) => t.getBoundingClientRect());
            let overlaps = 0;
            for (let i = 0; i < tiles.length; i += 1) for (let j = i + 1; j < tiles.length; j += 1) {
              const a = tiles[i]; const b = tiles[j];
              if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2) overlaps += 1;
            }
            return {
              count: tiles.length,
              hostWidth: Math.round(host.width),
              hostHeight: Math.round(host.height),
              outside: tiles.filter((r) => r.left < host.left - 1 || r.right > host.right + 1 || r.bottom > host.bottom + 1).length,
              overlaps,
              narrowest: Math.round(Math.min(...tiles.map((r) => r.width))),
              sliders: card.shadowRoot.querySelectorAll('input[type="range"]').length,
              text: card.shadowRoot.textContent.replace(/\\s+/g, " "),
            };
          })()`);
        const shootLights = async (name) => {
          const handle = await page.evaluateHandle(`${deepFind("THERMOWATT-LIGHTS-CARD")}[0]`);
          await handle.asElement().scrollIntoViewIfNeeded();
          await page.waitForTimeout(400);
          await handle.asElement().screenshot({ path: `${output}/lights-${name}-${size.name}.png` });
        };
        await expect(page.getByText("Dining room", { exact: true }).first()).toBeVisible();
        let lights = await lightFacts();
        expect(lights.count).toBe(2);
        expect(lights.text).toContain("Living room");
        await shootLights("2");
        await setState("light.third_light", "on", { friendly_name: "Third light", supported_color_modes: ["brightness"], brightness: 200 });
        await expect(page.getByText("Third light", { exact: true }).first()).toBeVisible();
        lights = await lightFacts();
        expect(lights.count).toBe(3);
        expect(lights.sliders).toBe(2); // Dining room (on, dimmable) and Third light; Living room is off
        await shootLights("3");
        await setState("light.gone_light", "unavailable", { friendly_name: "Gone light", supported_color_modes: ["brightness"] });
        await setState("light.all_lights_group", "on", { friendly_name: "All lights", entity_id: ["light.dining_room_light", "light.third_light"], supported_color_modes: ["brightness"] });
        await expect(page.getByText(/unavailable lights? (is|are) not shown/).first()).toBeVisible();
        lights = await lightFacts();
        expect(lights.count).toBe(3); // neither the unavailable light nor the group is shown
        expect(lights.text).not.toContain("Gone light");
        expect(lights.text).not.toContain("All lights");
        const lightCounts = [5, 10];
        for (const wanted of lightCounts) {
          for (let i = 4; i <= wanted; i += 1) {
            await setState(`light.test_light_${i}`, i % 2 ? "on" : "off", {
              friendly_name: `Test light ${i}`,
              supported_color_modes: i % 3 === 0 ? ["onoff"] : ["brightness"],
              ...(i % 2 && i % 3 !== 0 ? { brightness: 120 + i } : {}),
            });
          }
          // Home: the lights card shows every light inside its own cell (it scrolls inside), the page never scrolls
          await expect.poll(async () => (await lightFacts()).count, { timeout: 10000 }).toBe(wanted);
          lights = await lightFacts();
          expect(lights.narrowest).toBeGreaterThan(100); // never squeezed into an unreadable sliver
          expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2);
          if (HOME_FITS.has(size.name)) expect((await layout()).clipped).toEqual([]);
          await shootLights(`home-${wanted}`);
          // Lights page: the full layout, with the reasons for every light that is not shown
          await goHome("lights");
          await expect.poll(async () => (await lightFacts()).count, { timeout: 10000 }).toBe(wanted);
          lights = await lightFacts();
          expect(lights.outside).toBe(0);
          expect(lights.overlaps).toBe(0);
          expect(lights.narrowest).toBeGreaterThan(100);
          await shootLights(String(wanted));
          await goHome("home");
        }
        // The third light's missing-light explanation: every excluded light is listed with its reason.
        await goHome("lights");
        await expect(page.getByText("Why some lights are not shown", { exact: false })).toBeVisible();
        await expect(page.getByText("Gone light", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("Currently unavailable", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("A light group", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("Switches that look like lamps", { exact: false })).toBeVisible();
        await expect(page.getByText("switch.garden_lamp", { exact: false }).first()).toBeVisible(); // a lamp on a plug is a switch
        await expect(page.getByText("show_as_light", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("The evening schedule is not installed", { exact: false })).toBeVisible();
        await setState("automation.evening_lights_on", "off", { friendly_name: "Evening lights on" });
        await setState("automation.evening_lights_off", "off", { friendly_name: "Evening lights off" });
        await expect(page.getByText("Evening lights on (2 h before sunset)", { exact: false })).toBeVisible();
        result = await tap("Evening lights on (2 h before sunset)", { first: true });
        expect(result.confirmationShown, "switching the schedule on asks for confirmation").toBe(true);
        expect(JSON.stringify(result.calls)).toContain("automation.toggle");
        await page.screenshot({ path: `${output}/lights-page-${size.name}.png`, fullPage: true });
        // the schedule is "not installed" again for the next viewport (states persist across the run)
        await setState("automation.evening_lights_on", "unavailable");
        await setState("automation.evening_lights_off", "unavailable");
        await goHome("home");
        for (let i = 4; i <= 10; i += 1) await setState(`light.test_light_${i}`, "unavailable", { friendly_name: `Test light ${i}` });
        await setState("light.third_light", "unavailable", { friendly_name: "Third light" });
        await expect.poll(async () => (await lightFacts()).count, { timeout: 10000 }).toBe(2);
        result = await tap("Living room", { first: true });
        expect(JSON.stringify(result.calls)).toContain("light.toggle");

        // Home: the manual fan button of each bathroom (the only control on the page).
        await expect(page.getByText("Run fan — 20 min").first()).toBeVisible();
        result = await tap("Run fan — 20 min", { first: true });
        expect(JSON.stringify(result.calls)).toContain("switch.turn_on");
        expect(JSON.stringify(result.calls)).toContain(FAN_SWITCH);
        expect(JSON.stringify(result.calls)).not.toContain("towel");
        await setState(FAN_SWITCH, "on", { configured_minutes: 20, remaining_seconds: 17 * 60 - 20 });
        await expect(page.getByText("Cancel fan — 17 min left").first()).toBeVisible();
        result = await tap("Cancel fan — 17 min left", { first: true });
        expect(JSON.stringify(result.calls)).toContain("switch.turn_off");
        expect(JSON.stringify(result.calls)).toContain(FAN_SWITCH);
        await setState(FAN_SWITCH, "off", { configured_minutes: 45, remaining_seconds: null });
        await expect(page.getByText("Run fan — 45 min").first()).toBeVisible(); // the Bathrooms-page setting shows here
        await setState(FAN_SWITCH, "off", { configured_minutes: 20, remaining_seconds: null });
        await setState(FAN, "unavailable");
        await expect(page.getByText("Fan unavailable").first()).toBeVisible();
        result = await tap("Fan unavailable", { first: true });
        expect(result.calls).toEqual([]);
        await setState(FAN, "off", { summary: "Off — normal" });
        await setState(TOWEL, "off", { summary: "Waiting for off-peak — 4h 00m left (manual)" });
        await setState("sensor.tapo_smart_controller_main_bathroom_towel_rail_remaining_time", "4h", { remaining_seconds: 14400, waiting_for_off_peak: true });
        await expect(page.getByText("waiting for off-peak", { exact: false }).first()).toBeVisible(); // drying time left
        await setState(TOWEL, "off", { summary: "Off — no drying scheduled" });
        await setState("sensor.tapo_smart_controller_main_bathroom_towel_rail_remaining_time", "0m", { remaining_seconds: 0, waiting_for_off_peak: false });

        // Hot water view: grouped controls, every significant action confirmed, existing entities only.
        await goHome("hot-water");
        await setState(AUTOMATIC, "on");
        await setState(BOOST_ENABLED, "on");
        await expect(page.getByText("Everyday controls", { exact: true })).toBeVisible();
        await expect(page.getByText("Automatic heater control: ON")).toBeVisible();
        result = await tap("Automatic heater control: ON");
        expect(result.confirmationShown, "stopping automatic control asks for confirmation").toBe(true);
        expect(JSON.stringify(result.calls)).toContain("switch.turn_off");
        expect(JSON.stringify(result.calls)).toContain(AUTOMATIC);
        // optional solar boost is locked while automatic control is on: inert, and it says why
        await expect(page.getByText("Optional solar boost: enabled (locked: automatic control is on)")).toBeVisible();
        result = await tap("Optional solar boost: enabled (locked", { first: true });
        expect(result.calls).toEqual([]);
        expect(result.confirmationShown).toBe(false);
        await setState(AUTOMATIC, "off");
        await expect(page.getByText("Automatic heater control: OFF")).toBeVisible();
        await expect(page.getByText("Optional solar boost: enabled", { exact: true })).toBeVisible();
        result = await tap("Optional solar boost: enabled", { first: true });
        expect(result.confirmationShown).toBe(true);
        expect(JSON.stringify(result.calls)).toContain("switch.turn_off");
        expect(JSON.stringify(result.calls)).toContain(BOOST_ENABLED);
        expect(JSON.stringify(result.calls)).not.toContain("button.press"); // never a way to force the heater
        await setState(BOOST_ENABLED, "off");
        await expect(page.getByText("Optional solar boost: disabled", { exact: true })).toBeVisible();
        result = await tap("Optional solar boost: disabled", { first: true });
        expect(result.confirmationShown).toBe(true);
        expect(JSON.stringify(result.calls)).toContain("switch.turn_on");
        result = await tap("Automatic heater control: OFF");
        expect(result.confirmationShown, "starting automatic control asks for confirmation").toBe(true);
        expect(JSON.stringify(result.calls)).toContain("switch.turn_on");
        await setState(AUTOMATIC, "unavailable");
        await expect(page.getByText("Automatic heater control: status unknown")).toBeVisible();
        result = await tap("Automatic heater control: status unknown");
        expect(result.calls).toEqual([]);
        await setState(AUTOMATIC, "on");
        await setState(BOOST_ENABLED, "on");
        // 12-hour 62 C override: ON / OFF / unknown, each press confirmed, existing buttons only
        await setState(MODE, "automatic");
        await expect(page.getByText("12-hour 62 °C override: OFF")).toBeVisible();
        result = await tap("12-hour 62 °C override: OFF");
        expect(result.confirmationShown, "start override asks for confirmation").toBe(true);
        expect(JSON.stringify(result.calls)).toContain(START);
        await setState(MODE, "guest");
        await setState("sensor.thermann_shadow_guest_mode_ends", new Date(Date.now() + 3600e3).toISOString());
        await expect(page.getByText("12-hour 62 °C override: ON")).toBeVisible();
        await expect(page.getByText("12 h override ends").first()).toBeVisible(); // end time and time left, only while active
        await expect(page.getByText("min left").first()).toBeVisible();
        result = await tap("12-hour 62 °C override: ON");
        expect(result.confirmationShown, "cancel override asks for confirmation").toBe(true);
        expect(JSON.stringify(result.calls)).toContain(CANCEL);
        await setState(MODE, "unavailable");
        await expect(page.getByText("12-hour 62 °C override: status unknown")).toBeVisible();
        result = await tap("12-hour 62 °C override: status unknown");
        expect(result.calls).toEqual([]);
        expect(result.confirmationShown).toBe(false);
        await setState(MODE, "automatic");
        // grouped: operating info, everyday controls, then diagnostics and advanced settings; Thermowatt Settings button
        await expect(page.getByText("Thermowatt Settings", { exact: true })).toBeVisible();
        await expect(page.getByText("Advanced", { exact: true })).toBeVisible();
        await expect(page.getByText("Water temperature", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("Tank bottom", { exact: false })).toHaveCount(0);
        await setState(CONTROL, "observing");
        await expect(page.getByText("Automatic heating: active")).toBeVisible();
        result = await tap("Automatic heating: active");
        expect(result.confirmationShown).toBe(true);
        expect(JSON.stringify(result.calls)).toContain(HOLD);
        await setState(CONTROL, "owner_override");
        await expect(page.getByText("Automatic heating: on hold")).toBeVisible();
        result = await tap("Automatic heating: on hold");
        expect(JSON.stringify(result.calls)).toContain(RESUME);
        await setState(CONTROL, "fault_locked");
        await expect(page.getByText("Automatic heating: not available")).toBeVisible();
        result = await tap("Automatic heating: not available");
        expect(result.calls).toEqual([]);
        await setState(CONTROL, "observing");
        await expect(page.locator("hui-history-graph-card").first()).toBeVisible();
        await page.keyboard.press("Escape");
        await page.waitForTimeout(600);
        await page.screenshot({ path: `${output}/hot-water-${size.name}.png`, fullPage: true });

        // Bathrooms view: charts built from the original sensors and the physical relays.
        await goHome("bathrooms");
        await expect(page.locator("hui-history-graph-card")).toHaveCount(4);
        await expect(page.getByText("Learned background humidity").first()).toBeVisible();
        await expect(page.getByText("Why the fan is in this state").first()).toBeVisible();
        await expect(page.getByText("Humidity is normal; the fan is not needed.").first()).toBeVisible();
        await expect(page.getByText("Drying time left").first()).toBeVisible();
        await expect(page.getByText("Run fan length (5-120 min)", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("Towel drying per shower (1-12 h)", { exact: false }).first()).toBeVisible();
        await expect(page.getByText("Tapo Controller Settings").first()).toBeVisible();
        // the setting tiles open the integration's own number entity (a typed value); nothing is set by looking
        await clearCalls();
        expect(await calls()).toEqual([]);
        // Bathroom fan: automatic / manual / off / unknown; towel: queued request stays cancellable.
        await setState(FAN, "on", { summary: "On — automatic, drying the room" });
        await setState(FAN_SWITCH, "off");
        await expect(page.getByText("Fan: automatic").first()).toBeVisible();
        await setState(FAN_SWITCH, "on");
        await expect(page.getByText("Fan: manual").first()).toBeVisible();
        result = await tap("Fan: manual", { first: true });
        expect(JSON.stringify(result.calls)).toContain("turn_off");
        await setState(FAN_SWITCH, "off");
        await setState(FAN, "off", { summary: "Off — normal" });
        await expect(page.getByText("Fan: off").first()).toBeVisible();
        result = await tap("Fan: off", { first: true });
        expect(JSON.stringify(result.calls)).toContain(FAN_SWITCH);
        await setState(FAN, "unavailable");
        await expect(page.getByText("Fan: status unknown").first()).toBeVisible();
        result = await tap("Fan: status unknown", { first: true });
        expect(result.calls).toEqual([]);
        await setState(FAN, "off", { summary: "Off — normal" });
        await setState(TOWEL, "off", { summary: "Waiting for off-peak — 4h 00m left (manual)" });
        await setState(TOWEL_SWITCH, "on"); // queued request, relay still off (tariff pause)
        await expect(page.getByText("Towel rail: manual").first()).toBeVisible();
        result = await tap("Towel rail: manual", { first: true });
        expect(JSON.stringify(result.calls)).toContain("turn_off");
        await setState(TOWEL_SWITCH, "off");
        await setState(TOWEL, "on", { summary: "Heating — 3h 10m left (automatic)" });
        await expect(page.getByText("Towel rail: automatic").first()).toBeVisible();
        await setState(TOWEL, "off", { summary: "Off — no drying scheduled" });
        await page.evaluate(() => {
          window.scrollTo(0, 0);
          const walk = (root) => {
            for (const el of root.querySelectorAll("*")) {
              if (el.scrollTop > 0) el.scrollTop = 0;
              if (el.shadowRoot) walk(el.shadowRoot);
            }
          };
          walk(document);
        });
        await page.waitForTimeout(400);
        await page.screenshot({ path: `${output}/bathrooms-${size.name}.png`, fullPage: true });

        // Doors: plain-English status, no raw state, no actuation.
        await goHome("doors");
        await expect(page.getByText("lock status not available", { exact: false }).first()).toBeVisible();
        expect(await page.getByText("lock_integration_unavailable").count()).toBe(0);
        const body = await page.locator("body").innerText();
        for (const forbidden of [/open garage/i, /close garage/i, /unlock/i]) expect(body).not.toMatch(forbidden);
        await page.screenshot({ path: `${output}/doors-${size.name}.png`, fullPage: true });


        // Device Energy: discovery from the registries, tables, totals, sorting, history, no zeros.
        await goHome("device-energy");
        const FIND_ALL = `(() => {
          const out = [];
          const walk = (root) => {
            for (const el of root.querySelectorAll("*")) {
              if (el.tagName === "THERMOWATT-DEVICE-ENERGY-CARD") out.push(el);
              if (el.shadowRoot) walk(el.shadowRoot);
            }
          };
          walk(document);
          return out;
        })()`;
        const deepCard = () =>
          page.evaluate(
            `${FIND_ALL}.reduce((n, c) => n + (c.shadowRoot ? c.shadowRoot.querySelectorAll("table").length : 0), 0)`
          );
        await expect.poll(deepCard, { timeout: 30000 }).toBeGreaterThanOrEqual(4);
        const deviceText = async () =>
          (await page.evaluate(`${FIND_ALL}.map((c) => (c.shadowRoot ? c.shadowRoot.textContent : "")).join(" ")`)).replace(/\s+/g, " ");
        const energyText = await deviceText();
        console.log("device energy text:", energyText.slice(0, 600));
        for (const device of ["Dryer", "Fridge plug", "Server plug"]) expect(energyText).toContain(device);
        expect(energyText).not.toContain("Hall light"); // no energy capability: never listed as zero
        expect(energyText).not.toContain("Tapo P110"); // the configured (user) name is used
        expect(energyText).toContain("1 without energy monitoring");
        expect(energyText).toContain("estimated tariff-valued operating costs");
        expect(energyText).toContain("est."); // the power-only device is flagged as an estimate
        expect(energyText).toMatch(/Total \(3 devices/);
        expect(energyText).toMatch(/\$\d+\.\d\d/);
        expect(energyText).toContain("Previous completed months");
        expect(energyText).toContain("Last seven days");
        expect(energyText).toContain("Reconstructed from long-term statistics"); // history is not an archive
        expect(energyText).toContain("≈$"); // current prices applied to history are labelled as assumed
        expect(energyText).toContain("Statistics as of");
        // Whole-house energy balance: the ten figures, a Sankey diagram, the period toggle, energy only.
        for (const label of [
          "Whole-house energy balance",
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
          expect(energyText).toContain(label);
        }
        const sankey = () =>
          page.evaluate(`(() => {
            const card = ${FIND_ALL}.find((c) => c.shadowRoot && c.shadowRoot.querySelector("svg.sankey"));
            if (!card) return null;
            const svg = card.shadowRoot.querySelector("svg.sankey");
            const box = svg.getBoundingClientRect();
            return { width: Math.round(box.width), height: Math.round(box.height), paths: svg.querySelectorAll("path").length, text: svg.textContent, label: svg.getAttribute("aria-label") };
          })()`);
        const diagram = await sankey();
        if (diagram === null) {
          // the first hour after local midnight has no complete hour yet: the balance says it is collecting
          expect(energyText).toContain("collecting");
        } else {
          expect(diagram.paths).toBe(5);
          if (size.width >= 640) {
            expect(diagram.text).toContain("Solar");
            expect(diagram.text).toContain("Household");
            expect(diagram.text).toContain("Unmeasured");
          } else {
            expect(diagram.text).toBe(""); // no unreadably small labels on a phone: a legend instead
            expect(energyText).toContain("Unmeasured");
          }
          expect(diagram.width).toBeGreaterThan(Math.min(size.width, 400) * 0.6);
          expect(energyText).toMatch(/Monitored share of household\s*[≈≥]?\s*\d+%/);
          // the seeded Dryer's own daily counter disagrees with its statistics: the cross-check flags it (and only it)
          expect(energyText).toMatch(/Dryer.{0,60}≠ device counter/);
          expect(energyText).not.toMatch(/Fridge plug.{0,60}≠ device counter/);
          expect(energyText).not.toMatch(/withheld|NaN|undefined/);
          // the toggle redraws the diagram for the month
          await page.evaluate(`(() => {
            const card = ${FIND_ALL}.find((c) => c.shadowRoot && c.shadowRoot.querySelector("button[data-balance]"));
            card.shadowRoot.querySelector('button[data-balance="month"]').click();
          })()`);
          await expect
            .poll(async () => (await sankey()).label, { timeout: 5000 })
            .not.toBe(diagram.label);
        }
        const sorted = await page.evaluate(`(() => {
          const cards = ${FIND_ALL};
          const root = cards.map((c) => c.shadowRoot).find((r) => r && r.querySelector('button[data-table="daily"]'));
          root.querySelector('button[data-table="daily"][data-sort="name"]').click();
          return [...root.querySelectorAll("table")[0].querySelectorAll("tbody tr td:first-child")].map((td) => td.textContent.trim().split(" ")[0]);
        })()`);
        expect(sorted).toEqual([...sorted].sort((a, b) => a.localeCompare(b)));
        // Layout: the parts must use the available width (three columns on a wide screen, one on a phone).
        const boxes = await page.evaluate(`${FIND_ALL}.map((c) => { const r = c.getBoundingClientRect(); return { left: Math.round(r.left), width: Math.round(r.width) }; })`);
        expect(boxes.length).toBe(6); // balance, summary, week, monthly, daily, history
        if (size.width >= 1280) {
          expect(new Set(boxes.map((b) => b.left)).size).toBeGreaterThanOrEqual(2); // columns side by side
          expect(boxes[0].width).toBeGreaterThan(size.width * 0.45); // the balance hero spans two columns
          for (const b of boxes) expect(b.width).toBeGreaterThan(size.width / 5);
        } else if (size.width <= 500) {
          for (const b of boxes) expect(b.width).toBeGreaterThan(size.width * 0.8);
        }
        const overflowDevice = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflowDevice).toBeLessThanOrEqual(2);
        await page.screenshot({ path: `${output}/device-energy-${size.name}.png`, fullPage: true });

        // System and Energy views.
        await goHome("system");
        await expect(page.getByText("No problems detected").first()).toBeVisible();
        await expect(page.getByText("Observing: checking the heater before acting")).toBeVisible();
        await page.screenshot({ path: `${output}/system-${size.name}.png`, fullPage: true });
        await goHome("energy");
        await expect(page.getByText("4.123 kW")).toBeVisible();
        await expect(page.getByText("Whole-house balance").first()).toBeVisible(); // compact balance under today's energy
        await expect(page.getByText("Household used").first()).toBeVisible();
        await page.screenshot({ path: `${output}/energy-${size.name}.png`, fullPage: true });
      }
      report.push({ size: size.name, ...facts, motion });
    }

    // Reduced motion: static arrows still show the flow direction and nothing animates.
    const calm = await newContext({ reducedMotion: "reduce", viewport: { width: 1280, height: 800 } });
    await prepare(calm);
    const calmPage = await calm.newPage();
    await calmPage.goto("http://127.0.0.1:8123/home-test/home");
    await calmPage.waitForFunction(() => !!customElements.get("thermowatt-power-flow-card"));
    await expect(calmPage.getByText("4.123 kW")).toBeVisible();
    const quiet = await calmPage.evaluate(() => {
      const find = (root) => {
        for (const el of root.querySelectorAll("*")) {
          if (el.tagName === "THERMOWATT-POWER-FLOW-CARD") return el;
          if (el.shadowRoot) {
            const hit = find(el.shadowRoot);
            if (hit) return hit;
          }
        }
        return null;
      };
      const el = find(document);
      return {
        animated: el.shadowRoot.querySelectorAll("animateMotion").length,
        staticArrows: el.shadowRoot.querySelectorAll(".static-arrow").length,
      };
    });
    expect(quiet.animated).toBe(0);
    expect(quiet.staticArrows).toBeGreaterThan(0);
    await calm.close();

    if (errors.length) console.log("page errors:", errors.slice(0, 5));
    console.log(JSON.stringify({ ok: true, report }));
  } catch (error) {
    await page.screenshot({ path: `${output}/failure.png`, fullPage: true }).catch(() => {});
    console.error(String(error));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main();

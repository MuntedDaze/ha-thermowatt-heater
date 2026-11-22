/* Real Home Assistant Lovelace only: renders the generated Home dashboard on desktop and phone
 * widths, drives state through a test-only view, and checks which service call a tap WOULD send
 * (calls are recorded by the disposable server, never executed). */
const { chromium, expect } = require("@playwright/test");
const fs = require("node:fs");
const fixture = JSON.parse(fs.readFileSync("/private/browser.json", "utf8"));
const output = "/results";
const MODE = "sensor.thermann_shadow_hot_water_operating_mode";
const START = "button.thermann_shadow_start_guest_mode_12_h";
const CANCEL = "button.thermann_shadow_cancel_guest_mode";
const FAN = "binary_sensor.tapo_smart_controller_main_bathroom_fan_running";
const FAN_SWITCH = "switch.tapo_smart_controller_main_bathroom_fan_manual_override";

async function main() {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 960 }, locale: "en-AU" });
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    return url.hostname === "127.0.0.1" ? route.continue() : route.abort();
  });
  await context.addInitScript((auth) => {
    localStorage.setItem("hassTokens", JSON.stringify(auth));
    localStorage.setItem("selectedLanguage", "en");
  }, fixture.auth);
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (["error", "warning"].includes(m.type())) console.log("console:", m.type(), m.text().slice(0, 300));
  });
  page.on("websocket", (ws) =>
    ws.on("framesent", (f) => {
      if (String(f.payload).includes("call_service")) console.log("ws call_service:", String(f.payload).slice(0, 300));
    })
  );
  const hassCall = (method, path, body) =>
    page.evaluate(([m, p, b]) => document.querySelector("home-assistant").hass.callApi(m, p, b), [method, path, body]);
  const setState = (entity_id, state, attributes = {}) => hassCall("POST", "home_ui_state", { entity_id, state, attributes });
  // The power-flow card requires a W/kW unit, exactly like the real GoodWe entities provide.
  const power = (entity_id, state) => setState(entity_id, state, { unit_of_measurement: "W" });
  const calls = () => hassCall("GET", "home_ui_calls");
  const clearCalls = () => hassCall("DELETE", "home_ui_calls");
  const confirmIfAsked = async () => {
    // HA shows its own confirmation dialog for tap actions with `confirmation`.
    for (const name of ["Yes", "OK", "Confirm", "Continue"]) {
      const byRole = page.getByRole("button", { name, exact: true }).filter({ visible: true });
      const byText = page.getByText(name, { exact: true }).filter({ visible: true });
      for (const candidate of [byRole, byText]) {
        if (await candidate.first().isVisible({ timeout: 1500 }).catch(() => false)) {
          await candidate.first().click({ force: true });
          return true;
        }
      }
    }
    const dialogs = await page.locator("ha-dialog, ha-wa-dialog, dialog-box").allInnerTexts().catch(() => []);
    console.log("no confirmation button found; dialogs:", JSON.stringify(dialogs));
    await page.screenshot({ path: `${output}/no-confirm.png` }).catch(() => {});
    return false;
  };
  let httpConfirmed = false;
  const report = [];

  try {
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      await page.goto("http://127.0.0.1:8123/home-test/home");
      if (!httpConfirmed) {
        const confirm = page.locator("dialog-http-pending-config").getByRole("button", { name: "Confirm", exact: true });
        if (await confirm.isVisible({ timeout: 8000 }).catch(() => false)) await confirm.click({ force: true });
        httpConfirmed = true;
      }
      // The dashboard itself must load: no configuration error cards.
      await expect(page.getByText("kW", { exact: false }).first()).toBeVisible();
      expect(await page.locator("hui-error-card").count()).toBe(0);
      expect(await page.getByText("Configuration error", { exact: false }).count()).toBe(0);

      // Power-flow card: custom element, SVG, kW to 3 dp, dynamic grid label, motion.
      await page.waitForFunction(() => !!customElements.get("thermowatt-power-flow-card"));
      await expect(page.getByText("4.123 kW")).toBeVisible();
      await expect(page.getByText("Grid Export", { exact: true })).toBeVisible();
      const moved = await page.evaluate(async () => {
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
      expect(moved.chevrons).toBeGreaterThan(0);
      expect(moved.moved).toBeGreaterThan(0);
      await power("sensor.goodwe_inverter_meter_active_power", "-2200");
      await power("sensor.goodwe_inverter_pv_power", "800");
      await power("sensor.goodwe_inverter_house_consumption", "3000");
      await expect(page.getByText("Grid Import", { exact: true })).toBeVisible();
      await power("sensor.goodwe_inverter_meter_active_power", "unavailable");
      await expect(page.getByText("Grid Unavailable", { exact: true })).toBeVisible();
      await power("sensor.goodwe_inverter_meter_active_power", "2923");
      await power("sensor.goodwe_inverter_pv_power", "4123");
      await power("sensor.goodwe_inverter_house_consumption", "1200");

      // 12 h override: ON / OFF / unknown, with the existing buttons only.
      await setState(MODE, "automatic");
      await expect(page.getByText("12 h override: OFF")).toBeVisible();
      await clearCalls();
      await page.getByText("12 h override: OFF").click({ force: true });
      await page.screenshot({ path: `${output}/after-click-${width}.png` });
      await confirmIfAsked();
      await expect.poll(async () => (await calls()).map((c) => c.service)).toContain("button.press");
      expect(JSON.stringify(await calls())).toContain(START);
      await setState(MODE, "guest");
      await expect(page.getByText("12 h override: ON")).toBeVisible();
      await clearCalls();
      await page.getByText("12 h override: ON").click({ force: true });
      await confirmIfAsked();
      await expect.poll(async () => JSON.stringify(await calls())).toContain(CANCEL);
      await setState(MODE, "unavailable");
      await expect(page.getByText("12 h override: status unknown")).toBeVisible();
      await clearCalls();
      await page.getByText("12 h override: status unknown").click({ force: true });
      await page.waitForTimeout(800);
      expect(await calls()).toEqual([]); // inert

      // Bathroom fan toggle: automatic vs manual vs off vs unknown (and no command when unknown).
      await setState(FAN, "on", { summary: "On — automatic, drying the room" });
      await setState(FAN_SWITCH, "off");
      await expect(page.getByText("Fan: automatic").first()).toBeVisible();
      await setState(FAN_SWITCH, "on");
      await expect(page.getByText("Fan: manual").first()).toBeVisible();
      await setState(FAN_SWITCH, "off");
      await setState(FAN, "off", { summary: "Off — normal" });
      await expect(page.getByText("Fan: off").first()).toBeVisible();
      await clearCalls();
      await page.getByText("Fan: off").first().click({ force: true });
      await expect.poll(async () => JSON.stringify(await calls())).toContain(FAN_SWITCH);
      await setState(FAN, "unavailable");
      await expect(page.getByText("Fan: status unknown").first()).toBeVisible();
      await clearCalls();
      await page.getByText("Fan: status unknown").first().click({ force: true });
      await page.waitForTimeout(800);
      expect(await calls()).toEqual([]);
      await setState(FAN, "off", { summary: "Off — normal" });

      // No garage motor or lock controls anywhere on the page.
      const body = await page.locator("body").innerText();
      for (const forbidden of [/open garage/i, /close garage/i, /unlock/i]) expect(body).not.toMatch(forbidden);

      // Phone: no horizontal scroll.
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(2);
      await page.screenshot({ path: `${output}/home-${width}.png`, fullPage: true });
      report.push({ width, moved, overflow });
    }
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

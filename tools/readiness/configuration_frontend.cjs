/* Real HA frontend only: Playwright shares the loopback-only HA container's
 * network namespace. No mocked forms or synthetic frontend components. */
const { chromium, expect } = require("@playwright/test");
const fs = require("node:fs");
const fixture = JSON.parse(fs.readFileSync("/private/browser.json", "utf8"));
const translations = JSON.parse(fs.readFileSync("/workspace/custom_components/thermann_shadow/strings.json", "utf8"));
const steps = translations.options.step;
const output = "/results";

async function main() {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 960 }, locale: "en-AU" });
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    return url.hostname === "127.0.0.1" ? route.continue() : route.abort();
  });
  await context.addInitScript(auth => {
    localStorage.setItem("hassTokens", JSON.stringify(auth));
    localStorage.setItem("selectedLanguage", "en");
  }, fixture.auth);
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const reports = [];
  let confirmedHttp = false;
  const fieldText = label => new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\*?$`);
  const field = label => page.getByText(fieldText(label)).or(page.getByLabel(label, { exact: false })).filter({ visible: true }).first();
  const snapshot = () => page.evaluate(() => document.querySelector("home-assistant").hass.callApi("GET", "thermann_ui_snapshot"));
  const paths = {
    hot_water: [], prices: ["electricity"], peak_times: ["electricity"],
    tariff_json: ["electricity"], schedule: ["electricity"], solar: ["solar_meters"],
    sources: ["solar_meters"], equipment: ["advanced"], polling: ["advanced"],
    commissioning: ["advanced"], bridge_sources: ["advanced"], period: ["electricity", "schedule"],
  };
  try {
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      for (const [id, parents] of Object.entries(paths)) {
        await page.goto("http://127.0.0.1:8123/config/integrations/integration/thermann_shadow");
        // Open the actual options dialog through the integration's own control.
        const configure = page.getByRole("button", { name: "Configure", exact: true }).last();
        await expect(configure).toBeVisible();
        // Fresh disposable HA asks to confirm its loopback-only HTTP binding.
        // This is the isolated fixture, never the owner's installed HA.
        const pending = page.locator("dialog-http-pending-config");
        if (!confirmedHttp) {
          // The dialog host has no box itself. Wait for its actual button;
          // checking the host's visibility races the initial WS notification.
          const confirm = pending.getByRole("button", { name: "Confirm", exact: true });
          await confirm.click();
          await expect(confirm).not.toBeVisible();
          confirmedHttp = true;
        }
        await configure.click();
        await expect(page.getByText("Hot Water", { exact: true })).toBeVisible();
        if (id === "hot_water") await page.screenshot({ path: `${output}/menu-${width}.png` });
        for (const target of [...parents, ...(id === "period" ? [] : [id])]) {
          await page.getByText(steps[target].title, { exact: true }).last().click();
        }
        if (id === "period") {
          await page.getByText("Add a period", { exact: true }).click();
          await page.getByRole("button", { name: "Submit", exact: true }).click();
        }
        for (const label of Object.values(steps[id].data || {})) {
          await expect(field(label)).toBeVisible();
        }
        // Check actual rendered inline help, not just downloaded translations.
        for (const help of Object.values(steps[id].data_description || {})) {
          await expect(page.getByText(help, { exact: true }).first()).toBeVisible();
        }
        const overflow = await page.evaluate(() => {
          const all = [];
          function visit(root) {
            for (const el of root.querySelectorAll("*")) {
              if (el.shadowRoot) visit(el.shadowRoot);
              if (el.tagName === "HA-FORM") all.push(el);
            }
          }
          visit(document);
          return all.some(form => form.scrollWidth > form.clientWidth + 2);
        });
        if (overflow) throw new Error(`Horizontal form overflow: ${id} ${width}`);
        await page.screenshot({ path: `${output}/${id}-${width}.png` });
        const labels = Object.values(steps[id].data || {});
        if (labels.length) {
          // Some native floating labels use display:contents. Scroll the real
          // form's container instead of asking that label to have its own box.
          await page.locator("ha-form").last().evaluate(form => form.scrollIntoView({ block: "end", behavior: "instant" }));
          await page.screenshot({ path: `${output}/${id}-bottom-${width}.png` });
        }
        if (["hot_water", "prices", "sources"].includes(id)) {
          const before = await snapshot();
          const saved = page.waitForResponse(response => response.url().includes("/options/flow/") && response.request().method() === "POST");
          await page.getByRole("button", { name: "Submit", exact: true }).click();
          expect((await (await saved).json()).type).toBe("create_entry");
          expect(await snapshot()).toEqual(before);
        }
        reports.push({ page: id, width, labels: Object.keys(steps[id].data || {}).length, inline_help: true, overflow: false });
        console.log(`Rendered ${id} at ${width}px with inline help`);
      }
    }
    fs.writeFileSync(`${output}/frontend-results.json`, JSON.stringify({ real_home_assistant: true, reports }, null, 2));
  } catch (error) {
    await page.screenshot({ path: `${output}/failure.png` });
    const text = await page.evaluate(() => {
      const parts = [];
      function walk(root) {
        for (const child of root.childNodes) {
          if (child.nodeType === Node.TEXT_NODE) parts.push(child.textContent);
          else if (child.nodeType === Node.ELEMENT_NODE && !["STYLE", "SCRIPT"].includes(child.tagName)) {
            walk(child); if (child.shadowRoot) walk(child.shadowRoot);
          }
        }
      }
      walk(document.body); return parts.join(" ").replace(/\s+/g, " ");
    });
    fs.writeFileSync(`${output}/failure-text.txt`, text);
    throw error;
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });

// Browser smoke test: upload -> set up figure -> extract -> edit -> validate -> CSV.
// Usage: node smoke.mjs <base_url> <pdf> <card.json> [screenshot_dir]
import { createRequire } from "module";
import fs from "fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [base, pdf, cardPath, shots] = process.argv.slice(2);
const card = JSON.parse(fs.readFileSync(cardPath, "utf8"));
const pc = card.panels[0];
const errors = [];
const fail = (m) => { throw new Error(m); };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => {
  // expected 404s (e.g. no saved card yet) are logged by the browser itself
  if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(m.text());
});
page.setDefaultTimeout(30000);

async function drag(svgSel, box) {
  const pts = await page.$eval(svgSel, (svg, b) => {
    const m = svg.getScreenCTM();
    const f = (x, y) => { const p = new DOMPoint(x, y).matrixTransform(m); return [p.x, p.y]; };
    return [f(b[0], b[1]), f(b[2], b[3])];
  }, box);
  await page.mouse.move(...pts[0]);
  await page.mouse.down();
  await page.mouse.move((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2, { steps: 5 });
  await page.mouse.move(...pts[1], { steps: 5 });
  await page.mouse.up();
}

try {
  // 1 upload
  await page.goto(base + "/");
  await page.setInputFiles("#pdf-file", pdf);
  await page.fill("#citekey", "Smoke2026");
  await page.getByRole("button", { name: "Upload and find figures" }).click();
  await page.waitForURL(/#\/s\/[A-Za-z0-9_-]{32}/);
  const token = page.url().match(/#\/s\/([A-Za-z0-9_-]{32})/)[1];
  if (shots) await page.screenshot({ path: `${shots}/1-session.png` });

  // 2 set up (manual route: synthetic PDFs have no detectable caption)
  await page.goto(`${base}/#/s/${token}/fig/2/setup?page=1`);
  const svgSel = 'svg[aria-label^="Page 1 of the PDF"]';
  await page.waitForSelector(svgSel);
  // wait until the initial fit has settled (viewBox unchanged for 500 ms)
  let vb = null;
  for (let i = 0; i < 40; i++) {
    const v = await page.$eval(svgSel, (s) => s.getAttribute("viewBox"));
    if (v && v === vb) break;
    vb = v;
    await page.waitForTimeout(500);
  }
  await page.getByRole("button", { name: "Draw panel box" }).click();
  await drag(svgSel, pc.bbox_pt);
  await page.getByText(/ticks found/).first().waitFor();
  await page.getByRole("button", { name: "Draw legend box" }).click();
  await drag(svgSel, pc.legend.bbox_pt);
  await page.getByRole("textbox", { name: "Series 6 name" }).waitFor();
  await page.fill("#x-title", pc.x.title);
  await page.fill("#x-unit", pc.x.unit);
  await page.fill("#x-ticks", pc.x.ticks.join(", "));
  await page.fill("#y-title", pc.y.title);
  await page.fill("#y-unit", pc.y.unit);
  await page.fill("#y-ticks", pc.y.ticks.join(", "));
  if (!(await page.isChecked("#y-inv"))) await page.check("#y-inv");
  for (let i = 0; i < pc.series.length; i++)
    await page.getByRole("textbox", { name: `Series ${i + 1} name` }).fill(pc.series[i].label);
  if (shots) await page.screenshot({ path: `${shots}/2-setup.png` });
  await page.getByRole("button", { name: /Extract points/ }).click();
  await page.waitForURL(/\/review/);

  // 3 review: data from the API must match what the UI submitted
  const api = (p, o) => page.evaluate(async ([p, o]) => (await fetch(p, o)).json(), [p, o]);
  let rv = await api(`/api/s/${token}/figures/2`);
  const pts = rv.panels[0].blocks.main.points;
  if (pts.length !== 38) fail(`expected 38 points, got ${pts.length}`);
  await page.getByRole("button", { name: /Mark validated/ }).waitFor();
  if (shots) await page.screenshot({ path: `${shots}/3-review.png` });

  // edit a value in the table via the API path the UI uses, then validate in the UI
  await page.keyboard.press("Escape");
  const before = rv.n_edits;
  const firstCell = page.locator("table input").first();
  await firstCell.fill("42");
  await firstCell.press("Enter");
  await page.waitForFunction(async ([t, b]) => (await (await fetch(`/api/s/${t}/figures/2`)).json()).n_edits > b,
    [token, before]);
  await page.getByRole("button", { name: /Mark validated/ }).click();
  await page.getByText(/Validated/).first().waitFor();
  rv = await api(`/api/s/${token}/figures/2`);
  if (!rv.validation || !rv.validation.validated) fail("figure not validated");
  const csv = await page.evaluate(async (t) => (await fetch(`/api/s/${t}/figures/2/points.csv`)).text(), token);
  if (!csv.includes("manuell geprüft")) fail("CSV lacks validated confidence");
  if (shots) await page.screenshot({ path: `${shots}/4-validated.png` });

  // 4 narrow width: no horizontal scroll
  await page.setViewportSize({ width: 400, height: 800 });
  await page.waitForTimeout(300);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 1) fail(`horizontal scroll at 400px: ${overflow}px`);

  if (errors.length) fail("JS errors: " + errors.join(" | "));
  console.log("SMOKE OK", JSON.stringify({ points: pts.length, n_edits: rv.n_edits }));
} catch (e) {
  if (shots) await page.screenshot({ path: `${shots}/failure.png` }).catch(() => {});
  console.error("SMOKE FAIL", e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}

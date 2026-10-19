#!/usr/bin/env node
/**
 * Take the screenshots used in the README, from the real app.
 *
 *   npm run build && node scripts/readme-screenshots.mjs   # -> ../docs/screenshots/
 *
 * Runs the built frontend against the demo server (scripts/demo), and
 * walks one story: connect Google, give an AI Employee tools, assign a
 * task, watch it run and delegate, approve the email, see the result.
 * Needs Playwright with Chromium.
 */

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const OUT = resolve(new URL("../../docs/screenshots", import.meta.url).pathname);
const PORT = 8014;
const BASE = `http://localhost:${PORT}`;
mkdirSync(OUT, { recursive: true });

const server = spawn(process.execPath, [new URL("./demo/server.mjs", import.meta.url).pathname], {
  env: { ...process.env, DEMO_PORT: String(PORT), DEMO_SLOW: "1" },
  stdio: ["ignore", "pipe", "inherit"],
});
await new Promise((ready) => server.stdout.once("data", ready));

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
// The floating help button would sit on top of every picture.
await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => { const st = document.createElement("style"); st.textContent = ".coach-help{display:none!important}"; document.head.appendChild(st); }));
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const shot = async (name, settle = 900) => {
  await page.waitForTimeout(settle);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`docs/screenshots/${name}.png`);
};
const api = async (path) => (await fetch(`${BASE}/api/v1/orgs/victopia${path}`)).json();
async function until(check, timeoutMs = 30000) {
  const end = Date.now() + timeoutMs;
  while (!(await check())) {
    if (Date.now() > end) throw new Error("timed out waiting for the demo run");
    await new Promise((r) => setTimeout(r, 400));
  }
}

try {
  await page.goto(`${BASE}/product`);
  await page.evaluate(() => document.fonts.ready);
  await shot("01-landing", 2500);

  await page.goto(`${BASE}/connections`);
  await page.getByRole("button", { name: "Connect Google Workspace" }).click();
  await page.getByText("ops@victopia.com").first().waitFor();
  await shot("02-connections", 1200);

  await page.goto(`${BASE}/employees`);
  await page.locator("article", { hasText: "Operations Analyst" }).getByRole("button", { name: /Tools/ }).click();
  const pack = page.locator("aside").locator("details", { hasText: "Google Workspace" });
  await pack.locator("summary").click();
  for (const tool of ["Search Gmail", "Send a Gmail email"]) {
    await pack.locator("label").filter({ has: page.getByText(tool, { exact: true }) }).locator("input").check();
  }
  // The panel is taller than the window; a taller window keeps the
  // employee cards and the ticked Gmail tools in one picture.
  await page.setViewportSize({ width: 1440, height: 1500 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot("03-tool-picker");
  await page.setViewportSize({ width: 1440, height: 900 });

  // Plain-English setup: the three questions that make an AI Employee.
  await page.goto(`${BASE}/employees`);
  await page.getByRole("button", { name: "New AI Employee" }).click();
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Asha");
  await page.getByRole("textbox", { name: "Job title", exact: true }).fill("Support Lead");
  await page.getByPlaceholder("Read new support emails and draft a reply to each one.").fill("Sort the support inbox and draft first replies.");
  await page.getByPlaceholder("Never promise a refund. Never email a customer without approval.").fill("Never promise refunds. Never email without approval.");
  await page.getByPlaceholder("Before anything goes to a customer.").fill("Before anything goes to a customer.");
  await shot("12-new-employee");

  await page.goto(`${BASE}/providers`);
  await shot("13-own-ai-key", 1200);

  await page.goto(`${BASE}/tasks`);
  const form = page.locator("form", { hasText: "Assign work" });
  await page.getByPlaceholder(/What should it do/).fill("Why did checkouts fail overnight? Email the ops team a summary.");
  await form.getByRole("switch", { name: "Dry run" }).click();
  await form.screenshot({ path: `${OUT}/15-dry-run.png` });
  console.log("docs/screenshots/15-dry-run.png");
  await form.getByRole("switch", { name: "Dry run" }).click();
  await page.getByRole("button", { name: /Assign to Ravi/ }).click();

  // Wait until the run has started steps in parallel, then show it.
  const [newest] = await api("/tasks");
  const runId = (await api(`/tasks/${newest.id}`)).run.id;
  await until(async () => (await api(`/runs/${runId}/trace`)).events.some((e) => e.type === "tool_result" && e.tool === "get_webpage"));
  await shot("04-live-run", 900);
  await page.locator("section[aria-label='Run']").screenshot({ path: `${OUT}/14-parallel-steps.png` });
  console.log("docs/screenshots/14-parallel-steps.png");

  const run = page.locator("section[aria-label='Run']");
  await run.getByRole("button", { name: /Agent tree/ }).click();
  await until(async () => (await api("/approvals")).length > 0);
  await shot("05-agent-tree", 1500);

  await page.goto(`${BASE}/approvals`);
  await shot("06-approvals", 1200);

  const [approval] = await api("/approvals");
  await page.goto(`${BASE}/approve/${approval.id}?action=approve`);
  await shot("07-approve-from-email", 1200);
  await page.getByRole("button", { name: /Hold to approve/ }).click({ delay: 1500 });
  await page.waitForTimeout(500);

  const [task] = await api("/tasks");
  await until(async () => (await api(`/tasks/${task.id}`)).status === "completed");
  await page.goto(`${BASE}/tasks?task=${task.id}`);
  await page.locator("section[aria-label='Run']").getByRole("button", { name: /Result/ }).click();
  await shot("08-result", 1200);

  await page.goto(`${BASE}/memory`);
  await shot("09-memory", 1500);

  await page.goto(`${BASE}/policies`);
  await shot("10-permissions", 1500);

  await page.goto(`${BASE}/notifications`);
  await shot("11-notifications", 1200);
} finally {
  await browser.close();
  server.kill();
}

if (errors.length) {
  console.error("page errors:\n" + errors.join("\n"));
  process.exit(1);
}

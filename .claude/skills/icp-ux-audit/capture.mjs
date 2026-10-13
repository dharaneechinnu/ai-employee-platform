#!/usr/bin/env node
/**
 * Screenshot every screen as admin and member, on desktop and phone,
 * and run quick automatic checks on each one.
 *
 *   cd frontend && node ../.claude/skills/icp-ux-audit/capture.mjs <out-dir>
 *
 * Needs the app running (APP_URL, default http://localhost:5173) with
 * the DEMO.md accounts, and Playwright with Chromium.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(resolve(process.cwd(), "package.json"));
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const OUT = resolve(process.argv[2] || "ux-audit");
const APP = process.env.APP_URL || "http://localhost:5173";
mkdirSync(OUT, { recursive: true });

const DEVICES = {
  desktop: { viewport: { width: 1440, height: 900 } },
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const PUBLIC = ["/product", "/login", "/platform"];
const ROLES = {
  admin: {
    email: "owner@victopia.com",
    password: "owner-password-1234",
    pages: ["/tasks", "/employees", "/approvals", "/memory", "/members", "/connections", "/providers", "/policies", "/notifications"],
  },
  member: {
    email: "priya@victopia.com",
    password: "member-password-1234",
    pages: ["/tasks", "/employees", "/memory", "/members", "/policies"],
  },
};

/** Runs inside the page. Cheap, objective checks only. */
function inspect(isPhone) {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const name = (el) =>
    (el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
  const interactive = [...document.querySelectorAll("a[href],button,input,select,textarea,[role=button],[role=switch],[role=radio],[role=tab]")].filter(visible);

  const unnamed = interactive
    .filter((el) => ["A", "BUTTON"].includes(el.tagName) || el.getAttribute("role"))
    .filter((el) => !name(el) && !el.getAttribute("aria-labelledby") && !el.querySelector("img[alt]:not([alt=''])"))
    .map((el) => el.outerHTML.slice(0, 120));

  const unlabeled = [...document.querySelectorAll("input:not([type=hidden]),select,textarea")]
    .filter(visible)
    .filter(
      (el) =>
        !el.closest("label") &&
        !el.getAttribute("aria-label") &&
        !el.getAttribute("aria-labelledby") &&
        !(el.id && document.querySelector(`label[for="${el.id}"]`)),
    )
    .map((el) => el.outerHTML.slice(0, 120));

  const smallTargets = isPhone
    ? interactive
        .filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width < 44 || r.height < 44;
        })
        .filter((el) => !(el.tagName === "INPUT" && ["checkbox", "radio"].includes(el.type) && el.closest("label")))
        .map((el) => {
          const r = el.getBoundingClientRect();
          return `${name(el) || el.tagName.toLowerCase()} (${Math.round(r.width)}×${Math.round(r.height)})`;
        })
    : [];

  const tinyText = [];
  for (const el of document.querySelectorAll("body *")) {
    if (!visible(el)) continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (own && parseFloat(getComputedStyle(el).fontSize) < 12) tinyText.push(el.textContent.trim().slice(0, 30));
  }

  return {
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 1 ? document.documentElement.scrollWidth : 0,
    unnamed,
    unlabeled,
    smallTargets: [...new Set(smallTargets)],
    tinyText: [...new Set(tinyText)].slice(0, 15),
    tinyTextCount: tinyText.length,
    url: location.pathname,
  };
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const report = [];

async function capture(page, role, path, device, errors) {
  await page.goto(APP + path);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(900);
  const slug = path.replace(/\W+/g, "") || "home";
  const file = `${role}-${slug}-${device}.png`;
  await page.screenshot({ path: `${OUT}/${file}`, fullPage: true });
  const checks = await page.evaluate(inspect, device === "phone");
  report.push({ role, path, device, file, errors: [...errors], ...checks });
  errors.length = 0;
  console.log(file);
}

try {
  for (const [device, opts] of Object.entries(DEVICES)) {
    // Signed out.
    {
      const ctx = await browser.newContext({ ...opts, colorScheme: "dark" });
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      for (const path of PUBLIC) await capture(page, "public", path, device, errors);
      await ctx.close();
    }
    for (const [role, who] of Object.entries(ROLES)) {
      const ctx = await browser.newContext({ ...opts, colorScheme: "dark" });
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
      await page.goto(`${APP}/login`);
      await page.getByLabel(/email/i).fill(who.email);
      await page.locator("input[type=password]").fill(who.password);
      await page.locator("button[type=submit]").click();
      await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 });
      for (const path of who.pages) await capture(page, role, path, device, errors);
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}

writeFileSync(`${OUT}/checks.json`, JSON.stringify(report, null, 2));
console.log(`\n${report.length} screens → ${OUT}/checks.json`);

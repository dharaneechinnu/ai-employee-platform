#!/usr/bin/env node
/**
 * Screenshot the real Baton app for the feature tour.
 *
 *   node scripts/feature-tour/capture.mjs          # all shots
 *   node scripts/feature-tour/capture.mjs tree     # only the named ones
 *
 * Needs the local stack (Postgres, Redis, API on :8000, Vite on :5173)
 * and the demo account filled by seed.mjs. Writes, into shots/ next to
 * this file (git-ignored):
 *
 * - <name>.png: a 1440 x 900 window at device scale 2, so the stage can
 *   zoom in twice and stay sharp;
 * - boxes.js: where the things the tour points at sit on each shot
 *   (CSS pixels of that window), read by stage.html as window.BOXES, so
 *   highlight rings follow the real layout instead of hand-typed numbers.
 *
 * The whole film, from frontend/ with the stack running:
 *
 *   node scripts/feature-tour/seed.mjs        # once: fill the demo account
 *   node scripts/feature-tour/capture.mjs     # screenshots + boxes
 *   node scripts/ad-routing/render.mjs /tmp/tour.mp4 --stage scripts/feature-tour/stage.html
 *   AD_SCRIPT=scripts/feature-tour/script.json AD_CRF=30 \
 *     python3 scripts/ad/make_ad.py /tmp/tour.mp4 ../docs/feature-tour.mp4
 *
 * Everything here is the real app, signed in as the demo person (or as
 * the staff admin for the console). Only the approval link is made by
 * approval_link.py instead of arriving by email, because the recording
 * machine has no mail server.
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "shots");
const BASE = process.env.DEMO_URL ?? "http://localhost:5173";
const USER = { id: "priya", password: "Marigold-tea-2026" };
const STAFF = { email: "admin@example.com", password: "Admin-demo-2026!" };
const only = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });

const boxesFile = path.join(OUT, "boxes.js");
const BOXES = existsSync(boxesFile)
  ? JSON.parse(readFileSync(boxesFile, "utf8").replace(/^window\.BOXES = /, "").replace(/;\s*$/, ""))
  : {};

const browser = await chromium.launch({
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
});

async function session({ coach = false } = {}) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light",
    timezoneId: "Asia/Kolkata", permissions: ["microphone"],
  });
  await context.addInitScript((force) => {
    try {
      localStorage.setItem("theme", "light");
      if (force) sessionStorage.setItem("coach-force", "1");
    } catch { /* fine */ }
  }, coach);
  const page = await context.newPage();
  page.on("pageerror", (e) => console.error("page error:", e.message));
  return { context, page };
}

async function signIn(page) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Email or username").fill(USER.id);
  await page.locator("input[type=password]").fill(USER.password);
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.waitForURL(/chat/);
}

/** Where an element sits in the window, in CSS pixels. */
async function box(locator) {
  await locator.first().waitFor({ timeout: 20_000 });
  const r = await locator.first().boundingBox();
  return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
}

const rail = (page, name) => page.getByRole("navigation", { name: "Main menu" }).getByRole("link", { name: new RegExp(`^${name}`) }).first();

/**
 * The box of the card around some text: the nearest ancestor that looks
 * like a card (rounded, with a border or its own background). `outer`
 * keeps climbing to the outermost such card below maxW pixels wide.
 */
async function cardBox(page, text, { exact = false, outer = false, maxW = 1300, nth = 0 } = {}) {
  const el = page.getByText(text, { exact }).nth(nth);
  await el.waitFor({ timeout: 20_000 });
  return el.evaluate((node, [outerMost, max]) => {
    let found = null;
    for (let n = node.parentElement; n && n !== document.body; n = n.parentElement) {
      const cs = getComputedStyle(n);
      const r = n.getBoundingClientRect();
      if (r.width > max) break;
      const radius = parseFloat(cs.borderTopLeftRadius) || 0;
      const framed = parseFloat(cs.borderTopWidth) > 0 || (cs.backgroundColor !== "rgba(0, 0, 0, 0)" && cs.backgroundColor !== "transparent");
      if (radius >= 8 && framed && r.width > 60 && r.height > 30) {
        found = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
        if (!outerMost) break;
      }
    }
    return found;
  }, [outer, maxW]);
}

/** The nearest rounded card around a piece of text. */
const cardOf = (locator) => locator.first().locator("xpath=ancestor::*[contains(@class,'rounded')][1]");
const union = (a, b) => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.max(a.x + a.w, b.x + b.w) - Math.min(a.x, b.x), h: Math.max(a.y + a.h, b.y + b.h) - Math.min(a.y, b.y) });
const settle = (page, ms = 900) => page.waitForTimeout(ms);
// Hide the "?" help button and the toasts: they would sit on top of shots.
const tidy = (page) => page.addStyleTag({ content: "[aria-label='Help and tours'], .toast, [role=status].fixed { visibility: hidden !important; }" });

// ------------------------------------------------------------- the shots

const SHOTS = {
  async keys(page) {
    await rail(page, "AI keys").click();
    await page.getByRole("heading", { name: "AI keys" }).waitFor();
    await settle(page);
    const card = (name) => page.locator("button, a, div").filter({ hasText: name }).filter({ has: page.getByText(/Manage|Connect/) }).last();
    return {
      gemini: await box(card("Google Gemini")),
      groq: await box(card("Groq")),
      local: await box(card("My local model")),
      claude: await box(card("Anthropic (Claude)")),
      note: await box(page.locator("[data-coach=routing-note]")),
      grid: await box(page.getByRole("heading", { name: "AI models" }).locator("xpath=following::div[1]")),
    };
  },

  async picker(page) {
    await page.getByRole("button", { name: "New chat" }).first().click();
    await page.getByLabel("Message").waitFor();
    await settle(page);
    const select = page.getByLabel("AI model");
    const options = await select.locator("option").allTextContents();
    return {
      options,
      model: await box(page.locator("[data-coach=chat-model]").locator("xpath=..")),
      composer: await box(page.locator("[data-coach=chat-composer]")),
    };
  },

  async modes(page) {
    await page.getByRole("button", { name: "New chat" }).first().click();
    await page.getByLabel("Message").waitFor();
    await settle(page);
    const first = await cardBox(page, "Everyday questions and tasks");
    const last = await cardBox(page, "Developers: code, reviews and debugging");
    return {
      modes: union(first, last),
      study: await cardBox(page, "Students learning a subject"),
      team: await box(page.locator("[data-coach=chat-team-toggle]")),
      voice: await box(page.locator("[data-coach=voice]")),
    };
  },

  async team(page) {
    await rail(page, "Chat").click();
    await page.getByRole("link", { name: /My phone plan is/ }).first().click();
    await page.getByText("How I worked this out").first().waitFor();
    await settle(page, 800);
    await page.getByText("How I worked this out").first().click();
    const team = page.locator("[data-coach=chat-team]").first();
    await team.waitFor();
    await settle(page, 1200);
    await team.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.evaluate(() => {
      const el = document.querySelector("[data-coach=chat-team]");
      let s = el.parentElement;
      while (s && !(s.scrollHeight > s.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(s).overflowY))) s = s.parentElement;
      if (s) s.scrollTop -= 120;
    });
    await settle(page, 600);
    return {
      team: await box(team),
      answer: await box(page.locator(".chat-reply").last()),
      used: await box(page.getByText("Used", { exact: true }).first().locator("xpath=..")),
    };
  },

  async tools(page) {
    await rail(page, "Permissions").click();
    await page.getByRole("heading", { name: "Permissions" }).waitFor();
    await settle(page);
    const all = page.getByRole("button", { name: /^All\s*58/ });
    const web = page.getByRole("button", { name: /^Web\s*\d/ });
    const a = await box(all);
    const w = await box(web);
    const tabs = await box(all.locator("xpath=.."));
    // Every pack's tab, by its label: "Google Workspace", "Web", ...
    const each = {};
    for (const b of await all.locator("xpath=..").getByRole("button").all()) {
      const label = (await b.innerText()).replace(/\s*\d+\s*$/, "").trim();
      each[`tab:${label}`] = await box(b);
    }
    return { tabs, all: a, web: w, ...each };
  },

  async connections(page) {
    await rail(page, "Connections").click();
    await page.getByRole("heading", { name: "Connections" }).waitFor();
    await settle(page);
    const card = (t) => page.locator("[data-coach=connection-card]").filter({ hasText: t }).first();
    return {
      google: await box(card("Google Workspace")),
      microsoft: await box(card("Microsoft 365")),
      slack: await box(card("Slack channel")),
      teams: await box(card("Microsoft Team")),
      github: await box(card("GitHub")),
      oneclick: await box(page.getByText("One click").first()),
      secret: await box(page.getByText(/Sign-in details are encrypted/)),
    };
  },

  async draft(page) {
    await rail(page, "Chat").click();
    await page.getByRole("link", { name: /Make me an agent/ }).first().click();
    const draft = page.locator("[data-coach=agent-draft]").last();
    await draft.waitFor();
    await settle(page, 1000);
    await draft.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await settle(page, 500);
    return {
      draft: await box(draft),
      schedule: await box(page.getByText("Run on its own").locator("xpath=ancestor::div[contains(@class,'rounded')][1]")),
      ready: await box(page.getByText("Can it really do this?").locator("xpath=following-sibling::*[1]")),
      create: await box(page.getByRole("button", { name: /Create agent/ })),
      ask: await box(page.getByText("Make me an agent that sends me").first()),
    };
  },

  async agents(page) {
    await rail(page, "AI Agents").click();
    await page.getByRole("heading", { name: "AI Agents" }).waitFor();
    await settle(page, 1200);
    return {
      plan: await cardBox(page, "Every weekday at 8:00, a short plan", { outer: true, maxW: 700 }),
      inbox: await cardBox(page, "Summarises new mail every weekday morning", { outer: true, maxW: 700 }),
      readyLine: await box(page.getByText("Everything it needs is ready").first()),
      redLine: await cardBox(page, "Google Workspace is not connected"),
      schedule: await cardBox(page, "Monday to Friday at 8:00 AM"),
    };
  },

  async tree(page) {
    await page.goto(`${BASE}/agents?tab=tree`);
    const node = page.getByRole("button", { name: /Morning inbox digest/ }).first();
    await node.waitFor();
    await node.click();
    const how = page.locator("section[aria-label='How Morning inbox digest works']");
    await how.waitFor();
    await settle(page, 1200);
    await how.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.evaluate(() => window.scrollBy(0, -24));
    await settle(page, 800);
    const first = await cardBox(page, "Remembers you");
    const last = await cardBox(page, "Makes changes");
    const t1 = await cardBox(page, "Look up your memory");
    const t2 = await cardBox(page, "Save a Gmail draft");
    return {
      how: await box(how),
      trigger: union(await cardBox(page, "On schedule"), await cardBox(page, "You ask", { exact: true })),
      agent: await cardBox(page, "Your agent", { exact: true }),
      stages: union(first, last),
      tools: union(t1, t2),
      gmail: await cardBox(page, "Search Gmail"),
      result: await cardBox(page, "You get", { exact: true }),
    };
  },

  async perms(page) {
    await rail(page, "Permissions").click();
    await page.getByRole("heading", { name: "Permissions" }).waitFor();
    await settle(page);
    const row = (t) => page.locator("div.border-b, div").filter({ hasText: t }).filter({ has: page.getByRole("radiogroup") }).last();
    return {
      maths: await box(row("Do exact maths").getByRole("radiogroup")),
      slack: await box(row("Post to a Slack channel").getByRole("radiogroup")),
      teams: await box(row("Post to a Teams channel").getByRole("radiogroup")),
      undone: await box(page.getByText("Can't be undone").first()),
      slackRow: await box(row("Post to a Slack channel")),
    };
  },

  async perms2(page) {
    await rail(page, "Permissions").click();
    await page.getByRole("heading", { name: "Permissions" }).waitFor();
    await page.getByPlaceholder("Search tools").fill("send");
    await settle(page, 1000);
    const row = (t) => page.locator("div").filter({ hasText: t }).filter({ has: page.getByRole("radiogroup") }).last();
    return {
      gmail: await box(row("Send a Gmail email").getByRole("radiogroup")),
      search_gmail: await box(row("Search Gmail").getByRole("radiogroup")),
      mailbox_send: await box(row("Send an email").getByRole("radiogroup")),
      gmailRow: await box(row("Send a Gmail email")),
      search: await box(page.getByPlaceholder("Search tools")),
    };
  },

  async approvals(page) {
    await rail(page, "Approvals").click();
    await page.getByRole("heading", { name: "Approvals" }).waitFor();
    await page.getByRole("button", { name: /Approve/ }).first().waitFor();
    await settle(page);
    return {
      card: await cardBox(page, "Wants to", { outer: true }),
      buttons: await box(page.getByRole("button", { name: /Approve/ }).first().locator("xpath=..")),
      code: await box(page.getByText("Code", { exact: true }).locator("xpath=..")),
      rail: await box(rail(page, "Approvals")),
    };
  },

  async link(page) {
    const token = spawnSync("/tmp/claude-0/venv/bin/python", [path.join(here, "approval_link.py"), USER.id], {
      cwd: path.join(here, "../../../backend"), encoding: "utf8", env: { ...process.env, ENVIRONMENT: process.env.ENVIRONMENT ?? "dev" },
    });
    if (token.status !== 0) throw new Error(token.stderr);
    await page.goto(`${BASE}/approve/${token.stdout.trim()}`);
    await page.getByRole("button", { name: /Approve/ }).first().waitFor();
    await settle(page);
    return {
      buttons: await box(page.getByRole("button", { name: /Approve/ }).first().locator("xpath=..")),
      card: await box(page.getByRole("button", { name: /Approve/ }).first().locator("xpath=ancestor::main[1]")),
    };
  },

  async notify(page) {
    await rail(page, "Notifications").click();
    await page.getByRole("heading", { name: "Notifications" }).waitFor();
    await settle(page);
    return {
      channels: await box(page.locator("[data-coach=notify-channels]")),
      slack: await cardBox(page, "Post to a Slack channel you already watch.", { outer: true, maxW: 700 }),
      when: await box(page.locator("[data-coach=notify-when]")),
    };
  },

  async memory(page) {
    await rail(page, "Memory").click();
    await page.getByRole("heading", { name: "Memory" }).waitFor();
    await settle(page);
    return {
      list: await box(page.locator("[data-coach=memory-list]")),
      teach: await box(page.locator("[data-coach=memory-teach]")),
      search: await box(page.locator("[data-coach=memory-search]")),
      forget: await box(page.getByRole("button", { name: /Forget/ }).first()),
    };
  },

  async history(page) {
    await page.goto(`${BASE}/agents?tab=history`);
    const run = page.getByText("Python agrees").first();
    await run.waitFor();
    await run.click();
    await settle(page, 1800);
    return {
      list: await box(page.getByText("Python agrees").first().locator("xpath=ancestor::ul[1] | ancestor::ol[1] | ancestor::table[1]").first()).catch(() => null),
      detail: await box(page.getByText(/Replay|Who did what/).first().locator("xpath=ancestor::aside[1] | ancestor::section[1]").first()).catch(() => null),
      filters: await box(page.getByPlaceholder(/Search runs/)),
      who: await box(page.getByText(/who did what, over time/i).first().locator("xpath=..")),
      used: await box(page.getByText(/AI used/i).first().locator("xpath=..")),
    };
  },

  async cost(page) {
    await page.goto(`${BASE}/agents?tab=cost`);
    await page.getByText(/Estimated saved/i).first().waitFor();
    await settle(page, 1200);
    return {
      spent: await cardBox(page, /You spent/i),
      saved: await cardBox(page, /Estimated saved/i),
      free: await cardBox(page, /Free model share/i),
      bar: await cardBox(page, "How free and paid models were used"),
      table: await cardBox(page, "Share of use", { outer: true }),
    };
  },

  async voice(page) {
    await page.getByRole("button", { name: "New chat" }).first().click();
    await page.getByLabel("Message").waitFor();
    await settle(page, 600);
    const mic = page.locator("[data-coach=voice]");
    const before = await box(mic);
    await mic.locator("button").first().click().catch(() => mic.click());
    await settle(page, 1500);
    return {
      mic: before,
      micNow: await box(mic),
      composer: await box(page.locator("[data-coach=chat-composer]")),
    };
  },

  async welcome(page, context) {
    // A fresh browser, with tips forced on: what a new person sees first.
    await page.evaluate(() => localStorage.clear());
    await page.goto(`${BASE}/chat`);
    const dialog = page.getByRole("dialog").first();
    await dialog.waitFor({ timeout: 20_000 });
    await settle(page, 2500);
    void context;
    return { dialog: await cardBox(page, "Meet your assistant", { outer: true, maxW: 700 }) };
  },

  async platform(page) {
    await page.goto(`${BASE}/platform`);
    await page.getByLabel(/email/i).first().fill(STAFF.email);
    await page.locator("input[type=password]").fill(STAFF.password);
    await page.locator("button[type=submit]").click();
    await page.getByRole("heading", { name: "Overview" }).waitFor();
    await page.getByPlaceholder(/Search by name/).fill("gmail");
    await settle(page, 1500);
    return {
      privacy: await box(page.getByText("Private by design").locator("xpath=..")),
      counts: union(await cardBox(page, "17 active", { exact: false }), await cardBox(page, "One-click sign-in")),
    };
  },
};

// Which login each shot needs.
const STAFF_SHOTS = new Set(["platform"]);
const FRESH_SHOTS = new Set(["welcome"]);

let user = null;
for (const [name, shoot] of Object.entries(SHOTS)) {
  if (only.length && !only.includes(name)) continue;
  let s;
  if (STAFF_SHOTS.has(name)) s = await session();
  else if (FRESH_SHOTS.has(name)) {
    s = await session({ coach: true });
    await signIn(s.page);
  } else {
    if (!user) {
      user = await session();
      await signIn(user.page);
    }
    s = user;
    // The approval link page has no menu: go back into the app first.
    if (s.page.url().includes("/approve/")) await s.page.goto(`${BASE}/chat`);
  }
  await tidy(s.page);
  try {
    BOXES[name] = await shoot(s.page, s.context);
    await tidy(s.page);
    await s.page.mouse.move(1430, 890);
    await settle(s.page, 300);
    await s.page.screenshot({ path: path.join(OUT, `${name}.png`) });
    rmSync(path.join(OUT, `${name}-failed.png`), { force: true });
    console.log(`${name}: ${Object.keys(BOXES[name]).join(", ")}`);
  } catch (err) {
    console.error(`${name} failed: ${err.message.split("\n").slice(0, 3).join(" | ")}`);
    await s.page.screenshot({ path: path.join(OUT, `${name}-failed.png`) });
  }
  if (s !== user) await s.context.close();
}
writeFileSync(boxesFile, `window.BOXES = ${JSON.stringify(BOXES, null, 1)};\n`);
await browser.close();

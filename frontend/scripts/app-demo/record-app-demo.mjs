#!/usr/bin/env node
/**
 * Record the live demo: the real Baton app, used start to finish by a
 * new person, captured to an MP4 with chapter titles.
 *
 * Needs the whole stack running locally: Postgres, Redis, the API on
 * :8000 started with ALLOW_PRIVATE_URLS=true (so "Your own server" may
 * point at localhost), the arq worker (`arq app.workers.main.WorkerSettings`
 * in backend/, same env) and Vite on :5173. Then, in frontend/:
 *
 *   node scripts/app-demo/record-app-demo.mjs /tmp/app-demo.mp4
 *   AD_SCRIPT=scripts/app-demo/script.json \
 *     python3 scripts/ad/make_ad.py /tmp/app-demo.mp4 ../docs/product-demo.mp4
 *
 * The first writes the silent video and /tmp/app-demo.marks.json (when
 * each chapter starts); the second adds the Kokoro voiceover, music and
 * subtitles, and writes ../docs/product-demo.srt.
 *
 * There is no AI key on a recording machine, so this starts the scripted
 * stand-in model (model-server.mjs, a recording aid) and connects it in
 * the app as "Your own server". Everything else is real: sign-up, runs
 * through the worker, the calculator and Python tools, the helpers, the
 * approval pause, the agent and its tree.
 *
 * Each recording signs up a new person (DEMO_USER, default "priya"), so
 * the username must be free: use a fresh database or another DEMO_USER.
 * The API allows 10 sign-ups an hour from one address; restart it if a
 * few attempts used them up.
 *
 * Why half speed: a browser screencast gives about 25 frames a second.
 * The app's timers, its CSS animations, the stand-in model and this
 * script's pauses are all slowed by DEMO_SLOW, captured, then sped back
 * up, which doubles the frame rate without changing what is shown.
 */

import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const SLOW = Number(process.env.DEMO_SLOW ?? 2);
const BASE = process.env.DEMO_URL ?? "http://localhost:5173";
const USER = process.env.DEMO_USER ?? "priya";
const MODEL_URL = process.env.STANDIN_URL ?? "http://localhost:8787/v1";
const OUT = resolve(process.argv[2] ?? "/tmp/app-demo.mp4");
const FRAMES = join(tmpdir(), `app-demo-frames-${process.pid}`);

// ------------------------------------------------------------ preflight

const free = await fetch(`${BASE}/api/v1/auth/username-available?username=${USER}`).then((r) => r.json());
if (!free.available) {
  console.error(`The username "${USER}" is taken. Use a fresh database or set DEMO_USER.`);
  process.exit(2);
}

// The scripted model, slowed like everything else.
let model = null;
if (!process.env.STANDIN_URL) {
  model = spawn(process.execPath, [new URL("./model-server.mjs", import.meta.url).pathname], {
    env: { ...process.env, STANDIN_DELAY_MS: String(800 * SLOW) },
    stdio: ["ignore", "pipe", "inherit"],
  });
  await new Promise((ready) => model.stdout.once("data", ready));
  model.stdout.on("data", (d) => process.stdout.write(d));
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, colorScheme: "light" });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

// Stretch every timer in every frame (the app's polling, debounces and
// toasts) by the same factor as the animations.
await context.addInitScript((slow) => {
  const st = window.setTimeout.bind(window);
  const si = window.setInterval.bind(window);
  window.setTimeout = (fn, ms, ...a) => st(fn, (ms || 0) * slow, ...a);
  window.setInterval = (fn, ms, ...a) => si(fn, (ms || 0) * slow, ...a);
  try { localStorage.setItem("theme", "light"); } catch { /* fine */ }
}, SLOW);

const cdp = await context.newCDPSession(page);
await cdp.send("Animation.enable");
await cdp.send("Animation.setPlaybackRate", { playbackRate: 1 / SLOW });

// ------------------------------------------------------------ helpers

const wait = (ms) => page.waitForTimeout(ms * SLOW);
const stage = (fn, ...args) => page.evaluate(([f, a]) => window.stage[f](...a), [fn, args]);
const app = page.frameLocator("#app");

async function rect(locator, scroll = true) {
  await locator.waitFor({ timeout: 60_000 });
  if (scroll) await locator.evaluate((el) => el.scrollIntoView({ block: "nearest", behavior: "instant" }));
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
  });
}

async function point(locator, ms = 800) {
  const r = await rect(locator);
  ms = Math.round(ms * 0.8);
  await stage("moveToApp", r.cx, r.cy, ms);
  await wait(ms + 80);
  return r;
}

async function click(locator, ms = 800) {
  await point(locator, ms);
  await stage("click");
  await locator.click();
  await wait(250);
}

async function type(locator, text, perChar = 30) {
  await click(locator, 700);
  await locator.pressSequentially(text, { delay: perChar * SLOW });
}

async function zoom(locator, scale, at, ms = 1000) {
  const r = await rect(locator, false);
  await stage("zoom", r.cx, r.cy, scale, at, ms);
  await wait(ms + 100);
}

/** Scroll the app smoothly (at recording speed) so an element sits near the top. */
async function scrollTo(locator, offset = 90, ms = 1100) {
  await locator.waitFor();
  await locator.evaluate(
    (el, [off, dur]) =>
      new Promise((done) => {
        let box = el.parentElement;
        while (box && !(box.scrollHeight > box.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
        const scroller = box ?? document.scrollingElement;
        const top = box ? box.getBoundingClientRect().top : 0;
        const from = scroller.scrollTop;
        const to = from + el.getBoundingClientRect().top - top - off;
        const t0 = performance.now();
        // performance.now, not the frame time rAF passes in: the
        // slowed animation clock would stretch the scroll again.
        const step = () => {
          const k = Math.min(1, (performance.now() - t0) / dur);
          const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
          scroller.scrollTop = from + (to - from) * e;
          if (k < 1) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
    [offset, ms * SLOW],
  );
  await wait(150);
}

async function spotlight(locator, text, side = "right", pad = 12) {
  const r = await rect(locator, false);
  const s = await stage("spotlightApp", r.x, r.y, r.w, r.h, pad);
  await wait(550);
  if (text) {
    const at = {
      right: [s.x + s.w, s.y + s.h / 2],
      left: [s.x, s.y + s.h / 2],
      top: [s.x + s.w / 2, s.y],
      bottom: [s.x + s.w / 2, s.y + s.h],
    }[side];
    await stage("callout", at[0], at[1], text, side);
  }
}

async function unspot() {
  await stage("hideCallout");
  await stage("clearSpotlight");
  await wait(250);
}

// When each chapter starts, in finished-video seconds, for the voiceover.
const marks = [];
function mark(id, text) {
  marks.push({ id, text, t: frames.length ? frames.at(-1).t : null });
}

async function chapter(id, n, title, sub) {
  mark(id, title);
  await unspot();
  await stage("feature", n, title, sub, 1300);
  await wait(1050);
}

const rail = (name) => app.getByRole("navigation", { name: "Main menu" }).getByRole("link", { name, exact: true });
const send = () => app.getByRole("button", { name: "Send", exact: true });

// ------------------------------------------------------------ capture

mkdirSync(FRAMES, { recursive: true });
const frames = [];
cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
  const file = join(FRAMES, `f${String(frames.length).padStart(6, "0")}.jpg`);
  writeFileSync(file, Buffer.from(data, "base64"));
  frames.push({ file, t: metadata.timestamp });
  await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});

for (const kind of ["unhandledRejection", "uncaughtException"]) process.on(kind, async (err) => {
  console.error(err);
  await page.screenshot({ path: join(tmpdir(), "app-demo-failure.png") }).catch(() => {});
  model?.kill();
  process.exit(1);
});

await page.goto(`${BASE}/scripts/app-demo/stage.html`);
await page.evaluate(() => document.fonts.ready);
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
mark("intro", "Intro");
await stage("load", `${BASE}/register`);
await app.getByLabel("Username").waitFor();
await wait(2600);
await stage("showApp");
await stage("showCursor");
await stage("moveTo", 1500, 900, 0);
await wait(700);

// 1 · Sign up ---------------------------------------------------------
await chapter("signup", "01", "Sign up in seconds", "Pick a username: it checks it is free as you type");
const username = app.getByLabel("Username");
await zoom(username, 1.35, [1160, 470], 800);
await type(username, USER, 60);
await wait(900);
await spotlight(app.getByText(`${USER} is available`), "Checked as you type", "right", 8);
await wait(700);
await unspot();
await type(app.getByLabel("Email"), `${USER}@example.com`, 14);
await type(app.locator("input[autocomplete=new-password]"), "Marigold-tea-2026", 10);
await click(app.getByRole("button", { name: /Create account/ }), 600);
await stage("unzoom", 800);
await app.getByText("Connect an AI first").waitFor({ timeout: 30_000 });
await wait(600);

// 2 · Add an AI -------------------------------------------------------
await chapter("keys", "02", "Bring free AI keys", "Gemini, Groq, OpenRouter, Mistral, or your own server");
await click(app.getByRole("button", { name: "Connect an AI" }).or(app.getByRole("link", { name: "Connect an AI" })).first(), 700);
await app.getByRole("heading", { name: "AI keys" }).waitFor();
await wait(500);
await spotlight(app.getByRole("button", { name: /Google Gemini/ }).locator(".."), "Free tiers, labelled", "bottom", 8);
await wait(1000);
await unspot();
await spotlight(app.locator("[data-coach=routing-note]"), "Automatic picks the AI for each task", "bottom", 6);
await wait(1200);
await unspot();
await click(app.getByText("Your own server").first(), 700);
const panel = app.locator("aside[aria-label$='setup']");
await panel.waitFor();
await zoom(panel, 1.3, [1500, 520], 800);
await type(panel.getByLabel("Name"), "My local model", 16);
const address = panel.getByLabel("Server address");
await click(address, 500);
await address.fill("");
await address.pressSequentially(MODEL_URL, { delay: 12 * SLOW });
await click(panel.getByRole("button", { name: /Connect and test/ }), 600);
await panel.getByText("Connected and working").waitFor({ timeout: 60_000 });
await wait(400);
await spotlight(panel.getByText("Connected and working").locator("../.."), "Connected and tested", "left", 8);
await wait(1000);
await unspot();
await stage("unzoom", 700);

// 3 · Ask in Chat -----------------------------------------------------
await chapter("chat", "03", "Ask, and watch it work", "Helpers step in, every step shows live");
await click(rail("Chat"), 700);
const box = app.getByLabel("Message");
await box.waitFor();
await click(app.locator("[data-coach=chat-team-toggle]"), 600);
await type(box, "My phone plan is ₹719 every 84 days. Is the ₹2,999 yearly plan cheaper? Show the maths.", 11);
await click(send(), 500);
const reply = app.locator(".chat-reply").last();
await reply.waitFor();
await zoom(reply, 1.4, [960, 330], 900);
await app.locator(".chat-specialist").first().waitFor({ timeout: 60_000 });
await wait(600);
await spotlight(app.locator("[data-coach=chat-team]").last(), "Analyst and Critic, at the same time", "bottom", 8);
await app.getByText("Why this AI").last().waitFor({ timeout: 90_000 });
await unspot();
await stage("unzoom", 700);
await wait(300);
const answer = app.locator(".chat-reply").last();
await zoom(answer, 1.3, [960, 420], 800);
await spotlight(app.getByText("Why this AI").last().locator(".."), "Which AI answered, and why", "right", 6);
await wait(1500);
await unspot();
await stage("unzoom", 700);

// 4 · Build an agent by chatting --------------------------------------
await chapter("agent", "04", "Build agents by chatting", "Say what it should do and when; it runs on a schedule");
await click(app.getByRole("button", { name: "New chat" }).first(), 600);
await box.waitFor();
await click(app.locator("[data-coach=chat-team-toggle]"), 500);
await type(box, "Make me an agent that sends me a plan for the day every weekday at 8am, from my saved notes.", 11);
await click(send(), 500);
const create = app.getByRole("button", { name: /Create agent/ });
await create.waitFor({ timeout: 90_000 });
await wait(500);
const card = create.locator("xpath=ancestor::div[contains(@class,'rounded')][last()]");
await zoom(app.getByText("Run on its own").last(), 1.3, [900, 520], 900);
await spotlight(app.getByText("Run on its own").locator("xpath=ancestor::div[contains(@class,'rounded')][1]"), "Weekdays at 8:00", "right", 6);
await wait(1100);
await unspot();
await stage("unzoom", 600);
void card;
await click(create, 600);
await app.getByText("Morning Plan is saved").waitFor({ timeout: 30_000 });
await wait(400);
await click(rail("AI Agents"), 700);
const agentCard = app.locator("div", { has: app.getByText("Everything it needs is ready") }).filter({ hasText: "Morning Plan" }).last();
await agentCard.waitFor();
await zoom(agentCard, 1.35, [760, 400], 800);
await spotlight(agentCard, "Ready, and on a schedule", "right", 8);
await wait(1400);
await unspot();
await stage("unzoom", 600);

// 5 · Agent Tree ------------------------------------------------------
await chapter("tree", "05", "See how every agent works", "What starts it, its stages, the tools it uses, what you get");
await click(app.getByRole("button", { name: /^Tree/ }).first(), 600);
const morning = app.getByRole("button", { name: /Morning Plan/ }).first();
await morning.waitFor();
await wait(400);
await click(morning, 700);
const how = app.getByRole("heading", { name: "How Morning Plan works" });
await scrollTo(how, 40, 1000);
await wait(1500);
await click(app.getByRole("button", { name: /^Researcher/ }).first(), 700).catch(async () => {
  await scrollTo(app.getByText("Your assistant and its helpers"), 40, 800);
  await click(app.getByRole("button", { name: /^Researcher/ }).first(), 700);
});
const howR = app.getByRole("heading", { name: "How Researcher works" });
await scrollTo(howR, 20, 1100);
await wait(500);
await spotlight(app.getByText("Search Gmail").locator(".."), "Tools, with the real app logos", "left", 8);
await wait(1400);
await unspot();

// 6 · Safety ----------------------------------------------------------
await chapter("safety", "06", "You stay in control", "Reading runs, risky actions ask first or are blocked");
await click(rail("Permissions"), 700);
await app.getByRole("heading", { name: "Permissions" }).waitFor();
await wait(400);
const row = (text) => app.locator("div.border-b", { hasText: text }).filter({ has: app.getByRole("radiogroup") }).first();
await spotlight(row("Post to a Slack channel"), "Can't be undone: blocked", "top", 6);
await wait(1200);
await unspot();
await click(app.getByRole("button", { name: /^Python/ }).first(), 600);
await wait(500);
await spotlight(row("Run a small Python program"), "Python asks first", "top", 6);
await wait(1100);
await unspot();
await click(rail("Chat"), 700);
await click(app.getByText("My phone plan is").first(), 600);
await box.waitFor();
await type(box, "Double-check both plans with a quick Python script.", 11);
await click(send(), 500);
const approve = app.getByRole("button", { name: /^Approve/ });
await approve.waitFor({ timeout: 90_000 });
await wait(300);
const ask = app.locator("[data-coach=chat-approval]").last();
await zoom(ask, 1.35, [960, 520], 800);
await spotlight(ask, "Waits for your yes", "top", 8);
await wait(1200);
await unspot();
await click(approve, 600);
await stage("unzoom", 700);
await app.getByText("Python agrees").waitFor({ timeout: 90_000 });
await wait(400);
await zoom(app.getByText("Python agrees").last(), 1.3, [960, 380], 800);
await wait(1700);
await stage("unzoom", 700);

// Outro ---------------------------------------------------------------
await stage("hideFeature");
await stage("showCursor", false);
mark("outro", "Outro");
await stage("outro");
await wait(5000);

await cdp.send("Page.stopScreencast");
await browser.close();
model?.kill();

// ------------------------------------------------------------ encode

mkdirSync(dirname(OUT), { recursive: true });
const t0 = frames[0].t;
writeFileSync(
  OUT.replace(/\.mp4$/, ".marks.json"),
  JSON.stringify(marks.map((m) => ({ ...m, t: Math.round(((m.t ?? t0) - t0) / SLOW * 100) / 100 })), null, 2),
);

const lines = ["ffconcat version 1.0"];
for (let i = 0; i < frames.length; i++) {
  const next = frames[i + 1]?.t ?? frames[i].t + 1 / 30;
  lines.push(`file '${frames[i].file}'`, `duration ${Math.max(0.001, next - frames[i].t).toFixed(4)}`);
}
lines.push(`file '${frames.at(-1).file}'`);
const list = join(FRAMES, "list.txt");
writeFileSync(list, lines.join("\n"));

await new Promise((done, fail) => {
  const ff = spawn(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list,
      "-vf", `setpts=PTS/${SLOW},fps=30,format=yuv420p`,
      "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-movflags", "+faststart", OUT],
    { stdio: "inherit" },
  );
  ff.on("close", (code) => (code === 0 ? done() : fail(new Error(`ffmpeg exited ${code}`))));
});
rmSync(FRAMES, { recursive: true, force: true });
console.log(`${OUT} · ${frames.length} frames captured`);
if (errors.length) console.error("page errors:\n" + errors.join("\n"));

#!/usr/bin/env node
/**
 * Record the live product demo: the real app, driven like a person
 * would use it, captured to an MP4.
 *
 *   npm run build
 *   DEMO_SLOW=2 node scripts/demo/server.mjs &     # demo backend + built app
 *   node scripts/record-demo.mjs                    # -> ../docs/product-demo.mp4
 *
 * Why half speed: a browser screencast delivers roughly 25 frames a
 * second at 1080p. Everything (CSS animations, the app's timers, the
 * demo server's run events, and this script's pauses) is slowed by
 * DEMO_SLOW, captured, then sped back up, which doubles the frame rate
 * of the finished video without changing anything it shows.
 */

import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const SLOW = Number(process.env.DEMO_SLOW ?? 2);
const BASE = process.env.DEMO_URL ?? "http://localhost:8010";
const OUT = resolve(process.argv[2] ?? "../docs/product-demo.mp4");
const FRAMES = join(tmpdir(), `demo-frames-${process.pid}`);

// A fresh demo backend for every recording, so the story starts clean.
let server = null;
if (!process.env.DEMO_URL) {
  server = spawn(process.execPath, [new URL("./demo/server.mjs", import.meta.url).pathname], {
    env: { ...process.env, DEMO_SLOW: String(SLOW) },
    stdio: ["ignore", "pipe", "inherit"],
  });
  await new Promise((ready) => server.stdout.once("data", ready));
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, colorScheme: "dark" });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

// Stretch every timer in every frame by the same factor as the animations.
await page.addInitScript((slow) => {
  const st = window.setTimeout.bind(window);
  const si = window.setInterval.bind(window);
  window.setTimeout = (fn, ms, ...a) => st(fn, (ms || 0) * slow, ...a);
  window.setInterval = (fn, ms, ...a) => si(fn, (ms || 0) * slow, ...a);
}, SLOW);

const cdp = await page.context().newCDPSession(page);
await cdp.send("Animation.enable");
await cdp.send("Animation.setPlaybackRate", { playbackRate: 1 / SLOW });

// ------------------------------------------------------------------ helpers

const wait = (ms) => page.waitForTimeout(ms * SLOW);
const stage = (fn, ...args) => page.evaluate(([f, a]) => window.stage[f](...a), [fn, args]);

await page.goto(`${BASE}/__demo/stage`);
await page.evaluate(() => document.fonts.ready);
await stage("load", `${BASE}/tasks`);
const app = page.frameLocator("#app");
const frame = () => page.frames().find((f) => f.name() === "app" || f.url().startsWith(BASE) && f !== page.mainFrame());

async function rect(locator) {
  await locator.evaluate((el) => el.scrollIntoView({ block: "nearest", behavior: "instant" }));
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
  });
}

async function point(locator, ms = 900) {
  const r = await rect(locator);
  await stage("moveToApp", r.cx, r.cy, ms);
  await wait(ms + 120);
  return r;
}

async function click(locator, ms = 900) {
  await point(locator, ms);
  await stage("click");
  await locator.click();
  await wait(350);
}

async function type(locator, text, perChar = 38) {
  await click(locator, 800);
  await locator.pressSequentially(text, { delay: perChar * SLOW });
}

async function zoom(locator, scale, at, ms = 1100) {
  const r = await rect(locator);
  await stage("zoom", r.cx, r.cy, scale, at, ms);
  await wait(ms + 100);
}

async function caption(n, text) {
  await stage("caption", n, text);
  await wait(500);
}

async function go(path) {
  await stage("path", path.split("?")[0]);
}

// ------------------------------------------------------------------ capture

mkdirSync(FRAMES, { recursive: true });
const frames = [];
cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
  const file = join(FRAMES, `f${String(frames.length).padStart(6, "0")}.jpg`);
  writeFileSync(file, Buffer.from(data, "base64"));
  frames.push({ file, t: metadata.timestamp });
  await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });

// ------------------------------------------------------------------ the demo
for (const kind of ["unhandledRejection", "uncaughtException"]) process.on(kind, async (err) => {
  console.error(err);
  await page.screenshot({ path: join(tmpdir(), "demo-failure.png") }).catch(() => {});
  server?.kill();
  process.exit(1);
});
// Timed to land just under a minute: ~4s intro, six short chapters,
// ~3.5s outro. Waits are in finished-video time.

// Intro card, while the app loads behind it.
await app.getByRole("link", { name: "Tasks" }).first().waitFor();
await wait(2600);
await stage("zoom", 800, 450, 0.9, [960, 540], 0);
await stage("showWindow");
await wait(100);
await stage("unzoom", 1100);
await stage("showCursor");
await stage("moveTo", 1500, 900, 0);
await wait(900);

// 1 · Connect Google (~7s)
await caption("01", "Connect Google Workspace in one click");
await click(app.getByRole("link", { name: "Connections" }), 700);
await go("/connections");
const google = app.locator("article", { hasText: "Google Workspace" });
await zoom(google, 1.45, [960, 470], 900);
await click(google.getByRole("button", { name: "Connect Google Workspace" }), 700);
await wait(1100);
await point(google.getByText("ops@victopia.com").first(), 600);
await wait(900);
await stage("unzoom", 800);

// 2 · Give Ravi the Gmail tools (~8s)
await caption("02", "Give an AI Employee exactly the tools it needs");
await click(app.getByRole("link", { name: "AI Employees" }), 700);
await go("/employees");
const ravi = app.locator("article", { hasText: "Operations Analyst" });
await click(ravi.getByRole("button", { name: "Tools" }), 700);
const panel = app.locator("aside", { hasText: "Tools for Ravi" });
const googlePack = panel.locator("details", { hasText: "Google Workspace" });
await zoom(googlePack.locator("summary"), 1.45, [1060, 330], 900);
await click(googlePack.locator("summary"), 600);
await wait(250);
await zoom(googlePack, 1.45, [1060, 560], 700);
for (const tool of ["gmail_search", "gmail_send"]) {
  await click(googlePack.locator("label").filter({ has: app.getByText(tool, { exact: true }) }).locator("input"), 450);
}
await click(panel.getByRole("button", { name: /^Save/ }), 600);
await wait(700);
await stage("unzoom", 800);

// 3 · Assign and watch (~12s)
await caption("03", "Assign work and watch every step, live");
await click(app.getByRole("link", { name: "Tasks" }).first(), 700);
await go("/tasks");
const composer = app.getByPlaceholder(/What should it do/);
await zoom(composer, 1.35, [960, 460], 900);
await type(composer, "Why did checkouts fail overnight? Email the ops team a summary.", 26);
await click(app.getByRole("button", { name: /Assign to Ravi/ }), 600);
await stage("unzoom", 700);
await wait(600);
const run = app.locator("section[aria-label='Run']");
await zoom(run, 1.32, [1000, 560], 900);
await stage("moveTo", 1700, 960, 700);
await wait(4300);

// 4 · Agent tree (~5s)
await caption("04", "A manager hands work to specialists");
await click(run.getByRole("button", { name: /Agent tree/ }), 600);
await stage("moveTo", 1750, 980, 600);
await wait(3600);

// 5 · Approve from the inbox (~9s)
await caption("05", "Risky actions wait — approve from email or Slack");
await stage("unzoom", 700);
await stage("mail", true);
await wait(1100);
const box = await stage("mailApproveBox");
await stage("moveTo", box.x + box.width / 2, box.y + box.height / 2, 800);
await wait(850);
await stage("click");
await stage("mailApproved");
await wait(500);
await stage("mail", false);
const approval = await page.evaluate(async (base) => (await (await fetch(`${base}/api/v1/orgs/victopia/approvals`)).json())[0]?.id, BASE);
await frame().goto(`${BASE}/approve/${approval}?action=approve`);
await go("/approve");
const approve = app.getByRole("button", { name: /^Approve/ });
await zoom(approve, 1.3, [960, 640], 900);
await wait(700);
await click(approve, 600);
await wait(1100);
await stage("unzoom", 700);

// 6 · The run finishes (~8s)
await caption("06", "The run resumes and finishes, every step logged");
const taskId = await page.evaluate(async (base) => (await (await fetch(`${base}/api/v1/orgs/victopia/tasks`)).json())[0].id, BASE);
await frame().goto(`${BASE}/tasks?task=${taskId}`);
await go("/tasks");
await zoom(app.locator("section[aria-label='Run']"), 1.3, [1000, 560], 900);
await wait(2600);
await click(app.locator("section[aria-label='Run']").getByRole("button", { name: /Result/ }), 600);
await wait(2300);

// Outro (~3.5s)
await stage("hideCaption");
await stage("showCursor", false);
await stage("outro");
await wait(3600);

await cdp.send("Page.stopScreencast");
await browser.close();
server?.kill();

// ------------------------------------------------------------------ encode

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
      "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", OUT],
    { stdio: "inherit" },
  );
  ff.on("close", (code) => (code === 0 ? done() : fail(new Error(`ffmpeg exited ${code}`))));
});
rmSync(FRAMES, { recursive: true, force: true });

console.log(`${OUT} · ${frames.length} frames captured`);
if (errors.length) console.error("page errors:\n" + errors.join("\n"));

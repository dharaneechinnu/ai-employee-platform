#!/usr/bin/env node
/**
 * Render stage.html to a silent MP4, frame by frame.
 *
 *   node scripts/ad-routing/render.mjs OUT.mp4 [--from 0 --to 48 --fps 30] [--stage other/stage.html]
 *
 * Each frame seeks every animation on the page to its time and takes a
 * screenshot, so the result does not depend on how fast this machine is.
 * Also writes OUT.marks.json (scene start times) for make_ad.py.
 * --stage renders another stage page with the same contract (window.seek,
 * window.SCENES, window.DURATION), e.g. scripts/feature-tour/stage.html.
 */
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const out = args[0];
if (!out) {
  console.error("usage: node render.mjs OUT.mp4 [--from s --to s --fps n]");
  process.exit(2);
}
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i < 0 ? fallback : Number(args[i + 1]);
};
const fps = opt("fps", 30);
const stageAt = args.indexOf("--stage");
const stage = stageAt < 0 ? path.join(here, "stage.html") : path.resolve(args[stageAt + 1]);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(pathToFileURL(stage).href);
await page.evaluate(() => document.fonts.ready);
const { scenes, duration } = await page.evaluate(() => ({ scenes: window.SCENES, duration: window.DURATION }));
const from = opt("from", 0);
const to = opt("to", duration);

const ffmpeg = spawn(
  "ffmpeg",
  ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
   "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
  { stdio: ["pipe", "inherit", "inherit"] },
);

const frames = Math.round((to - from) * fps);
for (let f = 0; f < frames; f++) {
  await page.evaluate((t) => window.seek(t), from + f / fps);
  const jpg = await page.screenshot({ type: "jpeg", quality: 92 });
  if (!ffmpeg.stdin.write(jpg)) await new Promise((r) => ffmpeg.stdin.once("drain", r));
  if (f % (fps * 5) === 0) process.stdout.write(`${(from + f / fps).toFixed(0)}s `);
}
ffmpeg.stdin.end();
await new Promise((r, j) => ffmpeg.on("close", (c) => (c === 0 ? r() : j(new Error(`ffmpeg exited ${c}`)))));
await browser.close();

writeFileSync(out.replace(/\.mp4$/, ".marks.json"), JSON.stringify(scenes.map((s) => ({ id: s.id, t: s.t - from }))));
console.log(`\n${out}: ${frames} frames`);

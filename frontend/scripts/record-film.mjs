#!/usr/bin/env node
/**
 * Render the product film to an MP4, frame by frame.
 *
 * The film runs in a real browser at /film?record=1, which exposes
 * window.__film.seek(ms). For every frame we seek, screenshot, and hand
 * the image to ffmpeg, so the video is exact: no dropped frames, no
 * timing jitter, whatever the speed of the machine.
 *
 *   npm run build && npx vite preview --port 4173 &
 *   node scripts/record-film.mjs                     # -> product-film.mp4
 *   node scripts/record-film.mjs --check 3500,12000  # a few stills only
 *
 * Needs Playwright (with Chromium) and ffmpeg on the machine. Neither
 * is a project dependency: nobody needs them to build or run the app.
 */

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};

const url = option("url", "http://localhost:4173/film?record=1");
const out = resolve(option("out", "product-film.mp4"));
const fps = Number(option("fps", "30"));
const width = Number(option("width", "1920"));
const height = Math.round((width * 9) / 16);
const check = option("check", null);

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// The film needs no API; answer quietly so the app does not wait on one.
await page.route("**/api/v1/**", (route) => route.fulfill({ status: 401, json: {} }));
await page.goto(url);
await page.waitForFunction(() => window.__film?.ready);
// Fonts load lazily, on first use; ask for every face the film uses
// up front, so no frame is captured with a fallback font.
await page.evaluate(async () => {
  const faces = ['400 16px "DM Sans"', '500 16px "DM Sans"', '600 16px "DM Sans"', '400 16px "Geist Mono"', '600 16px "Outfit"', '700 16px "Outfit"', '300 16px "Geist Mono"'];
  await Promise.all(faces.map((f) => document.fonts.load(f)));
  await document.fonts.ready;
});

const total = await page.evaluate(() => window.__film.total);

if (check) {
  const dir = resolve(option("dir", "film-check"));
  mkdirSync(dir, { recursive: true });
  for (const t of check.split(",").map(Number)) {
    await page.evaluate((ms) => window.__film.seek(ms), t);
    await page.screenshot({ path: `${dir}/t${String(t).padStart(5, "0")}.png` });
  }
  console.log(`stills written to ${dir}`);
} else {
  const ffmpeg = spawn(
    "ffmpeg",
    [
      "-y",
      "-loglevel", "error",
      "-f", "image2pipe",
      "-framerate", String(fps),
      "-c:v", "mjpeg",
      "-i", "-",
      "-c:v", "libx264",
      "-preset", "slow",
      "-crf", "17",
      "-pix_fmt", "yuv420p",
      "-movflags", "+faststart",
      out,
    ],
    { stdio: ["pipe", "inherit", "inherit"] },
  );
  const frames = Math.ceil((total / 1000) * fps);
  const started = Date.now();
  for (let i = 0; i < frames; i++) {
    await page.evaluate((ms) => window.__film.seek(ms), (i * 1000) / fps);
    const jpeg = await page.screenshot({ type: "jpeg", quality: 95 });
    if (!ffmpeg.stdin.write(jpeg)) await new Promise((r) => ffmpeg.stdin.once("drain", r));
    if (i % fps === 0) process.stdout.write(`\r${Math.round((i / frames) * 100)}%  frame ${i}/${frames}`);
  }
  ffmpeg.stdin.end();
  await new Promise((r) => ffmpeg.on("close", r));
  console.log(`\n${out} · ${frames} frames · ${Math.round((Date.now() - started) / 1000)}s`);
}

await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

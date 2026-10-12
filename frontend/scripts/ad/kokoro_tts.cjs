#!/usr/bin/env node
/**
 * Offline voiceover: speak each line with the Kokoro neural voice model,
 * run locally through sherpa-onnx. No account or API key needed.
 *
 *   node kokoro_tts.cjs jobs.json
 *
 * jobs.json: { "items": [{ "text": "...", "voice": "af_bella", "speed": 1.0, "out": "/tmp/a.wav" }] }
 * Prints one JSON line per item: { "out": ..., "seconds": ... }.
 *
 * Install the engine and model once (kept out of git, ~200 MB):
 *   npm install --no-save --no-package-lock --prefix scripts/ad/.voice n8n-nodes-ttsbro@0.1.6 sherpa-onnx-node
 * That package ships the official sherpa-onnx build of Kokoro-82M
 * (kokoro-int8-en-v0_19, Apache-2.0).
 */

const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, ".voice", "node_modules");
const model = path.join(root, "n8n-nodes-ttsbro", "kokoro-int8-en-v0_19");
if (!fs.existsSync(model)) {
  console.error("Voice model not installed. See the install line at the top of scripts/ad/kokoro_tts.cjs.");
  process.exit(2);
}
const sherpa = require(path.join(root, "sherpa-onnx-node"));

// Speaker ids of kokoro-int8-en-v0_19, in the order of its voices.bin.
const VOICES = ["af", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george", "bm_lewis"];

const tts = new sherpa.OfflineTts({
  model: {
    kokoro: {
      model: path.join(model, "model.int8.onnx"),
      voices: path.join(model, "voices.bin"),
      tokens: path.join(model, "tokens.txt"),
      dataDir: path.join(model, "espeak-ng-data"),
      lengthScale: 1.0,
    },
    numThreads: 4,
    provider: "cpu",
    debug: false,
  },
  maxNumSentences: 1,
});

const jobs = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
for (const item of jobs.items) {
  const sid = VOICES.indexOf(item.voice ?? "af_bella");
  if (sid < 0) throw new Error(`Unknown voice ${item.voice}. Choose one of: ${VOICES.join(", ")}`);
  const audio = tts.generate({ text: item.text, sid, speed: item.speed ?? 1.0 });
  sherpa.writeWave(item.out, { samples: audio.samples, sampleRate: audio.sampleRate });
  console.log(JSON.stringify({ out: item.out, seconds: audio.samples.length / audio.sampleRate }));
}

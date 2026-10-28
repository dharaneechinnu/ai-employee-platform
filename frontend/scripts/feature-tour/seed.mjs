#!/usr/bin/env node
/**
 * Fill the demo account the feature tour is filmed on. Run once, before
 * capture.mjs, against the local stack (API on :8000, worker, Postgres).
 *
 *   node scripts/feature-tour/seed.mjs
 *
 * The account is "priya" (password Marigold-tea-2026), the person the
 * live demo (scripts/app-demo/record-app-demo.mjs) signs up: run that
 * first on a fresh database, so the account already has her own model
 * server, the team chat, the "Morning Plan" agent and its draft card.
 * Safe to run again: each step checks whether it is already done.
 *
 * What is real and what is not:
 *
 * - Through the real API: AI keys (placeholder keys, so they read
 *   "untested"), the Slack and Teams channel connections (placeholder
 *   webhook addresses), Slack approvals on the Notifications page,
 *   memories, two more agents and her display name.
 * - Through the real worker: one new chat, "Double-check both plans with a
 *   quick Python script", answered by the scripted stand-in model
 *   (scripts/app-demo/model-server.mjs, started here if it is not
 *   running). Python asks first, so it is left waiting in Approvals.
 * - Written straight into the database (SEEDED, not real runs): a week of
 *   past chats and Morning Plan runs, with their model calls on Gemini,
 *   Groq and Claude, so History and Models and cost have something to
 *   show. Their prices come from the app's own price table.
 *
 * Env: API (http://localhost:8000/api/v1), FT_DB (postgres URL for psql),
 * STANDIN_URL (http://localhost:8787/v1).
 */

import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";

const API = process.env.API ?? "http://localhost:8000/api/v1";
const DB = process.env.FT_DB ?? "postgresql://app:app@localhost:5432/ai_employee";
const STANDIN = process.env.STANDIN_URL ?? "http://localhost:8787/v1";
const USER = "priya";
const PASSWORD = "Marigold-tea-2026";

async function api(method, path, body, token) {
  const res = await fetch(API + path, {
    method,
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${path}: ${res.status} ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

function sql(query) {
  const out = spawnSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-Atq", "-c", query], { encoding: "utf8" });
  if (out.status !== 0) throw new Error(out.stderr);
  return out.stdout.trim();
}
const q = (s) => `'${String(s).replace(/'/g, "''")}'`;

const { access_token: token } = await api("POST", "/auth/login", { identifier: USER, password: PASSWORD });
const me = sql(`SELECT id FROM users WHERE lower(username) = ${q(USER)}`);
console.log(`signed in as ${USER} (${me})`);

// ---------------------------------------------------------------- name, age

sql(`UPDATE users SET full_name = 'Priya Sharma', created_at = LEAST(created_at, now() - interval '9 days') WHERE id = ${q(me)}`);

// ---------------------------------------------------------------- AI keys

const providers = await api("GET", "/me/providers", null, token);
const have = new Set(providers.map((p) => p.provider_key));
for (const [key, plan] of [["gemini", "free"], ["groq", "free"], ["openrouter", "free"], ["anthropic", "paid"]]) {
  if (have.has(key)) continue;
  await api("POST", "/me/providers", { provider_key: key, api_key: `demo-${key}-${randomUUID().slice(0, 12)}` }, token);
  await api("PUT", `/me/providers/${key}/plan`, { plan }, token);
  console.log(`key added: ${key} (${plan}, placeholder)`);
}

// ---------------------------------------------------------------- channels

const connections = await api("GET", "/me/connections", null, token);
const kinds = new Set(connections.map((c) => c.kind));
if (!kinds.has("slack")) {
  await api("POST", "/me/connections", {
    kind: "slack", label: "Study group", config: { channel: "#study-group" },
    secret: `https://hooks.slack.com/services/T0DEMO/B0DEMO/${randomUUID().replace(/-/g, "").slice(0, 24)}`,
  }, token);
  console.log("Slack channel connected (placeholder webhook)");
}
if (!kinds.has("teams")) {
  await api("POST", "/me/connections", {
    kind: "teams", label: "Project team", config: { channel: "Final-year project" },
    secret: `https://demo.webhook.office.com/webhookb2/${randomUUID()}`,
  }, token);
  console.log("Teams channel connected (placeholder webhook)");
}
const notes = await api("GET", "/me/notifications", null, token);
if (!notes.slack_connected) {
  await api("PUT", "/me/notifications", {
    email_enabled: true, slack_enabled: true, on_approval_requested: true,
    slack_webhook_url: `https://hooks.slack.com/services/T0DEMO/B0NOTE/${randomUUID().replace(/-/g, "").slice(0, 24)}`,
  }, token);
  console.log("Slack approvals switched on");
}

// ---------------------------------------------------------------- memory

const remembered = new Set((await api("GET", "/me/memory", null, token)).map((m) => m.content));
for (const content of [
  "I'm in my final year of B.Tech at Anna University, Chennai.",
  "My DBMS assignment is due this Thursday.",
  "I prefer short answers with bullet points.",
  "Our project team meets on Mondays at 10:00 IST.",
  "Expenses go in the 'Expenses 2026' Google Sheet.",
]) {
  if (!remembered.has(content)) await api("POST", "/me/memory", { content, kind: "fact" }, token);
}
// Told over the past week and a half, not all in the last minute.
sql(`WITH m AS (SELECT id, row_number() OVER (ORDER BY created_at) AS rn FROM memories WHERE owner_id = ${q(me)})
     UPDATE memories SET created_at = now() - interval '2 days' * (6 - m.rn) - interval '3 hours', updated_at = now() - interval '2 days' * (6 - m.rn) - interval '3 hours'
     FROM m WHERE memories.id = m.id AND memories.created_at > now() - interval '1 hour'`);
console.log("memories in place");

// ---------------------------------------------------------------- agents

const agents = (await api("GET", "/me/agents/overview", null, token)).agents;
const named = (n) => agents.find((a) => a.name === n);
if (!named("Morning inbox digest")) {
  await api("POST", "/me/agents", {
    name: "Morning inbox digest",
    description: "Summarises new mail every weekday morning",
    instructions: "Every weekday, read my unread email, summarise the important threads, and draft replies for anything urgent.",
    tools: ["current_time", "recall", "gmail_search", "gmail_read", "gmail_create_draft", "report_write"],
    schedule: { frequency: "weekdays", time: "07:30", timezone: "Asia/Kolkata" },
  }, token);
  console.log("agent: Morning inbox digest");
}
if (!named("Chennai meetup scout")) {
  await api("POST", "/me/agents", {
    name: "Chennai meetup scout",
    description: "Finds free developer meetups and keeps a sheet up to date",
    instructions: "Find free developer meetups and hackathons in Chennai this month and add them to my Google Sheet.",
    tools: ["current_time", "recall", "web_search", "get_webpage", "sheets_read", "sheets_append_rows"],
  }, token);
  console.log("agent: Chennai meetup scout");
}
const plan = (await api("GET", "/me/agents/overview", null, token)).agents.find((a) => a.name === "Morning Plan");

// ---------------------------------------------------------------- a real run that waits

const waiting = await api("GET", "/me/approvals", null, token);
if (!waiting.length) {
  const up = await fetch(`${STANDIN}/models`).then((r) => r.ok).catch(() => false);
  let model = null;
  if (!up) {
    model = spawn(process.execPath, [new URL("../app-demo/model-server.mjs", import.meta.url).pathname], { stdio: "ignore" });
    await new Promise((r) => setTimeout(r, 1500));
  }
  const chat = await api("POST", "/me/conversations", { mode: "general", routing: "private" }, token);
  await api("POST", `/me/conversations/${chat.id}/messages`, { content: "Double-check both plans with a quick Python script." }, token);
  for (let i = 0; i < 60; i++) {
    if ((await api("GET", "/me/approvals", null, token)).length) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  model?.kill();
  console.log("real run: a Python check is waiting in Approvals");
}

// ---------------------------------------------------------------- a week of history (SEEDED)

const seeded = sql(`SELECT count(*) FROM llm_calls WHERE owner_id = ${q(me)} AND provider_key <> 'custom'`);
if (seeded === "0") {
  const PRICE = {
    "gemini-2.0-flash": [0.1, 0.4], "openai/gpt-oss-20b": [0.075, 0.3], "openai/gpt-oss-120b": [0.15, 0.6],
    "claude-sonnet-5-5": [2, 10],
  };
  const PROVIDER = { "gemini-2.0-flash": "gemini", "openai/gpt-oss-20b": "groq", "openai/gpt-oss-120b": "groq", "claude-sonnet-5-5": "anthropic" };
  // [hours ago, mode, prompt, answer, model, prompt tokens, output tokens, seconds]
  const chats = [
    [150, "study", "Explain database normalisation with a small example", "**Normalisation** splits one big table into smaller ones so each fact is stored once…", "gemini-2.0-flash", 2100, 820, 7],
    [131, "work", "Draft a polite email asking Prof. Rao for a two-day extension", "Subject: Request for a short extension on the DBMS assignment…", "openai/gpt-oss-20b", 1400, 380, 4],
    [118, "code", "Why does my React useEffect run twice in development?", "In development, React 18 Strict Mode mounts each component twice on purpose…", "claude-sonnet-5-5", 5200, 1100, 12],
    [97, "general", "Plan a three-day trip to Jaipur on a student budget", "**Day 1:** Amber Fort early, then Panna Meena ka Kund… Total: about ₹6,500.", "openai/gpt-oss-120b", 1800, 900, 8],
    [76, "research", "What do recent papers say about retrieval-augmented generation?", "**Summary:** retrieval helps most on fresh or niche facts; three open questions…", "gemini-2.0-flash", 8800, 1500, 15],
    [55, "study", "Make a two-week timetable for my semester exams", "| Day | Morning | Evening |\n|---|---|---|\n| Mon | DBMS | OS revision |…", "gemini-2.0-flash", 2600, 1200, 9],
    [49, "code", "Find the bug in this Python function that merges two sorted lists", "The loop stops when either list runs out, so the rest of the other list is dropped…", "claude-sonnet-5-5", 4100, 700, 10],
    [30, "general", "Explain what a mutual fund SIP is in simple words", "A **SIP** puts a fixed amount into a mutual fund every month…", "openai/gpt-oss-20b", 1100, 420, 3],
    [22, "work", "Rewrite my resume summary for a data analyst internship", "Final-year B.Tech student who turns messy data into clear decisions…", "gemini-2.0-flash", 1900, 360, 5],
    [6, "study", "Convert 72 km/h to m/s and show the steps", "72 km/h × 1000 ÷ 3600 = **20 m/s**", "openai/gpt-oss-20b", 900, 160, 2],
  ];
  const runs = [];
  for (const [h, mode, prompt, answer, model, pin, pout, secs] of chats) {
    const conv = randomUUID();
    const at = `now() - interval '${h} hours'`;
    sql(`INSERT INTO conversations (id, owner_id, title, mode, created_at, updated_at) VALUES (${q(conv)}, ${q(me)}, ${q(prompt.slice(0, 60))}, ${q(mode)}, ${at}, ${at})`);
    runs.push({ conv, at, prompt, answer, model, pin, pout, secs, trigger: "chat", agent: null });
  }
  if (plan) {
    const conv = plan.run_conversation_id ?? randomUUID();
    if (!plan.run_conversation_id) {
      sql(`INSERT INTO conversations (id, owner_id, title, agent_id) VALUES (${q(conv)}, ${q(me)}, 'Morning Plan', ${q(plan.id)})`);
      sql(`UPDATE agents SET run_conversation_id = ${q(conv)} WHERE id = ${q(plan.id)}`);
    }
    // The last five weekday mornings at 8:00 IST (02:30 UTC).
    const days = [];
    for (let d = 1; days.length < 5 && d < 10; d++) {
      const day = new Date(Date.now() - d * 86400000);
      if (day.getUTCDay() !== 0 && day.getUTCDay() !== 6) days.push(day.toISOString().slice(0, 10));
    }
    const plans = [
      "1. Finish the DBMS assignment draft (due Thursday)\n2. Reply to Prof. Rao\n3. Project sync at 10:00",
      "1. DBMS assignment: write the normalisation section\n2. Book the lab slot\n3. Pay the hostel fee",
      "1. Revise operating systems, units 3 and 4\n2. Send the project slides to the team\n3. Gym at 6",
      "1. Project team meets at 10:00\n2. Mock interview prep: SQL joins\n3. Call home",
      "1. Submit the DBMS assignment\n2. Read the internship offer letter\n3. Plan the weekend trip",
    ];
    days.forEach((day, i) => runs.push({
      conv, at: `${q(day + " 02:30:00+00")}::timestamptz`, prompt: "Morning Plan · scheduled run", answer: plans[i],
      model: "gemini-2.0-flash", pin: 3200, pout: 260, secs: 6, trigger: "schedule", agent: plan.id,
    }));
  }
  for (const r of runs) {
    const task = randomUUID();
    const run = randomUUID();
    const [pi, po] = PRICE[r.model];
    const cost = PROVIDER[r.model] === "anthropic" ? ((r.pin * pi + r.pout * po) / 1e6).toFixed(6) : "0";
    sql(`INSERT INTO tasks (id, title, input, status, dry_run, created_by, cancel_requested, owner_id, conversation_id, agent_id, trigger, created_at, updated_at)
         VALUES (${q(task)}, ${q(r.prompt.slice(0, 200))}, ${q(r.prompt)}, 'completed', false, ${q(me)}, false, ${q(me)}, ${q(r.conv)}, ${r.agent ? q(r.agent) : "NULL"}, ${q(r.trigger)}, ${r.at}, ${r.at})`);
    sql(`INSERT INTO runs (id, task_id, attempt, status, step_count, prompt_tokens, output_tokens, cost_usd, output, started_at, ended_at, owner_id, created_at, updated_at, trigger, agent_id)
         VALUES (${q(run)}, ${q(task)}, 1, 'completed', 2, ${r.pin}, ${r.pout}, ${cost}, ${q(r.answer)}, ${r.at}, ${r.at} + interval '${r.secs} seconds', ${q(me)}, ${r.at}, ${r.at}, ${q(r.trigger)}, ${r.agent ? q(r.agent) : "NULL"})`);
    sql(`INSERT INTO llm_calls (run_id, provider_key, model, prompt_tokens, output_tokens, cost_usd, latency_ms, created_at, owner_id)
         VALUES (${q(run)}, ${q(PROVIDER[r.model])}, ${q(r.model)}, ${r.pin}, ${r.pout}, ${cost}, ${r.secs * 800}, ${r.at}, ${q(me)})`);
    sql(`INSERT INTO conversation_messages (id, owner_id, conversation_id, role, content, task_id, created_at, updated_at)
         VALUES (${q(randomUUID())}, ${q(me)}, ${q(r.conv)}, 'user', ${q(r.prompt)}, ${q(task)}, ${r.at}, ${r.at})`);
    sql(`INSERT INTO conversation_messages (id, owner_id, conversation_id, role, content, task_id, model, created_at, updated_at)
         VALUES (${q(randomUUID())}, ${q(me)}, ${q(r.conv)}, 'assistant', ${q(r.answer)}, ${q(task)}, ${q(r.model)}, ${r.at} + interval '${r.secs} seconds', ${r.at} + interval '${r.secs} seconds')`);
  }
  if (plan) {
    sql(`UPDATE agents SET last_run_at = now() - interval '1 day', last_status = 'completed' WHERE id = ${q(plan.id)}`);
    sql(`UPDATE conversations SET updated_at = now() - interval '1 day' WHERE agent_id = ${q(plan.id)}`);
  }
  console.log(`seeded ${runs.length} past runs (database rows, not real runs)`);
}
console.log("done");

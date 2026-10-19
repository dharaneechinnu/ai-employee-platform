#!/usr/bin/env node
/**
 * A self-contained demo backend for recording the live product demo.
 *
 * It serves the real built frontend (dist/) and answers its API calls
 * from memory, with one difference from a static mock: runs are live.
 * Assigning a task starts a scripted run whose events stream over SSE
 * at a human pace, pause for approval, and resume when someone approves,
 * exactly as the real worker would.
 *
 *   npm run build && node scripts/demo/server.mjs   # http://localhost:8010
 *
 * DEMO_SLOW=2 stretches every delay, for the half-speed recording that
 * the demo recorder speeds back up (see record-demo.mjs).
 */

import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const DIST = resolve(here, "../../dist");
const PORT = Number(process.env.DEMO_PORT ?? 8010);
const SLOW = Number(process.env.DEMO_SLOW ?? 1);
const TOOLS = JSON.parse(readFileSync(join(here, "tools.json"), "utf8"));
const STAGE = join(here, "stage.html");

const ORG = "victopia";
const now = () => new Date().toISOString();
const ago = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();
const later = (fn, ms) => setTimeout(fn, ms * SLOW);

// ------------------------------------------------------------------ state

const me = {
  id: "u-priya",
  email: "priya@victopia.com",
  full_name: "Priya Raman",
  organizations: [{ id: ORG, name: "Victopia Labs", slug: "victopia", role: "admin" }],
};

const guided = (does, never) => ({ what_it_does: does, what_it_must_never_do: never, when_to_ask_a_human: "Before sending anything outside the company." });

const employees = [
  {
    id: "e-ravi",
    name: "Ravi",
    job_title: "Operations Analyst",
    department: "Operations",
    avatar: null,
    status: "active",
    config: { guided: guided("Investigate incidents, find the cause, and brief the ops team.", "Never email customers directly."), model: "gemini:gemini-2.0-flash", temperature: 0.2, max_steps: 20, enabled_tools: ["recall", "remember", "run_query", "get_webpage", "delegate_to_specialist"] },
  },
  {
    id: "e-kiran",
    name: "Kiran",
    job_title: "Data Specialist",
    department: "Operations",
    avatar: null,
    status: "active",
    config: { guided: guided("Answer questions with SQL against the analytics database.", "Never change data."), model: "gemini:gemini-2.0-flash", temperature: 0.1, max_steps: 12, enabled_tools: ["run_query", "describe_table", "list_tables"] },
  },
  {
    id: "e-meera",
    name: "Meera",
    job_title: "Comms Specialist",
    department: "Support",
    avatar: null,
    status: "active",
    config: { guided: guided("Write clear, calm updates for customers and staff.", "Never send without approval."), model: "gemini:gemini-2.0-flash", temperature: 0.4, max_steps: 10, enabled_tools: ["recall", "gmail_create_draft"] },
  },
  {
    id: "e-arjun",
    name: "Arjun",
    job_title: "Research Assistant",
    department: null,
    avatar: null,
    status: "draft",
    config: { guided: guided("Research vendors and summarise what they offer.", "Never sign up for anything."), model: "gemini:gemini-2.0-flash", temperature: 0.3, max_steps: 15, enabled_tools: ["get_webpage"] },
  },
];

const tasks = [
  { id: "t-refunds", title: "Count refunds issued in September", status: "completed", employee_id: "e-kiran", created_at: ago(180), input: "How many refunds did we issue in September, and for how much?", dry_run: false },
  { id: "t-digest", title: "Draft the weekly ops digest", status: "completed", employee_id: "e-meera", created_at: ago(1440), input: "Draft this week's ops digest from the incident notes.", dry_run: false },
  { id: "t-vendors", title: "Compare two payment vendors", status: "failed", employee_id: "e-arjun", created_at: ago(2900), input: "Compare Stripe and Adyen fees for our volume.", dry_run: false },
];

const runs = {
  "r-refunds": { id: "r-refunds", status: "completed", step_count: 6, prompt_tokens: 4200, output_tokens: 610, estimated_cost_usd: "0.0009", output: "412 refunds in September, totalling ₹18,40,250. 61% were for late deliveries.", stop_cause: "completed", error_message: null, started_at: ago(180), ended_at: ago(178), events: [] },
  "r-digest": { id: "r-digest", status: "completed", step_count: 5, prompt_tokens: 3900, output_tokens: 820, estimated_cost_usd: "0.0010", output: "Draft saved to Gmail: “Ops digest · week 41”.", stop_cause: "completed", error_message: null, started_at: ago(1440), ended_at: ago(1437), events: [] },
  "r-vendors": { id: "r-vendors", status: "failed", step_count: 3, prompt_tokens: 1200, output_tokens: 90, estimated_cost_usd: "0.0002", output: null, stop_cause: "tool_error", error_message: "The vendor pricing page could not be reached.", started_at: ago(2900), ended_at: ago(2899), events: [] },
};
const runOf = { "t-refunds": "r-refunds", "t-digest": "r-digest", "t-vendors": "r-vendors" };

const connections = [
  { id: "c-db", kind: "database", display_name: "PostgreSQL", label: "analytics", account: "readonly", status: "connected", credential_last4: "ab12", last_tested_at: ago(40), last_error: null, enabled: true, created_at: ago(9000), config: { host: "db.victopia.com", database: "analytics", username: "readonly" } },
];

const available = [
  { kind: "google", display_name: "Google Workspace", description: "Gmail, Google Calendar and Google Drive, with one sign-in.", auth: "oauth", apps: ["Gmail", "Calendar", "Drive"], configured: true, fields: [], secret_label: null },
  { kind: "microsoft", display_name: "Microsoft 365", description: "Outlook mail, Outlook calendar and OneDrive, with one sign-in.", auth: "oauth", apps: ["Outlook", "Calendar", "OneDrive"], configured: true, fields: [], secret_label: null },
  { kind: "email", display_name: "Any mailbox (IMAP)", description: "Any provider that offers IMAP and SMTP with an app password.", auth: "manual", apps: ["Email"], configured: true, fields: [{ key: "username", label: "Email address", placeholder: "ops@company.com" }, { key: "imap_host", label: "IMAP server", placeholder: "imap.gmail.com" }], secret_label: "App password" },
  { kind: "database", display_name: "PostgreSQL", description: "Read-only questions against your own database.", auth: "manual", apps: ["Database"], configured: true, fields: [], secret_label: "Password" },
].map((a) => ({ ...a, tools: TOOLS.filter((t) => t.requires_connection === a.kind).map((t) => t.name) }));

let notifications = { email_enabled: true, email_available: true, slack_enabled: true, slack_connected: true, slack_webhook_last4: "Qx7a", on_approval_requested: true, on_task_completed: true, on_task_failed: true };

const approvals = [];
const memory = [
  { id: "m1", content: "ERR_4021 at checkout means the payment vendor timed out. Retry once, then hand the order to a human.", kind: "fact", scope: "org", employee_id: null, embedding_model: "text-embedding-004", created_at: ago(5000) },
  { id: "m2", content: "The ops team wants incident summaries before 9am, as three short bullet points.", kind: "preference", scope: "org", employee_id: null, embedding_model: "text-embedding-004", created_at: ago(3000) },
  { id: "m3", content: "Vendor maintenance runs 01:00–03:00 UTC on the first Tuesday of each month.", kind: "fact", scope: "employee", employee_id: "e-ravi", embedding_model: "text-embedding-004", created_at: ago(800) },
];

// ------------------------------------------------------------------ live runs

const listeners = new Map(); // run id -> Set(response)

function emit(run, type, payload = {}) {
  const event = { seq: run.events.length + 1, type, at: now(), ...payload };
  run.events.push(event);
  for (const res of listeners.get(run.id) ?? []) {
    res.write(`id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`);
    if (type === "run_finished" || type === "run_stopped") res.write("event: done\ndata: {}\n\n");
  }
}

/** The incident investigation, as the real agent loop would log it. */
function investigation(run) {
  const model = "gemini-2.0-flash";
  return [
    [600, () => emit(run, "run_started", { model })],
    [700, () => emit(run, "thinking", { step: 1 })],
    [1300, () => emit(run, "llm_call", { model, prompt_tokens: 1840, output_tokens: 212, latency_ms: 910 })],
    [500, () => emit(run, "tool_call", { tool: "recall", arguments: { query: "checkout failures ERR_4021" } })],
    [900, () => emit(run, "tool_result", { tool: "recall", ok: true, error_class: null })],
    [600, () => emit(run, "thinking", { step: 2 })],
    [1100, () => emit(run, "llm_call", { model, prompt_tokens: 2610, output_tokens: 298, latency_ms: 1040 })],
    [400, () => emit(run, "parallel_started", { count: 2 })],
    [300, () => emit(run, "tool_call", { tool: "delegate_to_specialist", arguments: { specialist_name: "Kiran", task: "Count failed checkouts since midnight, grouped by hour and error code." } })],
    [350, () => emit(run, "tool_call", { tool: "get_webpage", arguments: { url: "https://status.payvendor.com/history" } })],
    [1500, () => emit(run, "tool_result", { tool: "get_webpage", ok: true, error_class: null })],
    [1700, () => emit(run, "tool_result", { tool: "delegate_to_specialist", ok: true, error_class: null })],
    [600, () => emit(run, "thinking", { step: 3 })],
    [1200, () => emit(run, "llm_call", { model, prompt_tokens: 3920, output_tokens: 410, latency_ms: 1210 })],
    [400, () => emit(run, "tool_call", { tool: "delegate_to_specialist", arguments: { specialist_name: "Meera", task: "Write a three-bullet summary of the incident for the ops team." } })],
    [2000, () => emit(run, "tool_result", { tool: "delegate_to_specialist", ok: true, error_class: null })],
    [600, () => emit(run, "thinking", { step: 4 })],
    [900, () => emit(run, "llm_call", { model, prompt_tokens: 4630, output_tokens: 260, latency_ms: 880 })],
    [400, () => askApproval(run)],
  ];
}

function finish(run) {
  const model = "gemini-2.0-flash";
  return [
    [500, () => emit(run, "approval_granted", { tool: "gmail_send" })],
    [400, () => emit(run, "tool_call", { tool: "gmail_send", arguments: run.pendingEmail })],
    [1100, () => emit(run, "tool_result", { tool: "gmail_send", ok: true, error_class: null })],
    [600, () => emit(run, "thinking", { step: 5 })],
    [900, () => emit(run, "llm_call", { model, prompt_tokens: 5120, output_tokens: 180, latency_ms: 760 })],
    [
      500,
      () => {
        Object.assign(run, {
          status: "completed",
          stop_cause: "completed",
          step_count: 6,
          prompt_tokens: 18120,
          output_tokens: 1360,
          estimated_cost_usd: "0.0034",
          ended_at: now(),
          output:
            "1,284 checkouts failed between 01:10 and 02:40 UTC, all with ERR_4021: the payment vendor timed out during its maintenance window. Retries are now on, and the ops team has the summary in their inbox.",
        });
        run.task.status = "completed";
        emit(run, "run_finished", { cause: "completed" });
      },
    ],
  ];
}

/** `pace` below 1 tightens a script, to fit the under-a-minute demo. */
function play(steps, pace = 1) {
  let at = 0;
  for (const [delay, step] of steps) {
    at += delay * pace;
    later(step, at);
  }
}

function askApproval(run) {
  run.pendingEmail = {
    to: ["ops-team@victopia.com"],
    subject: "Checkout incident · overnight summary",
    body:
      "• 1,284 checkouts failed between 01:10 and 02:40 UTC (ERR_4021).\n• Cause: the payment vendor timed out during its maintenance window.\n• Retries are now on; no customer action is needed.",
  };
  const approval = {
    id: `a-${run.id}`,
    run_id: run.id,
    tool_name: "gmail_send",
    side_effect: "destructive",
    proposed: run.pendingEmail,
    status: "pending",
    expires_at: new Date(Date.now() + 24 * 3600e3).toISOString(),
    created_at: now(),
    task_title: run.task.title,
    run,
  };
  approvals.push(approval);
  run.status = "awaiting_approval";
  run.task.status = "awaiting_approval";
  emit(run, "approval_requested", { tool: "gmail_send", reason: "destructive actions ask first" });
}

function decide(approval, approve) {
  if (approval.status !== "pending") return false;
  approval.status = approve ? "approved" : "rejected";
  const run = approval.run;
  if (approve) {
    run.status = "running";
    run.task.status = "running";
    play(finish(run), 0.6);
  } else {
    Object.assign(run, { status: "failed", stop_cause: "approval_denied", error_message: "A reviewer rejected the proposed action.", ended_at: now() });
    run.task.status = "failed";
    emit(run, "run_stopped", { cause: "approval_denied" });
  }
  return true;
}

function createTask(body) {
  const id = `t-${Date.now().toString(36)}`;
  const runId = `r-${id.slice(2)}`;
  const title = body.input.length > 64 ? `${body.input.slice(0, 61)}…` : body.input;
  const task = { id, title: body.input.split(/[.?!]/)[0].slice(0, 70) || title, status: "running", employee_id: body.employee_id, created_at: now(), input: body.input, dry_run: !!body.dry_run };
  const run = { id: runId, status: "running", step_count: 0, prompt_tokens: 0, output_tokens: 0, estimated_cost_usd: "0.0000", output: null, stop_cause: null, error_message: null, started_at: now(), ended_at: null, events: [], task };
  tasks.unshift(task);
  runs[runId] = run;
  runOf[id] = runId;
  play(investigation(run), 0.55);
  return task;
}

// ------------------------------------------------------------------ API

function taskView(task) {
  const run = runs[runOf[task.id]];
  const { events, task: _t, pendingEmail: _p, ...publicRun } = run ?? {};
  // Progress counters grow as events arrive, so the stats move live.
  if (run && run.status !== "completed") {
    const calls = run.events.filter((e) => e.type === "llm_call");
    publicRun.step_count = calls.length;
    publicRun.prompt_tokens = calls.reduce((s, e) => s + e.prompt_tokens, 0);
    publicRun.output_tokens = calls.reduce((s, e) => s + e.output_tokens, 0);
    publicRun.estimated_cost_usd = ((publicRun.prompt_tokens * 0.1 + publicRun.output_tokens * 0.4) / 1e6).toFixed(4);
  }
  return { ...task, run: run ? publicRun : null };
}

const listItem = ({ input: _i, dry_run: _d, ...rest }) => rest;
const employeeItem = ({ config: _c, ...rest }) => rest;

function api(method, path, body, req, res) {
  const json = (data, status = 200) => {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(data));
  };
  const m = (re) => path.match(re);
  let p;

  if (path === "/auth/refresh") return json({ access_token: "demo-token" });
  if (path === "/auth/me") return json(me);
  if (path === "/auth/logout") return json({});

  if ((p = m(/^\/approval-links\/([^/]+)(\/decide)?$/))) {
    const approval = approvals.find((a) => a.id === decodeURIComponent(p[1])) ?? approvals.at(-1);
    if (!approval) return json({ detail: "This link is not valid." }, 404);
    if (p[2] && method === "POST") decide(approval, body.approve);
    return json({
      approval_id: approval.id,
      org_name: "Victopia Labs",
      task_title: approval.task_title,
      task_id: approval.run.task.id,
      employee_name: "Ravi",
      tool_name: approval.tool_name,
      side_effect: approval.side_effect,
      proposed: approval.proposed,
      status: approval.status,
      expires_at: approval.expires_at,
      requires_sign_in: false,
      acting_as: me.email,
    });
  }

  if (!(p = m(/^\/orgs\/[^/]+(\/.*)$/))) return json({ detail: "not found" }, 404);
  const rest = p[1];
  const r = (re) => rest.match(re);

  if (rest === "/ai-employees" && method === "GET") return json({ items: employees.map(employeeItem), used: employees.length, limit: 6 });
  if (rest === "/ai-employees" && method === "POST") {
    const e = { id: `e-${Date.now().toString(36)}`, name: body.name, job_title: body.job_title, department: null, avatar: null, status: "draft", config: { model: "gemini:gemini-2.0-flash", temperature: 0.2, max_steps: 20, enabled_tools: [], ...body.config } };
    employees.push(e);
    return json({ ...e, version_no: 1, created_at: now() }, 201);
  }
  if ((p = r(/^\/ai-employees\/([^/]+)(?:\/(activate|pause))?$/))) {
    const e = employees.find((x) => x.id === p[1]);
    if (!e) return json({ detail: "not found" }, 404);
    if (p[2]) e.status = p[2] === "activate" ? "active" : "paused";
    if (method === "PATCH" && body.config) e.config = body.config;
    return json({ ...e, version_no: 2, created_at: ago(9000) });
  }
  if (rest === "/templates") return json([]);
  if (rest === "/tools") {
    return json(TOOLS);
  }
  if (rest === "/models") return json([{ provider_key: "gemini", display_name: "Google Gemini", model: "gemini-2.0-flash", status: "working", trains_on_data: false }]);

  if (rest === "/connections/available") return json(available);
  if (rest === "/connections" && method === "GET") return json(connections);
  if ((p = r(/^\/connections\/oauth\/([^/]+)\/start$/))) {
    // Stand-in for the provider's consent screen: come straight back
    // connected, as the real callback does after the admin approves.
    const kind = p[1];
    const account = kind === "google" ? "ops@victopia.com" : "ops@victopia.onmicrosoft.com";
    if (!connections.some((c) => c.kind === kind)) {
      connections.unshift({ id: `c-${kind}`, kind, display_name: kind === "google" ? "Google Workspace" : "Microsoft 365", label: account, account, status: "connected", credential_last4: "zz99", last_tested_at: now(), last_error: null, enabled: true, created_at: now(), config: { account } });
    }
    return json({ authorize_url: `/connections?connected=${kind}&account=${encodeURIComponent(account)}` });
  }
  if ((p = r(/^\/connections\/([^/]+)(\/test)?$/))) {
    const c = connections.find((x) => x.id === p[1]);
    if (!c) return json({ detail: "not found" }, 404);
    if (method === "PATCH") c.enabled = body.enabled;
    if (method === "DELETE") {
      connections.splice(connections.indexOf(c), 1);
      res.writeHead(204);
      return res.end();
    }
    if (p[2]) Object.assign(c, { status: "connected", last_tested_at: now(), last_error: null });
    return json(c);
  }

  if (rest === "/notifications" && method === "GET") return json(notifications);
  if (rest === "/notifications" && method === "PUT") {
    const { slack_webhook_url, clear_slack_webhook, ...rest_ } = body;
    notifications = { ...notifications, ...rest_ };
    return json(notifications);
  }
  if (rest === "/notifications/test") return json({ email: `sent to ${me.email}`, slack: "sent" });

  if (rest === "/tasks" && method === "GET") return json(tasks.map(listItem));
  if (rest === "/tasks" && method === "POST") return json(taskView(createTask(body)), 201);
  if ((p = r(/^\/tasks\/([^/]+)(\/cancel)?$/))) {
    const t = tasks.find((x) => x.id === p[1]);
    return t ? json(taskView(t)) : json({ detail: "not found" }, 404);
  }

  if ((p = r(/^\/runs\/([^/]+)\/trace$/))) return json({ events: runs[p[1]]?.events ?? [] });
  if ((p = r(/^\/runs\/([^/]+)\/events$/))) {
    const run = runs[p[1]];
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    res.write(": connected\n\n");
    const last = Number(new URL(req.url, "http://x").searchParams.get("last_event_id") ?? 0);
    for (const e of run?.events.filter((x) => x.seq > last) ?? []) res.write(`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`);
    if (!run || run.status === "completed" || run.status === "failed") return res.end("event: done\ndata: {}\n\n");
    if (!listeners.has(run.id)) listeners.set(run.id, new Set());
    listeners.get(run.id).add(res);
    // res, not req: the request "closes" as soon as its (empty) body is
    // read, which would drop the listener before the first event.
    res.on("close", () => listeners.get(run.id)?.delete(res));
    return;
  }

  if (rest === "/approvals") return json(approvals.filter((a) => a.status === "pending").map(({ run: _r, ...a }) => a));
  if ((p = r(/^\/approvals\/([^/]+)\/(approve|reject)$/))) {
    const a = approvals.find((x) => x.id === p[1]);
    if (!a) return json({ detail: "not found" }, 404);
    decide(a, p[2] === "approve");
    const { run: _r, ...view } = a;
    return json(view);
  }

  if (rest === "/memory" && method === "GET") return json(memory);
  if (rest === "/memory/search") return json(memory.map((item, i) => ({ ...item, score: [0.91, 0.62, 0.48][i] ?? 0.3 })));
  if (rest === "/embedding-config") return json({ provider_key: "gemini", model: "text-embedding-004", dim: 768, memories_needing_reembedding: 0 });
  if (rest === "/members") return json([{ id: me.id, email: me.email, full_name: me.full_name, role: "admin" }, { id: "u-dev", email: "dev@victopia.com", full_name: "Dev Kumar", role: "member" }]);
  if (rest === "/policies" && method === "PUT") {
    // One tool's rule, as the switch on Connections and in the tool picker saves it.
    const tool = TOOLS.find((t) => t.name === body.scope_value);
    if (tool && body.scope === "tool") Object.assign(tool, { effective_setting: body.setting, reason: "set by your company for this tool" });
    return json({ ...body, is_default: false });
  }
  if (rest === "/policies") return json([]);
  if (rest === "/providers/available") return json([{ key: "gemini", display_name: "Google Gemini", default_model: "gemini-2.0-flash", docs_url: null, trains_on_data: false }]);
  if (rest === "/providers") return json([{ provider_key: "gemini", display_name: "Google Gemini", key_last4: "3f9a", status: "working", last_tested_at: ago(30), last_error: null, trains_on_data: false, default_model: "gemini-2.0-flash" }]);

  return json({ detail: `demo server has no ${method} ${path}` }, 404);
}

// ------------------------------------------------------------------ static + routing

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json" };

createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (url.pathname.startsWith("/api/v1/")) {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      let body = {};
      try {
        body = raw ? JSON.parse(raw) : {};
      } catch {
        /* not JSON */
      }
      api(req.method, url.pathname.slice(7), body, req, res);
    });
    return;
  }
  if (url.pathname === "/__demo/stage") {
    res.writeHead(200, { "Content-Type": TYPES[".html"] });
    return createReadStream(STAGE).pipe(res);
  }
  let file = join(DIST, url.pathname);
  if (!file.startsWith(DIST) || !existsSync(file) || statSync(file).isDirectory()) file = join(DIST, "index.html");
  res.writeHead(200, { "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`demo server on http://localhost:${PORT} (slow ×${SLOW})`));

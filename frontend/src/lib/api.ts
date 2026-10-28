/**
 * Typed API client.
 *
 * The access token lives in memory only, never localStorage: anything
 * in localStorage is readable by any script on the page, so an XSS
 * would hand over the session. The refresh token is an httpOnly
 * cookie the browser sends automatically and JavaScript cannot read.
 *
 * A 401 triggers one refresh attempt and one retry. If that fails the
 * session is genuinely over and we stop rather than loop.
 */

const BASE = "/api/v1";

let accessToken: string | null = null;
let onSessionLost: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function onSessionExpired(handler: () => void): void {
  onSessionLost = handler;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly fields?: { field: string; message: string }[],
  ) {
    super(message);
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let detail = response.statusText;
  let fields: { field: string; message: string }[] | undefined;
  try {
    const body = await response.json();
    detail = body.detail ?? detail;
    fields = Array.isArray(body.errors) ? body.errors : undefined;
  } catch {
    // A non-JSON error body is still an error; the status carries it.
  }
  return new ApiError(response.status, detail, fields);
}

async function send(path: string, init: RequestInit, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  // A caller sending something other than JSON (a recording) sets its own type.
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && retry && path !== "/auth/refresh") {
    const refreshed = await refresh();
    if (refreshed) return send(path, init, false);
    onSessionLost?.();
  }

  return response;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, blob: Blob) =>
    request<T>(path, { method: "POST", body: blob, headers: { "Content-Type": blob.type } }),
};

export async function refresh(): Promise<boolean> {
  const response = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) return false;
  const body = (await response.json()) as { access_token: string };
  accessToken = body.access_token;
  return true;
}

/**
 * Subscribe to a run's live events. Resumes from the last seq seen.
 *
 * Read with fetch, not EventSource: EventSource cannot send our sign-in
 * header (so the server refused it), and it hands named events (every
 * run event is named after its type) only to listeners for that name.
 * Stops by itself when the server says the run is done.
 */
export function streamRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  lastSeq = 0,
): () => void {
  const stop = new AbortController();
  let seq = lastSeq;
  let finished = false;

  async function once(): Promise<void> {
    const headers = new Headers({ Accept: "text/event-stream" });
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    const response = await fetch(`${BASE}/me/runs/${runId}/events?last_event_id=${seq}`, {
      headers,
      credentials: "include",
      signal: stop.signal,
    });
    if (response.status === 401) {
      if (!(await refresh())) throw new Error("signed out");
      return;
    }
    if (!response.ok || !response.body) throw new Error(String(response.status));

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += value;
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let name = "message";
        let data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) name = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (name === "done") {
          finished = true;
          return;
        }
        if (!data) continue;
        try {
          const event = JSON.parse(data) as RunEvent;
          if (typeof event.seq === "number") seq = Math.max(seq, event.seq);
          onEvent(event);
        } catch {
          /* a malformed frame should not kill the stream */
        }
      }
    }
  }

  void (async () => {
    let wait = 1000;
    while (!stop.signal.aborted && !finished) {
      try {
        await once();
        wait = 1000;
      } catch {
        if (stop.signal.aborted) return;
        wait = Math.min(wait * 2, 15000);
      }
      if (!finished) await new Promise((resolve) => window.setTimeout(resolve, wait));
    }
  })();

  return () => stop.abort();
}

/** One thing that happened to one of your agents or runs. */
export interface LiveEvent {
  /** "agent_due", "connections_checked", "agent_started", "agent_skipped", or a run event such as "tool_call". */
  type: string;
  at: string;
  /** Null for the assistant itself (a chat that is no agent's own). */
  agent_id: string | null;
  run_id: string | null;
  task_id: string | null;
  seq?: number;
  [key: string]: unknown;
}

/**
 * Watch everything the account is doing, in one stream.
 *
 * EventSource cannot send our sign-in header, so this reads the stream
 * with fetch instead. It reconnects by itself, from the position it last
 * saw, and asks for a fresh sign-in if the old one ran out. Returns a
 * function that stops it.
 */
export function streamAccount(
  onEvent: (event: LiveEvent) => void,
  since: string | null,
  onState?: (connected: boolean) => void,
): () => void {
  const stop = new AbortController();
  let cursor = since ?? "";

  async function once(): Promise<void> {
    const headers = new Headers({ Accept: "text/event-stream" });
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    const query = cursor ? `?last_event_id=${encodeURIComponent(cursor)}` : "";
    const response = await fetch(`${BASE}/me/live${query}`, {
      headers,
      credentials: "include",
      signal: stop.signal,
    });
    if (response.status === 401) {
      if (!(await refresh())) throw new Error("signed out");
      return;
    }
    if (!response.ok || !response.body) throw new Error(String(response.status));

    onState?.(true);
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += value;
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("id: ")) cursor = line.slice(4);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (!data) continue;
        try {
          onEvent(JSON.parse(data) as LiveEvent);
        } catch {
          /* a malformed frame should not kill the stream */
        }
      }
    }
  }

  void (async () => {
    let wait = 1000;
    while (!stop.signal.aborted) {
      try {
        await once();
        wait = 1000; // the server closes it now and then on purpose
      } catch {
        if (stop.signal.aborted) return;
        onState?.(false);
        wait = Math.min(wait * 2, 15000);
      }
      await new Promise((resolve) => window.setTimeout(resolve, wait));
    }
  })();

  return () => stop.abort();
}

// ---------------------------------------------------------------- types

export interface Me {
  id: string;
  email: string;
  /** Added with registration; older sessions may not carry it. */
  username?: string | null;
  full_name: string | null;
}

export interface ProviderOption {
  key: string;
  display_name: string;
  default_model: string | null;
  docs_url: string | null;
  trains_on_data: boolean;
  kind: "llm" | "embedding" | "search";
  free_tier: boolean;
  is_local: boolean;
  signup_url: string | null;
  /** 1 = the easiest to start with. */
  recommended_rank: number | null;
  /** The setup guide, one action per step. */
  guide: GuideStep[];
}

export interface GuideStep {
  id: string;
  title: string;
  detail: string;
  /** "You should see ..." */
  expect: string;
  url?: string;
}

export interface ConnectedProvider {
  provider_key: string;
  display_name: string;
  key_last4: string;
  status: "untested" | "working" | "failed";
  last_tested_at: string | null;
  last_error: string | null;
  trains_on_data: boolean;
  /** What runs: your chosen model, else the provider's default. */
  default_model: string | null;
  model_chosen?: boolean;
  /** Only for "custom": your own OpenAI-compatible server. */
  base_url?: string | null;
  /** What Automatic sends to this AI, in plain words. */
  strengths?: string[] | null;
  /** The plan this key is on, as the person said; null until they do. */
  plan?: "free" | "paid" | null;
}

type TaskStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface TaskListItem {
  id: string;
  title: string | null;
  status: TaskStatus;
  /** Every task is one reply in a conversation. */
  conversation_id: string;
  created_at: string;
}

interface Run {
  id: string;
  status: string;
  step_count: number;
  prompt_tokens: number;
  output_tokens: number;
  estimated_cost_usd: string;
  output: string | null;
  stop_cause: string | null;
  error_message: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface Task extends TaskListItem {
  input: string;
  dry_run: boolean;
  run: Run | null;
}

export interface RunEvent {
  seq: number;
  type: string;
  [key: string]: unknown;
}

export interface ToolEntry {
  name: string;
  pack: string;
  description: string;
  side_effect: "read" | "write" | "destructive";
  effective_setting: "auto" | "ask" | "blocked";
  reason: string;
  permanently_blocked: boolean;
  requires_connection?: string | null;
}

export interface PolicyRow {
  scope: "pack" | "tool";
  scope_value: string;
  side_effect: string | null;
  setting: "auto" | "ask" | "blocked";
  is_default: boolean;
}

export interface Approval {
  id: string;
  run_id: string;
  tool_name: string;
  side_effect: string;
  proposed: Record<string, unknown>;
  status: string;
  expires_at: string;
  created_at: string;
  task_title: string | null;
}

export interface MemoryItem {
  id: string;
  content: string;
  kind: string;
  embedding_model: string;
  created_at: string;
}

export interface EmbeddingConfig {
  provider_key: string;
  model: string;
  dim: number;
  memories_needing_reembedding: number;
}

interface ConnectionField {
  key: string;
  label: string;
  placeholder?: string;
}

export interface AvailableConnection {
  kind: string;
  display_name: string;
  description: string;
  auth: "oauth" | "manual";
  apps: string[];
  configured: boolean;
  tools: string[];
  fields: ConnectionField[];
  secret_label: string | null;
  /** False when a Platform Admin closed this one for us specifically. */
  allowed: boolean;
  blocked_note: string | null;
}

export interface ConnectionItem {
  id: string;
  kind: string;
  display_name: string;
  label: string;
  account: string | null;
  status: "connected" | "untested" | "failed" | "needs_reconnect";
  credential_last4: string;
  last_tested_at: string | null;
  last_error: string | null;
  enabled: boolean;
  created_at: string;
  config: Record<string, unknown>;
}

export interface NotificationSettings {
  email_enabled: boolean;
  email_available: boolean;
  slack_enabled: boolean;
  slack_connected: boolean;
  slack_webhook_last4: string | null;
  on_approval_requested: boolean;
}

export interface ApprovalLinkView {
  approval_id: string;
  owner_name: string;
  task_title: string | null;
  task_id: string | null;
  tool_name: string;
  side_effect: string;
  proposed: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired";
  expires_at: string;
  requires_sign_in: boolean;
  acting_as: string | null;
}

// ---------------------------------------------------------- assistant

export type ChatMode = "general" | "study" | "work" | "research" | "code";

interface ChatModeInfo {
  key: ChatMode;
  label: string;
  for_whom: string;
  examples: string[];
}

export interface AssistantInfo {
  modes: ChatModeInfo[];
  team_roles: { key: string; label: string }[];
}

export interface ConversationItem {
  id: string;
  title: string;
  mode: ChatMode;
  model: string;
  routing: "balanced" | "quality" | "cost" | "private";
  team: boolean;
  agent_id: string | null;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  task_id: string | null;
  /** On a reply: which AI wrote it, as "provider:model". */
  model: string | null;
  /** Why that AI answered: "best of your AIs for coding". */
  model_reason?: string | null;
  /** On a reply that did not finish: what went wrong. */
  error: string | null;
  /** On a reply: tools it used, and "specialist:<role>" for each specialist asked. */
  tools_used: string[];
  /** On a reply that designed an agent: the draft. Nothing exists until Create. */
  draft?: AgentDraft | null;
  created_at: string;
}

export interface Conversation extends ConversationItem {
  messages: ChatMessage[];
  turn: { task_id: string; status: TaskStatus; run_id: string | null } | null;
}

export interface ModelOption {
  provider_key: string;
  display_name: string;
  model: string;
  status: string;
}


// ------------------------------------------------------------- agents

export interface AgentSchedule {
  frequency: "daily" | "weekdays" | "weekly";
  /** 24-hour "HH:MM" in `timezone`. */
  time: string;
  /** Weekly only: 0 Monday to 6 Sunday. */
  days: number[];
  timezone: string;
}

export interface AgentDraft {
  name: string;
  description: string;
  instructions: string;
  tools: string[] | null;
  /** When it runs by itself. Absent or null: only when someone chats with it. */
  schedule?: AgentSchedule | null;
  /** The address of the one spreadsheet it may write to. */
  spreadsheet?: string | null;
}

/** One link in the chain behind an agent: is it ready, and how to fix it. */
interface ReadinessCheck {
  ok: boolean;
  layer: "app" | "platform" | "connection" | "permission" | "agent" | "setup";
  title: string;
  detail: string;
  /** "connect:google", "reconnect:google[:service:level]", "permissions", "ask_admin", "choose_sheet". */
  fix: string | null;
  service: string | null;
  level: string | null;
  tool: string | null;
}

export interface Readiness {
  ok: boolean;
  checks: ReadinessCheck[];
}

export interface RunNowResult {
  status: "started" | "needs_attention" | "busy";
  message: string;
  task_id: string | null;
  conversation_id: string | null;
  readiness: Readiness | null;
}

interface AgentUsage {
  runs: number;
  prompt_tokens: number;
  output_tokens: number;
  /** Estimated: with your own keys we never see the invoice. A decimal string. */
  cost_usd: string;
}

export interface Agent {
  id: string;
  name: string;
  handle: string;
  description: string;
  instructions: string;
  tools: string[] | null;
  /** True when the tools were chosen from the instructions. */
  tools_auto: boolean;
  model: string;
  routing: "balanced" | "quality" | "cost" | "private";
  created_at: string;
  usage: AgentUsage;
  schedule: AgentSchedule | null;
  schedule_text: string | null;
  schedule_enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  /** "running", "completed", "failed" or "needs_attention". */
  last_status: string | null;
  last_summary: string | null;
  /** The chat where its runs are written. */
  run_conversation_id: string | null;
  max_steps: number;
  scope: { sheet_ids: string[] };
}

export interface AgentStarter {
  key: string;
  kind: "mode" | "specialist";
  name: string;
  description: string;
  instructions: string;
}

export interface AgentToolInfo {
  name: string;
  pack: string;
  description: string;
  side_effect: "read" | "write" | "destructive";
  needs_app: string | null;
}

export interface AgentRunRow {
  run_id: string;
  conversation_id: string;
  title: string;
  agent_id: string | null;
  status: string;
  cost_usd: string;
  prompt_tokens: number;
  output_tokens: number;
  started_at: string | null;
  ended_at: string | null;
}

export interface AgentsOverview {
  agents: Agent[];
  starters: AgentStarter[];
  assistant_usage: AgentUsage;
  tools: AgentToolInfo[];
  recent_runs: AgentRunRow[];
  limit: number;
}

/** The agent tree's starting picture: see `GET /me/agents/tree`. */
export type TreeState = "idle" | "working" | "waiting" | "failed";

export interface AgentsTree {
  now: string;
  scheduler: {
    next_run_at: string | null;
    next_agent_id: string | null;
    next_agent_name: string | null;
    scheduled_count: number;
  };
  lead: { state: TreeState; active_run_id: string | null; active_task_id: string | null };
  agents: {
    id: string;
    name: string;
    state: TreeState;
    next_run_at: string | null;
    schedule_text: string | null;
    last_summary: string | null;
    active_run_id: string | null;
    active_task_id: string | null;
  }[];
  helpers: { key: string; label: string }[];
  recent_scheduler: LiveEvent[];
  /** Where to start the live stream so nothing falls between the two. */
  cursor: string;
}

/** The result of "find a model this key can use". */
export interface AutoModelResult {
  provider: ConnectedProvider;
  /** The model it switched to, or null when none of those tried answered. */
  selected: string | null;
  tried: { model: string; ok: boolean; reason: string | null }[];
}


// ---- service access

/** One part of an app (Gmail, Sheets...), as the connect screen sees it. */
export interface ServiceInfo {
  id: string;
  app: string;
  name: string;
  can_edit: boolean;
  allowed: { read: boolean; edit: boolean };
  note: string | null;
  /** What the current connection holds; null when not connected. */
  granted: { read: boolean; edit: boolean } | null;
}

/** One past run in the History list: see `GET /me/history/runs`. */
export interface HistoryModel {
  provider_key: string;
  model: string;
  /** "unknown" when there is no price on file for the model. */
  plan: "free" | "paid" | "unknown";
  prompt_tokens: number;
  output_tokens: number;
  estimated_cost_usd: string;
}

export interface HistoryItem {
  id: string;
  task_id: string;
  conversation_id: string;
  agent_id: string | null;
  agent_name: string | null;
  title: string | null;
  summary: string;
  status: string;
  trigger: "chat" | "schedule" | "manual";
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  duration_seconds: number | null;
  estimated_cost_usd: string;
  models: HistoryModel[];
}

/** What the models cost: see `GET /me/usage`. Every figure is an estimate. */
interface UsageModelChoice {
  provider_key: string;
  provider_name: string;
  model: string;
}

interface UsagePlanShare {
  calls: number;
  tokens: number;
  cost_usd: string;
}

export interface UsageModel extends UsageModelChoice {
  plan: "free" | "paid" | "unknown";
  runs: number;
  calls: number;
  tokens: number;
  cost_usd: string;
  /** Null when the model has no price on file: unpriced, not zero. */
  saved_usd: string | null;
  is_reference: boolean;
  /** Share of all calls in the range, 0 to 1. */
  share: number;
}

export interface Usage {
  range: "7d" | "30d" | "all";
  runs: number;
  calls: number;
  tokens: number;
  total_cost_usd: string;
  saved_usd: string;
  unpriced_calls: number;
  reference: UsageModelChoice | null;
  reference_is_default: boolean;
  reference_choices: UsageModelChoice[];
  free: UsagePlanShare;
  paid: UsagePlanShare;
  unknown: UsagePlanShare;
  agents: { agent_id: string | null; name: string; runs: number; tokens: number; cost_usd: string }[];
  models: UsageModel[];
}

export interface HistoryPage {
  items: HistoryItem[];
  next: string | null;
}

export interface HistoryLane {
  kind: "agent" | "specialist" | "tool";
  label: string;
  key: string;
  start_ms: number;
  end_ms: number;
  ok: boolean | null;
}

export interface HistoryDetail extends HistoryItem {
  result: string | null;
  error_message: string | null;
  stop_cause: string | null;
  step_count: number;
  prompt_tokens: number;
  output_tokens: number;
  lanes: HistoryLane[];
  can_run_again: boolean;
}

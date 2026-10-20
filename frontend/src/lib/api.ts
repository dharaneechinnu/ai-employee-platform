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

/** Subscribe to a run's live events. Resumes from the last seq seen. */
export function streamRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  lastSeq = 0,
): () => void {
  // EventSource cannot set an Authorization header, so the token goes
  // in the query string. Acceptable only because it is short-lived;
  // a long-lived credential must never travel in a URL.
  const url = `${BASE}/me/runs/${runId}/events?last_event_id=${lastSeq}`;
  const source = new EventSource(url, { withCredentials: true });

  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as RunEvent);
    } catch {
      /* a malformed frame should not kill the stream */
    }
  };
  source.addEventListener("done", () => source.close());
  source.onerror = () => source.close();

  return () => source.close();
}

// ---------------------------------------------------------------- types

export interface Me {
  id: string;
  email: string;
  full_name: string | null;
  /** The cap on AI Employees for this account, set by the platform. */
  max_employees: number;
}

export type EmployeeStatus = "draft" | "active" | "paused" | "archived";

export interface EmployeeListItem {
  id: string;
  name: string;
  job_title: string | null;
  department: string | null;
  avatar: string | null;
  status: EmployeeStatus;
}

export interface EmployeeList {
  items: EmployeeListItem[];
  used: number;
  limit: number;
}

export interface Employee extends EmployeeListItem {
  version_no: number;
  config: EmployeeConfig;
  created_at: string;
}

export interface EmployeeConfig {
  guided?: {
    what_it_does: string;
    what_it_must_never_do?: string | null;
    tone?: string | null;
    when_to_ask_a_human?: string | null;
    what_good_looks_like?: string | null;
  } | null;
  raw_instructions?: string | null;
  model: string;
  /** With model "auto": what Automatic aims for. */
  routing?: "balanced" | "quality" | "cost" | "private";
  temperature: number;
  max_steps: number;
  enabled_tools: string[];
}

export interface Template {
  id: string;
  name: string;
  description: string | null;
  department: string | null;
  config: EmployeeConfig;
  is_platform_template: boolean;
}

export interface ProviderOption {
  key: string;
  display_name: string;
  default_model: string | null;
  docs_url: string | null;
  trains_on_data: boolean;
}

export interface ConnectedProvider {
  provider_key: string;
  display_name: string;
  key_last4: string;
  status: "untested" | "working" | "failed";
  last_tested_at: string | null;
  last_error: string | null;
  trains_on_data: boolean;
  /** What runs: the company's chosen model, else the provider's default. */
  default_model: string | null;
  model_chosen?: boolean;
  /** Only for "custom": the company's own OpenAI-compatible server. */
  base_url?: string | null;
  /** What Automatic sends to this AI, in plain words. */
  strengths?: string[] | null;
}

export interface McpServerTool {
  name: string;
  remote_name: string;
  title: string | null;
  description: string;
  side_effect: "read" | "write" | "destructive";
}

export interface McpServer {
  id: string;
  name: string;
  slug: string;
  url: string;
  token_last4: string | null;
  status: string;
  last_error: string | null;
  last_synced_at: string | null;
  tools: McpServerTool[];
}

export type TaskStatus =
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
  employee_id: string;
  created_at: string;
}

export interface Run {
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
  /** Set for tools from an MCP server: the server's own wording. */
  label?: string | null;
  pack_label?: string | null;
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
  scope: string;
  employee_id: string | null;
  embedding_model: string;
  created_at: string;
}

export interface EmbeddingConfig {
  provider_key: string;
  model: string;
  dim: number;
  memories_needing_reembedding: number;
}

export interface Person {
  id: string;
  email: string;
  full_name: string | null;
  active: boolean;
  max_employees: number;
  employees_used: number;
}

export interface ConnectionField {
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
  on_task_completed: boolean;
  on_task_failed: boolean;
}

export interface ApprovalLinkView {
  approval_id: string;
  org_name: string;
  task_title: string | null;
  task_id: string | null;
  employee_name: string | null;
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

export interface ChatModeInfo {
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

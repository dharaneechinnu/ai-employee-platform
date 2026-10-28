import { ApiError } from "../../lib/api";

/**
 * The staff console's own client: a separate token, held in memory only,
 * so it is never mixed up with a customer's session and is gone when the
 * tab closes. Every type here is counts, dates and yes or no. There is no
 * type for a task, a memory, a key or a token, because no endpoint
 * returns one.
 */

const BASE = "/api/v1/platform";

let platformToken: string | null = null;

export function setPlatformToken(token: string | null) {
  platformToken = token;
}

export async function call<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: method ?? (body ? "POST" : "GET"),
    headers: {
      "Content-Type": "application/json",
      ...(platformToken ? { Authorization: `Bearer ${platformToken}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    const detail = typeof problem.detail === "string" ? problem.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** The setup link a person opens to choose their own password. */
export function setupLinkFor(token: string): string {
  return `${window.location.origin}/login?token=${token}`;
}

export interface StaffMe {
  id: string;
  email: string;
}

/** One account, as staff may see it. */
export interface Person {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  active: boolean;
  created_at: string;
  joined_via: "self" | "invited";
  setup_link: "waiting" | "used" | "expired" | null;
  setup_link_expires_at: string | null;
  /** The later of their last sign-in and their last session renewal. */
  last_active_at: string | null;
}

export interface Overview {
  people_total: number;
  people_active: number;
  people_suspended: number;
  joined_this_week_self: number;
  joined_this_week_invited: number;
  setup_links_waiting: number;
  setup_links_expiring_soon: number;
  ai_keys_total: number;
  ai_keys_free: number;
  ai_keys_paid: number;
  agents_built: number;
  runs_this_week: number;
}

/** Whether a person has connected a provider. Never the key, not even masked. */
export interface ProviderStatus {
  provider_key: string;
  connected: boolean;
  status: string;
  last_tested_at: string | null;
}

export interface PersonDetail extends Person {
  task_count: number;
  agent_count: number;
  scheduled_agent_count: number;
  runs_this_week: number;
  providers: ProviderStatus[];
  apps: { kind: string; display_name: string; connected: boolean }[];
}

/** One kind of app, as it stands for one person. */
export interface ConnectionAccess {
  kind: string;
  display_name: string;
  platform_ready: boolean;
  allowed: boolean;
  overridden: boolean;
  note: string | null;
  everyone_allowed: boolean;
}

/** One kind of app, as it stands for everyone. */
export interface AppAccess {
  kind: string;
  display_name: string;
  platform_ready: boolean;
  allowed: boolean;
  people_connected: number;
  people_with_own_settings: number;
}

/** One part of an app at one level, for everyone. */
export interface ServiceAccessRow {
  service: string;
  app: string;
  name: string;
  level: "read" | "edit";
  allowed: boolean;
}

export interface PersonServiceRow extends ServiceAccessRow {
  overridden: boolean;
  note: string | null;
}

/** One one-click provider, as the console sees it. */
export interface OAuthApp {
  provider: string;
  display_name: string;
  client_id: string | null;
  secret_last4: string | null;
  enabled: boolean;
  configured: boolean;
  redirect_uri: string;
  docs_url: string;
  from_environment: boolean;
  updated_at: string | null;
  updated_by_email: string | null;
}

/** One entry in the AI provider catalog. */
export interface Provider {
  key: string;
  display_name: string;
  kind: "llm" | "search" | string;
  default_model: string | null;
  trains_on_data: boolean;
  enabled: boolean;
  free_tier: boolean;
  is_local: boolean;
  people_connected: number;
  paused_at: string | null;
  paused_by_email: string | null;
}

/** One line of the diary: who did what to which account, never content. */
export interface AuditEntry {
  id: string;
  admin_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_label: string | null;
  detail: string | null;
  created_at: string;
}

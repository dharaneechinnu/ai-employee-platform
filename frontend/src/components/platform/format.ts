import type { AuditEntry, Person } from "./api";

/**
 * Words for the staff console: names, dates, "2 hours ago", and the
 * audit log in plain English. Kept apart from the screens so the same
 * phrase reads the same everywhere.
 */

/** A person's name, or the best stand-in for one. */
export function nameOf(p: Pick<Person, "full_name" | "username" | "email">): string {
  return p.full_name?.trim() || p.username || p.email;
}

/** First name, for sentences like "Access just for Asha". */
export function firstName(p: Pick<Person, "full_name" | "username" | "email">): string {
  return nameOf(p).split(/\s+/)[0];
}

export function initials(name: string): string {
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : name.slice(0, 2);
  return letters.toUpperCase();
}

// Deep tones that all carry white initials at 4.5:1 or better.
const TILE_COLOURS = ["#b45309", "#0369a1", "#5a3fd8", "#15803d", "#be123c", "#4b4860", "#7c3aed", "#075985"];

/** A stable colour per person, so the same face comes back each visit. */
export function tileColour(seed: string): string {
  let value = 0;
  for (const char of seed) value = (value * 31 + char.charCodeAt(0)) >>> 0;
  return TILE_COLOURS[value % TILE_COLOURS.length];
}

const DAY = 24 * 60 * 60 * 1000;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "12 Oct 2026". Spelled out by hand: some browsers say "Sept". */
export function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "20 Oct, 14:02". */
export function dayAndTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${clock(iso)}`;
}

/** "Tuesday 28 October". */
export function longDay(d: Date): string {
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

/** "14:02". */
export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** "6 pm", "6:30 pm". */
function hour(d: Date): string {
  const h = d.getHours() % 12 || 12;
  const m = d.getMinutes();
  return `${h}${m ? `:${String(m).padStart(2, "0")}` : ""} ${d.getHours() < 12 ? "am" : "pm"}`;
}

/** "5 minutes ago", "2 hours ago", "Yesterday", "9 days ago". */
export function ago(iso: string, now = new Date()): string {
  const then = new Date(iso);
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const days = Math.round((startOfDay(now) - startOfDay(then)) / DAY);
  if (days === 0) {
    const hours = Math.round(minutes / 60);
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return shortDate(iso);
}

/** "Not yet signed in" or when they were last around. */
export function lastActive(p: Person, now = new Date()): string {
  return p.last_active_at ? ago(p.last_active_at, now) : "Not yet signed in";
}

/** Whether a waiting setup link stops working before midnight today. */
export function expiresToday(p: Person, now = new Date()): boolean {
  if (p.setup_link !== "waiting" || !p.setup_link_expires_at) return false;
  return startOfDay(new Date(p.setup_link_expires_at)) === startOfDay(now);
}

/** "Expires today, 6 pm", "Expires tomorrow", "Expires in 5 days". */
export function linkNote(p: Person, now = new Date()): string {
  if (p.setup_link === "expired") return "Expired";
  if (!p.setup_link_expires_at) return "";
  const at = new Date(p.setup_link_expires_at);
  const days = Math.round((startOfDay(at) - startOfDay(now)) / DAY);
  if (days <= 0) return `Expires today, ${hour(at)}`;
  if (days === 1) return "Expires tomorrow";
  return `Expires in ${days} days`;
}

/** "Signed up themselves", "Invited · link waiting", ... */
export function joinedLabel(p: Person): string {
  if (p.joined_via === "self") return "Signed up themselves";
  if (p.setup_link === "used") return "Invited · link used";
  if (p.setup_link === "expired") return "Invited · link expired";
  return "Invited · link waiting";
}

// --------------------------------------------------------------- names

/** Short names for each kind of app, as the console says them. */
export const APP_NAME: Record<string, string> = {
  google: "Google",
  microsoft: "Microsoft 365",
  email: "Mailbox (IMAP)",
  github: "GitHub",
  database: "PostgreSQL",
  slack: "Slack channel",
  teams: "Teams channel",
};

/** What each part of an app lets an agent do, look then change. */
export const SERVICE_HINT: Record<string, string> = {
  "google.gmail": "Read mail · send and label",
  "google.calendar": "See events · add and move them",
  "google.drive": "Find and read files",
  "google.sheets": "Read sheets · edit cells",
  "microsoft.mail": "Read mail · send and file",
  "microsoft.calendar": "See events · add and move them",
  "microsoft.files": "Read files · edit workbooks",
};

const SERVICE_NAME: Record<string, string> = {
  "google.gmail": "Gmail",
  "google.calendar": "Google Calendar",
  "google.drive": "Google Drive",
  "google.sheets": "Google Sheets",
  "microsoft.mail": "Outlook mail",
  "microsoft.calendar": "Outlook calendar",
  "microsoft.files": "OneDrive and Excel",
};

/** "Gmail · change" from "google.gmail:edit". */
export function serviceLabel(detail: string): string {
  const [service, level] = detail.split(":");
  return `${SERVICE_NAME[service] ?? service} · ${level === "edit" ? "change" : "look"}`;
}

/** The staff member, as the log and the strip show them. */
export function staffName(email: string | null): string {
  return email ?? "A removed staff account";
}

// ----------------------------------------------------------- audit log

export type AuditGroup = "account" | "access" | "app" | "ai" | "login";

export const AUDIT_GROUPS: { key: AuditGroup | "all"; label: string }[] = [
  { key: "all", label: "All changes" },
  { key: "account", label: "Accounts" },
  { key: "access", label: "Access" },
  { key: "app", label: "Sign-in apps" },
  { key: "ai", label: "AI providers" },
  { key: "login", label: "Staff sign-ins" },
];

/** How an entry is drawn: its mark, its tint and its group's name. */
export type AuditTone = "account" | "block" | "allow" | "app" | "ai" | "login";

export interface AuditLine {
  what: string;
  group: AuditGroup;
  tone: AuditTone;
  /** Staff's own words (a suspend reason), shown in quotes. */
  note: string | null;
}

const PROVIDER_ACTIONS: Record<string, [string, AuditTone]> = {
  provider_added: ["added the AI provider", "ai"],
  provider_updated: ["changed the settings of", "ai"],
  provider_enabled: ["turned on", "allow"],
  provider_paused: ["paused", "ai"],
};

/**
 * One audit entry, as a sentence: "suspended Meera Iyer's account."
 * `providers` maps a provider key to its name, for "paused Mistral".
 */
export function auditLine(e: AuditEntry, providers: Record<string, string> = {}): AuditLine {
  const who = e.target_label ?? "an account";
  const detail = e.detail ?? "";
  const app = APP_NAME[detail] ?? detail;
  const account = (what: string, tone: AuditTone = "account", note: string | null = null): AuditLine => ({
    what,
    group: "account",
    tone,
    note,
  });
  const access = (what: string, tone: AuditTone): AuditLine => ({ what, group: "access", tone, note: null });
  const signIn = (what: string, tone: AuditTone = "app"): AuditLine => ({ what, group: "app", tone, note: null });
  const oauthName = APP_NAME[e.target_id ?? ""] ?? e.target_id ?? "a";

  switch (e.action) {
    case "platform_login":
      return { what: "signed in.", group: "login", tone: "login", note: null };
    case "account_created":
      return account(`created an account for ${who} and made a setup link.`);
    case "account_suspended":
      return account(`suspended ${who}’s account.`, "block", e.detail);
    case "account_restored":
      return account(`restored ${who}’s account.`, "allow");
    case "setup_link_reissued":
      return account(`made a new setup link for ${who}.`);
    case "connection_allowed":
      return access(`allowed ${app} for ${who}.`, "allow");
    case "connection_blocked":
      return access(`blocked ${app} for ${who}.`, "block");
    case "connection_access_inherited":
      return access(`set ${app} back to the same as everyone for ${who}.`, "account");
    case "app_allowed":
      return access(`turned on ${app} for everyone.`, "allow");
    case "app_blocked":
      return access(`turned off ${app} for everyone.`, "block");
    case "service_allowed":
    case "service_blocked":
    case "service_inherited": {
      const part = serviceLabel(detail);
      const forWhom = e.target_type === "platform" ? "everyone" : who;
      if (e.action === "service_inherited") return access(`set ${part} back to the same as everyone for ${who}.`, "account");
      if (e.target_type === "platform") {
        return access(`turned ${e.action === "service_allowed" ? "on" : "off"} ${part} for everyone.`, e.action === "service_allowed" ? "allow" : "block");
      }
      return access(`${e.action === "service_allowed" ? "allowed" : "blocked"} ${part} for ${forWhom}.`, e.action === "service_allowed" ? "allow" : "block");
    }
    case "oauth_app_registered":
      return signIn(`set up ${oauthName} sign-in.`);
    case "oauth_app_updated":
      return signIn(`replaced the ${oauthName} sign-in secret.`);
    case "oauth_app_enabled":
      return signIn(`turned on ${oauthName} sign-in.`, "allow");
    case "oauth_app_disabled":
      return signIn(`turned off ${oauthName} sign-in.`, "block");
    case "oauth_app_removed":
      return signIn(`removed the ${oauthName} sign-in app.`, "block");
  }
  const provider = PROVIDER_ACTIONS[e.action];
  if (provider) {
    const suffix = e.action === "provider_added" || e.action === "provider_updated" ? "." : " for everyone.";
    const name = providers[e.target_id ?? ""] ?? e.target_id ?? "";
    return { what: `${provider[0]} ${name}${suffix}`, group: "ai", tone: provider[1], note: null };
  }
  // An action this screen does not know yet still shows, in its own words.
  return { what: `${e.action.replace(/_/g, " ")}${detail ? ` (${detail})` : ""}.`, group: "account", tone: "account", note: null };
}

export const TONE_STYLE: Record<AuditTone, { mark: string; className: string; label: string }> = {
  account: { mark: "A", className: "bg-accent-soft text-accent-text", label: "Account" },
  block: { mark: "!", className: "bg-bad-soft text-bad-text", label: "Access" },
  allow: { mark: "✓", className: "bg-ok-soft text-ok-text", label: "Access" },
  app: { mark: "S", className: "bg-run-soft text-run-text", label: "Sign-in app" },
  ai: { mark: "AI", className: "bg-ask-soft text-ask-text", label: "AI provider" },
  login: { mark: "→", className: "bg-raised text-muted", label: "Staff sign-in" },
};

export const GROUP_LABEL: Record<AuditGroup, string> = {
  account: "Account",
  access: "Access",
  app: "Sign-in app",
  ai: "AI provider",
  login: "Staff sign-in",
};

/** "Today, Tuesday 28 October", "Yesterday, ...", "Sunday 26 October". */
export function dayHeading(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const days = Math.round((startOfDay(now) - startOfDay(d)) / DAY);
  const label = longDay(d) + (d.getFullYear() !== now.getFullYear() ? ` ${d.getFullYear()}` : "");
  if (days === 0) return `Today, ${label}`;
  if (days === 1) return `Yesterday, ${label}`;
  return label;
}

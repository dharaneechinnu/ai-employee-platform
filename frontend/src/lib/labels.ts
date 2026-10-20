/**
 * Plain-English names for things the code calls by internal ids.
 *
 * The people using this app run operations, sales and HR teams. They
 * should read "Send a Gmail email", not `gmail_send`, and "Can't be
 * undone", not "destructive". One table, so every screen says the
 * same thing for the same tool.
 */

export const TOOL_LABELS: Record<string, string> = {
  gmail_search: "Search Gmail",
  gmail_read: "Read a Gmail email",
  gmail_create_draft: "Save a Gmail draft",
  gmail_send: "Send a Gmail email",
  google_calendar_list: "See Google Calendar",
  google_calendar_create: "Add a Google Calendar event",
  google_drive_search: "Search Google Drive",
  google_drive_read: "Read a Google Drive file",
  outlook_search: "Search Outlook",
  outlook_read: "Read an Outlook email",
  outlook_create_draft: "Save an Outlook draft",
  outlook_send: "Send an Outlook email",
  outlook_calendar_list: "See Outlook calendar",
  outlook_calendar_create: "Add an Outlook calendar event",
  onedrive_search: "Search OneDrive",
  onedrive_read: "Read a OneDrive file",
  list_emails: "List mailbox emails",
  read_email: "Read a mailbox email",
  save_draft: "Save a mailbox draft",
  send_email: "Send an email",
  list_tables: "See database tables",
  describe_table: "See a table's columns",
  run_query: "Look up data (read-only)",
  get_webpage: "Read a web page",
  recall: "Look up company memory",
  remember: "Save to company memory",
  github_list_repos: "See GitHub repositories",
  github_search_code: "Search code on GitHub",
  github_read_file: "Read a file on GitHub",
  github_list_issues: "See issues and pull requests",
  github_read_issue: "Read an issue or pull request",
  github_pr_diff: "Review a pull request's changes",
  github_list_commits: "See recent commits",
  github_ci_status: "Check CI (GitHub Actions)",
  github_comment: "Comment on GitHub",
  github_create_issue: "Open a GitHub issue",
  github_propose_change: "Propose a code change (pull request)",
  ask_specialist: "Ask a specialist",
};

export function humanise(id: string): string {
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Tools from a company's MCP servers are named "mcp__<server>__<tool>".
// The app has no built-in words for them, so it uses the server's own
// (learned when the tool list loads), or the tool's name made readable.
const MCP_PREFIX = "mcp__";
const learnedTools = new Map<string, string>();
const learnedPacks = new Map<string, string>();

export function isMcpTool(name: string): boolean {
  return name.startsWith(MCP_PREFIX);
}

export function learnToolLabels(entries: { name: string; pack: string; label?: string | null; pack_label?: string | null }[]) {
  for (const e of entries) {
    if (e.label) learnedTools.set(e.name, e.label);
    if (e.pack_label) learnedPacks.set(e.pack, e.pack_label);
  }
}

export function toolLabel(name: string): string {
  const known = TOOL_LABELS[name] ?? learnedTools.get(name);
  if (known) return known;
  if (isMcpTool(name)) return humanise(name.split("__").slice(2).join("__") || name);
  return humanise(name);
}

/** A sentence fragment: "Ravi wants to send a Gmail email". */
export function toolAction(name: string): string {
  const label = toolLabel(name);
  return label.charAt(0).toLowerCase() + label.slice(1);
}

export const PACK_LABELS: Record<string, string> = {
  google: "Google Workspace",
  microsoft: "Microsoft 365",
  email: "Mailbox (IMAP)",
  database: "Database",
  web: "Web",
  memory: "Memory",
  delegation: "Teamwork",
  github: "GitHub",
};

export function packLabel(pack: string): string {
  const known = PACK_LABELS[pack] ?? learnedPacks.get(pack);
  if (known) return known;
  if (pack.startsWith(MCP_PREFIX)) return `${humanise(pack.slice(MCP_PREFIX.length))} (MCP)`;
  return humanise(pack);
}

export type Effect = "read" | "write" | "destructive";

export const EFFECTS: Record<Effect, { label: string; hint: string; tone: "ok" | "brand" | "bad" }> = {
  read: { label: "Only reads", hint: "Looks at information; changes nothing.", tone: "ok" },
  write: { label: "Makes changes", hint: "Creates or edits something, like a draft.", tone: "brand" },
  destructive: { label: "Can't be undone", hint: "Sends or deletes something for good.", tone: "bad" },
};

export function effectLabel(effect: string): string {
  return EFFECTS[effect as Effect]?.label ?? humanise(effect);
}

export function effectTone(effect: string): "ok" | "brand" | "bad" {
  return EFFECTS[effect as Effect]?.tone ?? "brand";
}

const PROVIDER_NAMES: Record<string, string> = {
  gemini: "Gemini",
  groq: "Groq",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
  openai: "OpenAI",
  anthropic: "Claude",
  mistral: "Mistral",
  custom: "Your server",
};

/** "auto" (and the old "gemini-flash") means: whichever AI is connected. */
export function isAutoModel(model: string): boolean {
  return ["auto", "gemini-flash", ""].includes(model.trim());
}

export function modelLabel(model: string): string {
  if (isAutoModel(model)) return "Automatic AI";
  const [provider, name] = model.includes(":") ? model.split(/:(.*)/s) : ["gemini", model];
  // The model name usually already says the provider ("gemini-2.0-flash").
  return name.toLowerCase().includes(provider.toLowerCase()) ? name : `${PROVIDER_NAMES[provider] ?? humanise(provider)} ${name}`;
}

/** "Default for Google · can't be undone", from the server's reason. */
export function plainReason(reason: string): string {
  const m = reason.match(/^platform default for (\w+) (read|write|destructive) actions$/i);
  if (m) return `Default for ${packLabel(m[1])} · ${effectLabel(m[2]).toLowerCase()}`;
  if (/^platform default for this tool$/i.test(reason)) return "Default for this tool";
  return reason.charAt(0).toUpperCase() + reason.slice(1);
}

// "14 Oct 2026, 7:41 pm": the month as a word, so it reads the same
// for everyone (10/14 vs 14/10 is ambiguous). A fixed, valid locale
// rather than the browser's, whose tag can be one Intl rejects.
const DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : DATE_TIME.format(date);
}

// ------------------------------------------------- automatic routing

export type Routing = "balanced" | "quality" | "cost" | "private";

/** The four ways "Automatic" can pick one of the person's connected AIs. */
export const AUTO_CHOICES: { routing: Routing; label: string; hint: string }[] = [
  { routing: "balanced", label: "Automatic · Balanced", hint: "Strongest AI for hard work, fast and cheap for easy questions" },
  { routing: "quality", label: "Automatic · Best quality", hint: "Always the most capable of your AIs" },
  { routing: "cost", label: "Automatic · Lowest cost", hint: "The cheapest of your AIs that can do the job" },
  { routing: "private", label: "Automatic · Private only", hint: "Only your own server: nothing leaves it" },
];

/** One select value for "which AI": "auto|balanced", or "provider:model" when pinned. */
export function aiChoiceValue(model: string, routing: string | undefined): string {
  return isAutoModel(model) ? `auto|${routing || "balanced"}` : model;
}

export function parseAiChoice(value: string): { model: string; routing?: Routing } {
  if (value.startsWith("auto|")) return { model: "auto", routing: value.slice(5) as Routing };
  return { model: value };
}

export function aiChoiceLabel(model: string, routing?: string): string {
  if (!isAutoModel(model)) return modelLabel(model);
  return AUTO_CHOICES.find((c) => c.routing === (routing || "balanced"))?.label ?? "Automatic";
}

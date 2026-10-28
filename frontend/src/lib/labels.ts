/**
 * Plain-English names for things the code calls by internal ids.
 *
 * The person using this app is not a programmer. They should read "Send a Gmail email", not `gmail_send`, and "Can't be
 * undone", not "destructive". One table, so every screen says the
 * same thing for the same tool.
 */

const TOOL_LABELS: Record<string, string> = {
  gmail_search: "Search Gmail",
  gmail_read: "Read a Gmail email",
  gmail_create_draft: "Save a Gmail draft",
  gmail_send: "Send a Gmail email",
  gmail_organize: "Archive, label or mark Gmail emails",
  google_calendar_list: "See Google Calendar",
  google_calendar_create: "Add a Google Calendar event",
  google_calendar_update: "Move or change a Google Calendar event",
  google_calendar_cancel: "Cancel a Google Calendar event",
  google_drive_search: "Search Google Drive",
  google_drive_read: "Read a Google Drive file",
  outlook_search: "Search Outlook",
  outlook_read: "Read an Outlook email",
  outlook_create_draft: "Save an Outlook draft",
  outlook_send: "Send an Outlook email",
  outlook_organize: "Archive, flag or mark Outlook emails",
  outlook_calendar_list: "See Outlook calendar",
  outlook_calendar_create: "Add an Outlook calendar event",
  outlook_calendar_update: "Move or change an Outlook calendar event",
  outlook_calendar_cancel: "Cancel an Outlook calendar event",
  onedrive_search: "Search OneDrive",
  onedrive_read: "Read a OneDrive file",
  excel_read: "Read an Excel workbook",
  excel_append_rows: "Add rows to an Excel workbook",
  excel_update_cells: "Change cells in an Excel workbook",
  slack_post: "Post to a Slack channel",
  teams_post: "Post to a Teams channel",
  list_emails: "List mailbox emails",
  read_email: "Read a mailbox email",
  save_draft: "Save a mailbox draft",
  send_email: "Send an email",
  list_tables: "See database tables",
  describe_table: "See a table's columns",
  run_query: "Look up data (read-only)",
  get_webpage: "Read a web page",
  recall: "Look up your memory",
  remember: "Save to your memory",
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
  current_time: "Know today's date and time",
  calculator: "Do exact maths",
  text_tools: "Count, compare and pull out text",
  python_run: "Run a small Python program",
  report_write: "Write a finished report",
  web_search: "Search the web",
  sheets_create: "Create a Google Sheet",
  sheets_read: "Read a Google Sheet",
  sheets_append_rows: "Add rows to a Google Sheet",
  sheets_update_cells: "Change cells in a Google Sheet",
  propose_agent: "Draft a new agent",
};

function humanise(id: string): string {
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? humanise(name);
}

/** A sentence fragment: "Ravi wants to send a Gmail email". */
export function toolAction(name: string): string {
  const label = toolLabel(name);
  return label.charAt(0).toLowerCase() + label.slice(1);
}

const PACK_LABELS: Record<string, string> = {
  google: "Google Workspace",
  microsoft: "Microsoft 365",
  email: "Mailbox (IMAP)",
  database: "Database",
  web: "Web",
  memory: "Memory",
  delegation: "Specialists",
  github: "GitHub",
  clock: "Date and time",
  calculator: "Maths",
  text: "Text",
  python_run: "Python",
  report: "Reports",
  search: "Web search",
  sheets: "Google Sheets",
  excel: "Excel (OneDrive)",
  chat: "Team chat",
  team: "Specialists",
  builder: "Agent builder",
};

export function packLabel(pack: string): string {
  return PACK_LABELS[pack] ?? humanise(pack);
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
function isAutoModel(model: string): boolean {
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

/**
 * One line a non-technical person can read: what turning the tool on
 * lets the agent do. Tools without an entry fall back to the first
 * sentence of their own description.
 */
const TOOL_BLURBS: Record<string, string> = {
  current_time: "Lets it know today's date, so it can tell upcoming from past.",
  calculator: "Does sums, percentages and averages exactly instead of guessing.",
  text_tools: "Counts words, finds emails, links and numbers, and shows what changed between two versions.",
  python_run: "Runs a short program for data work. No internet and no files.",
  report_write: "Puts the findings into one finished, tidy report.",
  web_search: "Looks things up on the web.",
  get_webpage: "Opens a web page and reads it.",
  recall: "Remembers what you told it before, such as corrections.",
  remember: "Saves something useful to remember next time.",
  sheets_create: "Makes a new Google Sheet for its results and keeps using it.",
  sheets_read: "Reads what is already in a Google Sheet.",
  sheets_append_rows: "Adds new rows to the bottom of its Google Sheet.",
  sheets_update_cells: "Fixes values in rows that are already in its Google Sheet.",
  gmail_search: "Finds emails in your Gmail.",
  gmail_read: "Reads one Gmail email.",
  gmail_create_draft: "Writes a reply and saves it as a draft. Nothing is sent.",
  gmail_send: "Sends an email from your Gmail. This cannot be undone.",
  google_calendar_list: "Looks at your Google Calendar.",
  google_calendar_create: "Adds an event to your Google Calendar.",
  google_drive_search: "Finds files in your Google Drive.",
  google_drive_read: "Reads a file in your Google Drive.",
  outlook_search: "Finds emails in Outlook.",
  outlook_read: "Reads one Outlook email.",
  outlook_create_draft: "Saves an Outlook draft. Nothing is sent.",
  outlook_send: "Sends an Outlook email. This cannot be undone.",
  outlook_calendar_list: "Looks at your Outlook calendar.",
  outlook_calendar_create: "Adds an event to your Outlook calendar.",
  onedrive_search: "Finds files in OneDrive.",
  onedrive_read: "Reads a file in OneDrive.",
  list_emails: "Lists emails in a connected mailbox.",
  read_email: "Reads one email in a connected mailbox.",
  save_draft: "Saves a reply as a draft for you to review.",
  send_email: "Sends an email. This cannot be undone.",
  list_tables: "Shows which tables a connected database has.",
  describe_table: "Shows the columns of one table.",
  run_query: "Looks up data in the database. It can only read.",
  github_list_repos: "Lists your GitHub repositories.",
  github_search_code: "Searches code on GitHub.",
  github_read_file: "Reads a file in a repository.",
  github_list_issues: "Lists issues and pull requests.",
  github_read_issue: "Reads one issue or pull request.",
  github_pr_diff: "Reads the changes in a pull request.",
  github_list_commits: "Lists recent commits.",
  github_ci_status: "Checks whether tests and builds passed.",
  github_comment: "Posts a comment on an issue or pull request.",
  github_create_issue: "Opens a new GitHub issue.",
  github_propose_change: "Opens a pull request with a code change. It never edits the main branch.",
  ask_specialist: "Hands part of a job to a helper.",
};

export function toolBlurb(name: string, description: string): string {
  const known = TOOL_BLURBS[name];
  if (known) return known;
  const first = description.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s/)[0] ?? "";
  return first.length > 140 ? `${first.slice(0, 139)}…` : first;
}

/** The order people think in: everyday helpers first, then each app. */
const GROUP_ORDER = [
  "clock",
  "calculator",
  "text",
  "python_run",
  "report",
  "search",
  "web",
  "memory",
  "sheets",
  "google",
  "microsoft",
  "excel",
  "chat",
  "email",
  "github",
  "database",
];

export function packOrder(pack: string): number {
  const i = GROUP_ORDER.indexOf(pack);
  return i === -1 ? GROUP_ORDER.length : i;
}

/** Packs shown together under one heading. */
const GROUP_OF: Record<string, string> = {
  clock: "basics",
  calculator: "basics",
  text: "basics",
  python_run: "basics",
  report: "basics",
  search: "web",
  web: "web",
};

const GROUP_TITLES: Record<string, string> = {
  basics: "Everyday helpers",
  web: "The web",
};

export function groupKey(pack: string): string {
  return GROUP_OF[pack] ?? pack;
}

export function groupTitle(key: string): string {
  return GROUP_TITLES[key] ?? packLabel(key);
}

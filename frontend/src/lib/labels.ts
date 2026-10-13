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
  delegate_to_specialist: "Ask another AI Employee",
};

export function humanise(id: string): string {
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

export const PACK_LABELS: Record<string, string> = {
  google: "Google Workspace",
  microsoft: "Microsoft 365",
  email: "Mailbox (IMAP)",
  database: "Database",
  web: "Web",
  memory: "Memory",
  delegation: "Teamwork",
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

export function effectTone(effect: string): "ok" | "brand" | "bad" {
  return EFFECTS[effect as Effect]?.tone ?? "brand";
}

const PROVIDER_NAMES: Record<string, string> = {
  gemini: "Gemini",
  groq: "Groq",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
  openai: "OpenAI",
};

/** "auto" (and the old "gemini-flash") means: whichever AI is connected. */
export function isAutoModel(model: string): boolean {
  return ["auto", "gemini-flash", ""].includes(model.trim());
}

export function modelLabel(model: string): string {
  if (isAutoModel(model)) return "Automatic AI";
  const [provider, name] = model.includes(":") ? model.split(/:(.*)/s) : ["gemini", model];
  return `${PROVIDER_NAMES[provider] ?? humanise(provider)} · ${name}`;
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

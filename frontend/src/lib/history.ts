import type { HistoryItem, HistoryModel } from "./api";

/** How a run began, in the words used on screen. */
export const STARTED_BY: Record<HistoryItem["trigger"], string> = {
  schedule: "Schedule",
  manual: "Run now",
  chat: "Chat",
};

/** "Time" choices for the filter bar; `days` is how far back to look. */
export const RANGES: { value: string; label: string; days: number | null }[] = [
  { value: "1", label: "Last 24 hours", days: 1 },
  { value: "7", label: "Last 7 days", days: 7 },
  { value: "30", label: "Last 30 days", days: 30 },
  { value: "all", label: "Any time", days: null },
];

export const STATUS_CHOICES: { value: string; label: string }[] = [
  { value: "", label: "Any status" },
  { value: "completed", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "awaiting_approval", label: "Needs approval" },
  { value: "running", label: "Running" },
  { value: "cancelled", label: "Stopped" },
];

const STATUS_WORDS: Record<string, string> = Object.fromEntries(
  STATUS_CHOICES.filter((s) => s.value).map((s) => [s.value, s.label]),
);

export function statusWords(status: string): string {
  return STATUS_WORDS[status] ?? status.replace(/_/g, " ");
}

/** "2m 40s", "48s", "1h 5m". */
export function fmtDuration(seconds: number | null): string {
  if (seconds === null) return "not started";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** "gemini-2.0-flash" reads fine; "openai/gpt-oss-120b" loses its prefix. */
export function modelName(model: string): string {
  return model.includes("/") ? (model.split("/").pop() ?? model) : model;
}

export function planWords(plan: HistoryModel["plan"]): string {
  return plan === "free" ? "Free" : plan === "paid" ? "Paid" : "Price unknown";
}

/** The model line in a row: the first model, and how many more. */
export function modelsLine(models: HistoryModel[]): string {
  if (models.length === 0) return "no model";
  const first = modelName(models[0].model);
  return models.length > 1 ? `${first} +${models.length - 1}` : first;
}

export function sinceFor(days: number | null): string | undefined {
  return days === null ? undefined : new Date(Date.now() - days * 86_400_000).toISOString();
}

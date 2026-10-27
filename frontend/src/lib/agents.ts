import type { AgentSchedule } from "./api";

/** "$0.0042", or "under $0.0001" for a very small spend. Always an estimate. */
export function fmtCost(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n) || n === 0) return "$0";
  if (n < 0.0001) return "under $0.0001";
  return `$${n < 0.01 ? n.toFixed(4) : n.toFixed(3)}`;
}

export function fmtTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

// ---------------------------------------------------------------- schedule

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** The person's own time zone, or India Standard Time when it cannot be read. */
export function localZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
}

export function defaultSchedule(): AgentSchedule {
  return { frequency: "daily", time: "23:30", days: [], timezone: localZone() };
}

/** "Every day at 11:30 PM (Asia/Kolkata)". */
export function describeSchedule(s: AgentSchedule): string {
  const [h, m] = s.time.split(":").map(Number);
  const clock = `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
  let when = "Every day";
  if (s.frequency === "weekdays") when = "Monday to Friday";
  if (s.frequency === "weekly") {
    const names = s.days.map((d) => WEEKDAYS[d]);
    when = "Every " + (names.length <= 1 ? (names[0] ?? "week") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);
  }
  return `${when} at ${clock} (${s.timezone})`;
}

/** Where a failed readiness check sends the person. */
export function fixTarget(fix: string | null): { to: string; label: string } | null {
  if (!fix) return null;
  const [kind, app] = fix.split(":");
  const name = app === "microsoft" ? "Microsoft 365" : "Google";
  if (kind === "connect") return { to: "/connections", label: `Connect ${name}` };
  if (kind === "reconnect") return { to: "/connections", label: `Reconnect ${name}` };
  if (kind === "permissions") return { to: "/policies", label: "Open Permissions" };
  return null;
}

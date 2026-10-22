import type { AgentSchedule, RunEvent } from "./api";

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

export function fmtMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export interface FlowStep {
  /** Milliseconds from the start of the run. */
  at: number;
  label: string;
  kind: "think" | "tool" | "blocked";
  ok?: boolean;
}

export interface FlowLane {
  id: string;
  label: string;
  kind: "lead" | "specialist";
  start: number;
  end: number;
  steps: FlowStep[];
  model: string | null;
  promptTokens: number | null;
  outputTokens: number | null;
  /** Estimated; null where the run predates per-specialist cost. */
  cost: number | null;
  ok: boolean | null;
}

export interface Flow {
  lanes: FlowLane[];
  duration: number;
}

type Timed = RunEvent & { at?: string };

/**
 * Turns a run's event log into lanes: one for the assistant and one per
 * specialist it asked, each with its own span of time, steps and cost.
 * That is the view "who did what, and what did it cost", which is a
 * different question from the route diagram in Chat ("where did this
 * request go"), so it is drawn from the same log but laid out by time.
 */
export function deriveFlow(events: RunEvent[], totalCost: number, labelFor: (tool: string) => string): Flow {
  const timed = events as Timed[];
  const times = timed.map((e) => (e.at ? Date.parse(e.at) : NaN)).filter((t) => Number.isFinite(t));
  if (times.length === 0) return { lanes: [], duration: 0 };
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const rel = (e: Timed) => (e.at ? Math.max(0, Date.parse(e.at) - t0) : 0);
  const duration = Math.max(t1 - t0, 1);

  const lead: FlowLane = {
    id: "lead",
    label: "Assistant",
    kind: "lead",
    start: 0,
    end: duration,
    steps: [],
    model: null,
    promptTokens: 0,
    outputTokens: 0,
    cost: null,
    ok: null,
  };
  const specialists = new Map<string, FlowLane>();

  for (const e of timed) {
    const str = (k: string) => (typeof e[k] === "string" ? (e[k] as string) : null);
    const num = (k: string) => (typeof e[k] === "number" ? (e[k] as number) : null);
    switch (e.type) {
      case "model_chosen":
        lead.model = str("model");
        break;
      case "llm_call":
        lead.promptTokens = (lead.promptTokens ?? 0) + (num("prompt_tokens") ?? 0);
        lead.outputTokens = (lead.outputTokens ?? 0) + (num("output_tokens") ?? 0);
        lead.steps.push({ at: rel(e), label: "Thinks", kind: "think" });
        break;
      case "tool_call": {
        const tool = str("tool");
        if (tool && tool !== "ask_specialist") {
          lead.steps.push({ at: rel(e), label: labelFor(tool), kind: "tool" });
        }
        break;
      }
      case "tool_blocked":
        lead.steps.push({ at: rel(e), label: labelFor(str("tool") ?? "tool"), kind: "blocked", ok: false });
        break;
      case "specialist_started": {
        const id = str("id") ?? `s${specialists.size + 1}`;
        specialists.set(id, {
          id,
          label: humanRole(str("role")),
          kind: "specialist",
          start: rel(e),
          end: duration,
          steps: [],
          model: str("model"),
          promptTokens: null,
          outputTokens: null,
          cost: null,
          ok: null,
        });
        break;
      }
      case "specialist_step": {
        const lane = specialists.get(str("id") ?? "");
        const tool = str("tool");
        if (lane && str("kind") === "tool_call" && tool) {
          lane.steps.push({ at: rel(e), label: labelFor(tool), kind: "tool" });
        }
        break;
      }
      case "specialist_finished": {
        const lane = specialists.get(str("id") ?? "");
        if (lane) {
          lane.end = rel(e);
          lane.ok = e.ok === true;
          lane.promptTokens = num("prompt_tokens");
          lane.outputTokens = num("output_tokens");
          lane.cost = num("cost_usd");
        }
        break;
      }
    }
  }

  const spent = [...specialists.values()].reduce((sum, l) => sum + (l.cost ?? 0), 0);
  lead.cost = Math.max(totalCost - spent, 0);
  return { lanes: [lead, ...specialists.values()], duration };
}

function humanRole(role: string | null): string {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : "Specialist";
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

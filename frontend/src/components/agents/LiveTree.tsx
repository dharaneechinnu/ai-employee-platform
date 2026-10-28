import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { agentLook } from "../../lib/agentIcons";
import { api, ApiError, type Agent, type AgentsOverview, type Approval, type RunNowResult } from "../../lib/api";
import { LEAD, useLiveTree, type NodeLive } from "../../lib/liveTree";
import { toolLabel } from "../../lib/labels";
import { Icon } from "../icons";
import { Button, Spinner, relativeTime, useToast } from "../ui";
import AgentAvatar from "./AgentAvatar";
import AgentTreeGraph from "./AgentTreeGraph";
import RunPanel, { type PanelNode } from "./RunPanel";

const W = 220;
const H = 64;
const ROW = 72;
const COL_A = 0;
const COL_B = 290;
const COL_C = 640;
const CANVAS_W = 1000;
const LABEL = 28;

interface Slot extends PanelNode {
  x: number;
  y: number;
  /** What to say when it is idle. */
  idleNote: string;
}

const STATE_WORDS: Record<string, string> = {
  working: "Working",
  waiting: "Waiting for you",
  failed: "Needs attention",
  done: "Finished",
};

/**
 * Every agent as its own node, live.
 *
 * The Scheduler is at the top and starts the agents that have a time.
 * You and your assistant are below, with the built-in helpers fanning
 * out to the right. Lines move while work moves along them, tool chips
 * pop in on the line as each tool is used, and the panel on the right
 * steps through whichever run you pick. It is driven by one stream for
 * the whole account (see `useLiveTree`).
 */
export default function LiveTree({
  overview,
  onChanged,
}: {
  overview: AgentsOverview;
  /** Something happened that the Agents tab should reload for. */
  onChanged: () => void;
}) {
  const toast = useToast();
  const { ready, nodes, tree, live, failed, reload } = useLiveTree();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canvas = useRef<HTMLDivElement>(null);
  const { agents } = overview;

  // Esc closes the panel, unless a dialog owns the keyboard.
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key !== "Escape" || document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      setSelected(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { slots, height, lines, splitY } = useMemo(() => layout(agents, tree?.helpers ?? []), [agents, tree?.helpers]);

  const stateOf = (id: string): NodeLive | undefined => nodes[id];
  const anyLive = Object.values(nodes).some((n) => n.state === "working" || n.state === "waiting");

  // The scheduler's own look comes from the agents it is starting.
  const startingNow = agents.find((a) => {
    const phase = nodes[a.id]?.phase;
    return phase === "due" || phase === "ready" || phase === "starting";
  });
  const blocked = agents.find((a) => nodes[a.id]?.phase === "blocked");

  const run = useCallback(
    async (agent: Agent) => {
      setBusy(true);
      try {
        const result = await api.post<RunNowResult>(`/me/agents/${agent.id}/run`);
        toast(
          result.status === "started"
            ? `${agent.name} is starting.`
            : result.message || "It could not start just now.",
        );
        setSelected(agent.id);
        onChanged();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Could not start it.");
      } finally {
        setBusy(false);
      }
    },
    [onChanged, toast],
  );

  const stop = useCallback(
    async (taskId: string) => {
      try {
        await api.post(`/me/tasks/${taskId}/cancel`);
        toast("Stopping. It will finish its current step first.");
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Could not stop it.");
      }
    },
    [toast],
  );

  const approve = useCallback(
    async (id: string) => {
      const runId = nodes[id]?.runId;
      try {
        const all = await api.get<Approval[]>("/me/approvals");
        const mine = all.find((a) => a.run_id === runId);
        if (!mine) return toast("Nothing is waiting for you here any more.");
        await api.post(`/me/approvals/${mine.id}/approve`);
        toast("Approved. It carries on.");
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Could not approve it.");
      }
    },
    [nodes, toast],
  );

  // Arrow keys move between nodes by where they sit; Enter opens one.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    const here = (e.target as HTMLElement).closest<HTMLElement>("[data-node]")?.dataset.node;
    const from = slots.find((s) => s.id === here);
    if (!dir || !from) return;
    const [dx, dy] = dir;
    let best: Slot | null = null;
    let bestScore = Infinity;
    for (const s of slots) {
      const mx = (s.x - from.x) * dx;
      const my = (s.y - from.y) * dy;
      if (s.id === from.id || mx < 0 || my < 0 || mx + my === 0) continue;
      const across = dx ? Math.abs(s.y - from.y) : Math.abs(s.x - from.x);
      const score = mx + my + across * 2;
      if (score < bestScore) [best, bestScore] = [s, score];
    }
    if (best) {
      e.preventDefault();
      canvas.current?.querySelector<HTMLElement>(`[data-node="${best.id}"] button.tnode`)?.focus();
    }
  }

  if (failed) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-[14px] text-muted">Could not load the live view.</p>
        <Button size="sm" variant="ghost" icon="refresh" onClick={reload}>
          Try again
        </Button>
      </div>
    );
  }
  if (!ready) return <Spinner rows={4} />;

  const panelSlot = slots.find((s) => s.id === selected) ?? null;
  const panelNode: PanelNode | null = panelSlot;
  const panelLive: NodeLive | null = panelSlot ? (nodes[panelSlot.id] ?? null) : null;

  const showGraph = panelSlot && (panelSlot.kind === "agent" || panelSlot.kind === "lead" || panelSlot.kind === "helper");

  return (
    <div className="flex flex-col gap-4">
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
          <Key tone="var(--ok)" label="Working" />
          <Key tone="var(--ask)" label="Waiting for you" />
          <Key tone="var(--bad)" label="Failed" />
          <Key tone="var(--line2)" label="Idle" />
          <span className="ml-auto flex items-center gap-1.5" aria-live="polite">
            <i
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: live ? "var(--ok)" : "var(--ask)" }}
              aria-hidden="true"
            />
            {live ? "Live" : "Reconnecting…"}
          </span>
          <span className="max-lg:hidden">Arrow keys move between agents. Enter opens one.</span>
        </div>

        <div className="overflow-x-auto rounded-2xl border border-line bg-panel p-5">
          <div
            ref={canvas}
            className="relative"
            style={{ width: CANVAS_W, height }}
            onKeyDown={onKeyDown}
            role="group"
            aria-label="Your agents and how work moves between them"
          >
            <svg className="absolute inset-0" width={CANVAS_W} height={height} aria-hidden="true">
              {lines.map((l) => {
                const target = nodes[l.to];
                return (
                  <path
                    key={l.id}
                    d={l.d}
                    className={`tline ${lineClass(l, target)}`}
                  />
                );
              })}
            </svg>

            <span className="absolute text-[12px] font-semibold uppercase tracking-[0.08em] text-dim" style={{ left: COL_A, top: 0 }}>
              Your agents
            </span>
            <span
              className="absolute text-[12px] font-semibold uppercase tracking-[0.08em] text-dim"
              style={{ left: COL_A, top: splitY }}
            >
              Your assistant and its helpers
            </span>

            {slots.map((slot) => (
              <Node
                key={slot.id}
                slot={slot}
                live={stateOf(slot.id)}
                selected={selected === slot.id}
                onSelect={() => setSelected((cur) => (cur === slot.id ? null : slot.id))}
                onApprove={() => void approve(slot.id)}
                scheduler={
                  slot.id === "scheduler"
                    ? {
                        at: tree?.scheduler.next_run_at ?? null,
                        name: tree?.scheduler.next_agent_name ?? null,
                        starting: startingNow?.name ?? null,
                        blocked: blocked?.name ?? null,
                      }
                    : null
                }
              />
            ))}

            {slots.map((slot) => (
              <Chips key={slot.id} slot={slot} live={stateOf(slot.id)} />
            ))}
          </div>
        </div>

        {!anyLive && (
          <p className="text-[14px] text-dim">
            {agents.length === 0
              ? "You have no agents yet. Describe one in Chat and it appears here, next to the built-in helpers."
              : "Nothing is running right now. When an agent starts, its lines light up here."}
          </p>
        )}
      </div>

      <RunPanel
        node={panelNode}
        live={panelLive}
        agents={agents}
        runs={overview.recent_runs}
        busy={busy}
        onClose={() => setSelected(null)}
        onRunNow={(a) => void run(a)}
        onStop={(id) => void stop(id)}
        onApprove={(id) => void approve(id)}
      />
    </div>
    {showGraph ? (
      <AgentTreeGraph node={panelSlot} live={panelLive} agents={agents} />
    ) : (
      <p className="text-[14px] text-dim">Click any agent or helper to see its tree: what starts it, what it does and what you get.</p>
    )}
    </div>
  );
}

// ---------------------------------------------------------------- layout

interface Line {
  id: string;
  from: string;
  to: string;
  d: string;
  /** "you" lines are the person's own way in. */
  kind: "schedule" | "you" | "lead" | "helper" | "mention";
}

const curve = (x1: number, y1: number, x2: number, y2: number) => {
  const m = (x1 + x2) / 2;
  return `M${x1} ${y1} C${m} ${y1}, ${m} ${y2}, ${x2} ${y2}`;
};

function layout(agents: Agent[], helpers: { key: string; label: string }[]) {
  const slots: Slot[] = [];
  const lines: Line[] = [];

  const scheduledRows = Math.max(agents.length, 1);
  const top1 = LABEL;
  const top2 = top1 + scheduledRows * ROW + 24 + LABEL;
  const helpersBlock = Math.max(helpers.length, 1) * ROW - (ROW - H);
  const leadY = top2 + (helpersBlock - H) / 2;
  const height = top2 + helpersBlock + 24;

  slots.push({
    id: "scheduler",
    name: "Scheduler",
    kind: "scheduler",
    role: "scheduler",
    icon: "clock",
    tone: "var(--run)",
    agent: null,
    x: COL_A,
    y: top1,
    idleNote: "Nothing scheduled",
  });
  slots.push({
    id: "you",
    name: "You",
    kind: "you",
    role: "you",
    icon: "people",
    tone: "var(--accent)",
    agent: null,
    x: COL_A,
    y: leadY,
    idleNote: "Chat or @mention",
  });
  const lead = agentLook("lead");
  slots.push({
    id: LEAD,
    name: lead.label,
    kind: "lead",
    role: "lead",
    icon: lead.icon,
    tone: lead.tone,
    agent: null,
    x: COL_B,
    y: leadY,
    idleNote: "Ready when you are",
  });
  lines.push({ id: "you-lead", from: "you", to: LEAD, kind: "you", d: curve(COL_A + W, leadY + H / 2, COL_B, leadY + H / 2) });

  agents.forEach((a, i) => {
    const look = agentLook(null);
    const y = top1 + i * ROW;
    slots.push({
      id: a.id,
      name: a.name,
      kind: "agent",
      role: "agent",
      icon: look.icon,
      tone: look.tone,
      agent: a,
      x: COL_B,
      y,
      idleNote: a.schedule_enabled && a.next_run_at ? `Next run ${relativeTime(a.next_run_at)}` : "Runs when you ask",
    });
    // A scheduled agent hangs off the Scheduler; any other is reached by you.
    const scheduled = a.schedule_enabled && !!a.next_run_at;
    lines.push(
      scheduled
        ? { id: `s-${a.id}`, from: "scheduler", to: a.id, kind: "schedule", d: curve(COL_A + W, top1 + H / 2, COL_B, y + H / 2) }
        : { id: `m-${a.id}`, from: "you", to: a.id, kind: "mention", d: curve(COL_A + W, leadY + H / 2, COL_B, y + H / 2) },
    );
  });

  helpers.forEach((h, i) => {
    const look = agentLook(h.key);
    const y = top2 + i * ROW;
    slots.push({
      id: h.key,
      name: h.label,
      kind: "helper",
      role: h.key,
      icon: look.icon,
      tone: look.tone,
      agent: null,
      x: COL_C,
      y,
      idleNote: "Idle",
    });
    lines.push({ id: `h-${h.key}`, from: LEAD, to: h.key, kind: "helper", d: curve(COL_B + W, leadY + H / 2, COL_C, y + H / 2) });
  });

  return { slots, lines, height, splitY: top2 - LABEL };
}

function lineClass(line: Line, target: NodeLive | undefined): string {
  const phase = target?.phase;
  if (phase === "blocked") return "is-bad";
  if (line.kind === "schedule" && (phase === "due" || phase === "ready" || phase === "starting")) return "is-on dash-flow";
  if (target?.state === "working") return "is-on dash-flow";
  if (target?.state === "waiting") return "is-wait";
  if (target?.state === "failed") return "is-bad";
  if (line.kind === "you") return "is-you";
  return "is-quiet";
}

// ------------------------------------------------------------------ nodes

function Key({ tone, label }: { tone: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: tone }} aria-hidden="true" />
      {label}
    </span>
  );
}

function Node({
  slot,
  live,
  selected,
  onSelect,
  onApprove,
  scheduler,
}: {
  slot: Slot;
  live: NodeLive | undefined;
  selected: boolean;
  onSelect: () => void;
  onApprove: () => void;
  scheduler: { at: string | null; name: string | null; starting: string | null; blocked: string | null } | null;
}) {
  let state = live?.state ?? "idle";
  let note = live?.note || slot.idleNote;
  if (scheduler) {
    state = scheduler.blocked ? "failed" : scheduler.starting ? "working" : "idle";
    note = scheduler.blocked
      ? `Could not start ${scheduler.blocked}`
      : scheduler.starting
        ? `Starting ${scheduler.starting}`
        : "";
  } else if (live && (state === "working" || state === "waiting") && live.model) {
    note = `${live.model} · ${note}`;
  } else if (state === "idle" && live?.phase === "skipped") {
    note = live.note;
  }
  const word = STATE_WORDS[state];

  return (
    <div className="tn-slot" style={{ left: slot.x, top: slot.y }} data-node={slot.id}>
      <button
        type="button"
        className={`tnode ${slot.kind === "you" ? "is-you" : ""} ${slot.kind === "lead" ? "is-lead" : ""}`}
        data-state={state}
        aria-pressed={selected}
        aria-label={`${slot.name}: ${word ?? "idle"}`}
        onClick={onSelect}
      >
        <span className="tn-ic" style={{ ["--tone" as string]: slot.tone }}>
          {(state === "working" || state === "waiting") && <span className="tn-ring" aria-hidden="true" />}
          {scheduler && <Countdown at={scheduler.at} />}
          <AgentAvatar role={slot.role} size={22} />
        </span>
        <span className="min-w-0 flex-1">
          <b>{slot.name}</b>
          <small>
            {scheduler && !note ? <SchedulerNote at={scheduler.at} name={scheduler.name} /> : note}
            {word && state !== "working" && state !== "waiting" ? ` · ${word}` : ""}
          </small>
        </span>
      </button>
      {state === "waiting" && (
        <button type="button" className="btn btn-sm btn-ok tnode-ask" onClick={onApprove}>
          Approve
        </button>
      )}
    </div>
  );
}

/** A ring around the Scheduler's icon that fills over the last hour before the next start. */
function Countdown({ at }: { at: string | null }) {
  const left = useRemaining(at);
  if (left === null || left > 3600_000) return null;
  const fill = 1 - Math.max(left, 0) / 3600_000;
  const c = 2 * Math.PI * 19;
  return (
    <svg className="absolute -inset-[5px]" width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
      <circle cx="23" cy="23" r="19" fill="none" stroke="var(--line2)" strokeWidth="2" />
      <circle
        cx="23"
        cy="23"
        r="19"
        fill="none"
        stroke="var(--run)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeDasharray={`${c * fill} ${c}`}
        transform="rotate(-90 23 23)"
      />
    </svg>
  );
}

function SchedulerNote({ at, name }: { at: string | null; name: string | null }) {
  const left = useRemaining(at);
  if (left === null) return <>Nothing scheduled</>;
  return <>{left <= 0 ? "Due now" : `Next in ${countdown(left)}`}{name ? ` · ${name}` : ""}</>;
}

function useRemaining(at: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!at) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [at]);
  return at ? Date.parse(at) - now : null;
}

function countdown(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h >= 1) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** The tools in use, popping in along the line as each one is called. */
function Chips({ slot, live }: { slot: Slot; live: NodeLive | undefined }) {
  if (!live || (live.state !== "working" && live.state !== "waiting" && live.state !== "done")) return null;
  const tools = live.story.filter((s) => s.kind === "tool").slice(-2);
  if (tools.length === 0) return null;

  // An agent or helper shows them to its right, along its line; the
  // assistant shows them underneath, where there is room.
  const place = (i: number) =>
    slot.kind === "lead"
      ? { left: slot.x, top: slot.y + H + 10 + i * 32 }
      : { left: slot.kind === "helper" ? slot.x + W + 10 : slot.x + W + 24, top: slot.y + 4 + i * 32 };

  return (
    <>
      {tools.map((t, i) => (
        <span
          key={t.id}
          className={`tchip chip-pop ${t.state === "done" ? "is-done" : t.state === "failed" ? "is-failed" : ""}`}
          style={place(i)}
          title={toolLabel(t.tool ?? "")}
        >
          <Icon name={t.state === "done" ? "check" : t.state === "failed" ? "x" : "zap"} size={13} strokeWidth={2.2} />
          <span className="truncate">{t.title}</span>
          <span className="sr-only">{t.state === "now" ? " (in progress)" : t.state === "failed" ? " (did not work)" : " (done)"}</span>
        </span>
      ))}
    </>
  );
}

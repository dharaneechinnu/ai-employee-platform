import { useEffect, useReducer, useState } from "react";
import { api, streamAccount, type AgentsTree, type LiveEvent, type TreeState } from "./api";
import { toolLabel } from "./labels";

/**
 * What the agent tree knows about each node, kept up to date from the
 * account's one live stream.
 *
 * A node is the assistant ("lead"), a saved agent (its id) or one of the
 * built-in helpers (the role name, which never changes). Everything
 * here is plain data so the tree and its side panel read from one place.
 */

/** "idle" again some while after a run ends, so a finished node does not glow for ever. */
const DONE_FOR_MS = 45_000;
const MAX_STORY = 40;

type NodeState = TreeState | "done";
/** Where a scheduled start has got to. */
type Phase = "due" | "ready" | "blocked" | "starting" | "skipped" | null;

export interface StoryItem {
  id: string;
  kind: "step" | "tool";
  title: string;
  detail?: string;
  state: "done" | "now" | "failed";
  /** The tool's name, for the chip on the line. */
  tool?: string;
}

export interface NodeLive {
  state: NodeState;
  phase: Phase;
  /** One line under the name while something is happening. */
  note: string;
  model: string | null;
  story: StoryItem[];
  runId: string | null;
  taskId: string | null;
  llmCalls: number;
  tokens: number;
  /** "the scheduler", "you" or "chat". */
  trigger: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  /** Plain words about what went wrong. */
  problem: string | null;
  waitingFor: string | null;
}

interface LiveTreeState {
  ready: boolean;
  nodes: Record<string, NodeLive>;
  tree: AgentsTree | null;
}

const blank = (): NodeLive => ({
  state: "idle",
  phase: null,
  note: "",
  model: null,
  story: [],
  runId: null,
  taskId: null,
  llmCalls: 0,
  tokens: 0,
  trigger: null,
  startedAt: null,
  finishedAt: null,
  problem: null,
  waitingFor: null,
});

export const LEAD = "lead";

type Action =
  | { kind: "snapshot"; tree: AgentsTree }
  | { kind: "event"; event: LiveEvent }
  | { kind: "tick"; now: number };

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number => (typeof v === "number" ? v : 0);

function put(story: StoryItem[], item: StoryItem): StoryItem[] {
  return [...story.filter((s) => s.id !== item.id), item].slice(-MAX_STORY);
}

/** Marks the step in progress as finished, so only one is ever "now". */
function settle(story: StoryItem[], to: "done" | "failed" = "done"): StoryItem[] {
  return story.map((s) => (s.state === "now" ? { ...s, state: to } : s));
}

function clock(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Who a run-level event belongs to: its agent, or the assistant. */
const owner = (e: LiveEvent) => e.agent_id ?? LEAD;

function reduceEvent(state: LiveTreeState, e: LiveEvent): LiveTreeState {
  const nodes = { ...state.nodes };
  const get = (id: string): NodeLive => nodes[id] ?? blank();
  const set = (id: string, patch: Partial<NodeLive>) => {
    nodes[id] = { ...get(id), ...patch };
  };
  const at = Date.parse(e.at) || Date.now();
  const id = owner(e);
  const n = get(id);
  const key = `${e.type}-${e.seq ?? e.at}`;

  switch (e.type) {
    // ------------------------------------------------ the scheduler's steps
    case "agent_due":
      set(id, {
        ...blank(),
        phase: "due",
        trigger: "the scheduler",
        note: "Time reached",
        taskId: null,
        story: [
          {
            id: "due",
            kind: "step",
            title: "Time reached",
            detail: clock(str(e.scheduled_for)) || undefined,
            state: "done",
          },
        ],
      });
      break;

    case "connections_checked": {
      const ok = e.ok !== false;
      // Part of a scheduled start that began with "due"; otherwise a start
      // of its own (Run now), which begins a fresh story.
      const scheduled = n.phase === "due";
      set(id, {
        ...(scheduled ? n : blank()),
        trigger: scheduled ? n.trigger : "you",
        phase: ok ? "ready" : "blocked",
        note: ok ? "Checked its connections" : "A connection is broken",
        problem: ok ? null : str(e.message),
        state: ok ? "idle" : "failed",
        story: put(scheduled ? n.story : [], ok
          ? { id: "checked", kind: "step", title: "Connections checked", detail: "All working", state: "done" }
          : {
              id: "checked",
              kind: "step",
              title: "A connection needs fixing",
              detail: str(e.message) ?? undefined,
              state: "failed",
            }),
      });
      break;
    }

    case "agent_started":
      set(id, {
        phase: "starting",
        trigger: n.trigger ?? (e.trigger === "schedule" ? "the scheduler" : "you"),
        taskId: e.task_id,
        state: "working",
        note: "Starting",
        startedAt: at,
        finishedAt: null,
        story: put(n.story, { id: "running", kind: "step", title: "Running", state: "now" }),
      });
      break;

    case "agent_skipped":
      set(id, {
        phase: "skipped",
        note: "Skipped this time",
        problem: str(e.message),
        story: put(n.story, {
          id: "skipped",
          kind: "step",
          title: "Skipped this time",
          detail: str(e.message) ?? undefined,
          state: "failed",
        }),
      });
      break;

    // ---------------------------------------------------------- a run
    case "run_started": {
      const same = n.taskId !== null && n.taskId === e.task_id;
      set(id, {
        ...(same ? n : blank()),
        model: n.model,
        state: "working",
        phase: null,
        runId: e.run_id,
        taskId: e.task_id,
        trigger: same ? n.trigger : "chat",
        startedAt: same && n.startedAt ? n.startedAt : at,
        finishedAt: null,
        problem: null,
        note: "Getting started",
        story: same
          ? put(n.story, { id: "running", kind: "step", title: "Running", state: "now" })
          : [{ id: "running", kind: "step", title: "Working on your request", state: "now" }],
      });
      break;
    }

    case "model_chosen":
      // Written before the run starts, so a run keeps it (see run_started).
      set(id, { model: str(e.name) ?? str(e.model) ?? n.model });
      break;

    case "llm_call":
      set(id, {
        model: n.model ?? str(e.model),
        llmCalls: n.llmCalls + 1,
        tokens: n.tokens + num(e.prompt_tokens) + num(e.output_tokens),
      });
      break;

    case "thinking":
      set(id, { note: "Thinking it through" });
      break;

    case "tool_call": {
      const tool = str(e.tool);
      if (!tool || tool === "ask_specialist") break;
      set(id, {
        note: `${toolLabel(tool)}…`,
        story: put(n.story, { id: key, kind: "tool", title: toolLabel(tool), state: "now", tool }),
      });
      break;
    }

    case "tool_result":
    case "tool_blocked": {
      const tool = str(e.tool);
      if (!tool || tool === "ask_specialist") break;
      const failed = e.type === "tool_blocked" || e.ok === false;
      // The latest still-open step for this tool is the one that just finished.
      const open = [...n.story].reverse().find((s) => s.tool === tool && s.state === "now");
      set(id, {
        story: open
          ? n.story.map((s) =>
              s.id === open.id
                ? { ...s, state: failed ? "failed" : "done", detail: failed ? "Did not work" : undefined }
                : s,
            )
          : n.story,
      });
      break;
    }

    case "approval_requested": {
      const tool = str(e.tool);
      set(id, {
        state: "waiting",
        waitingFor: tool,
        note: tool ? `Needs your OK: ${toolLabel(tool).toLowerCase()}` : "Needs your OK",
        story: put(settle(n.story), {
          id: "approval",
          kind: "step",
          title: "Waiting for you",
          detail: tool ? toolLabel(tool) : undefined,
          state: "now",
        }),
      });
      break;
    }

    case "approval_granted":
      set(id, {
        state: "working",
        waitingFor: null,
        note: "Carrying on",
        story: settle(n.story.filter((s) => s.id !== "approval")),
      });
      break;

    case "run_finished":
      set(id, {
        state: "done",
        phase: null,
        note: "Finished",
        waitingFor: null,
        finishedAt: at,
        story: put(settle(n.story), { id: "finished", kind: "step", title: "Finished", state: "done" }),
      });
      break;

    case "run_stopped": {
      const cause = str(e.cause);
      const calm = cause === "cancelled";
      set(id, {
        state: calm ? "idle" : "failed",
        phase: null,
        note: calm ? "Stopped" : "Stopped early",
        waitingFor: null,
        finishedAt: at,
        problem: calm ? null : plainCause(cause),
        story: put(settle(n.story, "failed"), {
          id: "stopped",
          kind: "step",
          title: calm ? "Stopped" : "Stopped early",
          detail: calm ? undefined : (plainCause(cause) ?? undefined),
          state: calm ? "done" : "failed",
        }),
      });
      break;
    }

    case "provider_error":
      set(id, { note: "The AI had a problem, trying again" });
      break;

    // ------------------------------------------------ the built-in helpers
    case "specialist_started": {
      const role = str(e.role);
      if (!role) break;
      const h = get(role);
      nodes[role] = {
        ...blank(),
        state: "working",
        runId: e.run_id,
        taskId: e.task_id,
        model: str(e.model) ?? h.model,
        startedAt: at,
        trigger: "your assistant",
        note: "Working on its part",
        story: [{ id: "running", kind: "step", title: "Working on its part", detail: str(e.task) ?? undefined, state: "now" }],
      };
      break;
    }

    case "specialist_step": {
      const role = str(e.role);
      const tool = str(e.tool);
      if (!role) break;
      const h = get(role);
      if (e.kind === "tool_call" && tool) {
        nodes[role] = {
          ...h,
          state: "working",
          note: `${toolLabel(tool)}…`,
          story: put(h.story, { id: `${key}`, kind: "tool", title: toolLabel(tool), state: "now", tool }),
        };
      } else if ((e.kind === "tool_result" || e.kind === "tool_blocked") && tool) {
        const failed = e.kind === "tool_blocked" || e.ok === false;
        const open = [...h.story].reverse().find((s) => s.tool === tool && s.state === "now");
        nodes[role] = {
          ...h,
          story: h.story.map((s) => (s.id === open?.id ? { ...s, state: failed ? "failed" : "done" } : s)),
        };
      } else if (e.kind === "llm_call") {
        nodes[role] = { ...h, llmCalls: h.llmCalls + 1 };
      }
      break;
    }

    case "specialist_finished": {
      const role = str(e.role);
      if (!role) break;
      const h = get(role);
      const ok = e.ok !== false;
      nodes[role] = {
        ...h,
        state: ok ? "done" : "failed",
        note: ok ? "Finished its part" : "Could not finish",
        finishedAt: at,
        tokens: num(e.prompt_tokens) + num(e.output_tokens),
        problem: ok ? null : "It ran out of steps or time before it could finish.",
        story: put(settle(h.story, ok ? "done" : "failed"), {
          id: "finished",
          kind: "step",
          title: ok ? "Finished its part" : "Could not finish",
          state: ok ? "done" : "failed",
        }),
      };
      break;
    }

    default:
      return state;
  }
  return { ...state, nodes };
}

function plainCause(cause: string | null): string | null {
  switch (cause) {
    case "provider_not_connected":
      return "No AI is connected for this. Connect one under AI keys.";
    case "provider_key_unreadable":
      return "The saved AI key can no longer be read. Enter it again under AI keys.";
    case "max_steps":
      return "It used all its steps before finishing.";
    case "timeout":
    case "max_seconds":
      return "It ran out of time before finishing.";
    case "provider_error":
      return "The AI service kept failing.";
    default:
      return cause ? "It stopped before it finished." : null;
  }
}

function reduce(state: LiveTreeState, action: Action): LiveTreeState {
  switch (action.kind) {
    case "snapshot": {
      const { tree } = action;
      const nodes: Record<string, NodeLive> = {};
      const from = (s: TreeState, runId: string | null, taskId: string | null): NodeLive => ({
        ...blank(),
        state: s,
        runId,
        taskId,
        note: s === "working" ? "Working" : s === "waiting" ? "Needs your OK" : "",
      });
      nodes[LEAD] = from(tree.lead.state, tree.lead.active_run_id, tree.lead.active_task_id);
      for (const a of tree.agents) {
        nodes[a.id] = { ...from(a.state, a.active_run_id, a.active_task_id), problem: a.state === "failed" ? a.last_summary : null };
      }
      for (const h of tree.helpers) nodes[h.key] = blank();
      let next: LiveTreeState = { ready: true, nodes, tree };
      // Replay what the scheduler did in the last few minutes, so a tree
      // opened mid-start shows where that start has got to.
      for (const e of tree.recent_scheduler) next = reduceEvent(next, e);
      return next;
    }
    case "event":
      return reduceEvent(state, action.event);
    case "tick": {
      let changed = false;
      const nodes = { ...state.nodes };
      for (const [id, n] of Object.entries(nodes)) {
        if (n.state === "done" && n.finishedAt && action.now - n.finishedAt > DONE_FOR_MS) {
          nodes[id] = { ...n, state: "idle", note: "" };
          changed = true;
        }
      }
      return changed ? { ...state, nodes } : state;
    }
  }
}

/**
 * Loads the tree's starting picture, then keeps it live. `reload` asks
 * for a fresh picture (after Run now, say).
 */
export function useLiveTree() {
  const [state, dispatch] = useReducer(reduce, { ready: false, nodes: {}, tree: null });
  const [live, setLive] = useState(false);
  const [failed, setFailed] = useState(false);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let closed = false;
    let stop: (() => void) | null = null;
    void (async () => {
      try {
        const tree = await api.get<AgentsTree>("/me/agents/tree");
        if (closed) return;
        dispatch({ kind: "snapshot", tree });
        setFailed(false);
        // From the snapshot's own position, so nothing falls in the gap.
        stop = streamAccount((event) => dispatch({ kind: "event", event }), tree.cursor, setLive);
      } catch {
        if (!closed) setFailed(true);
      }
    })();
    return () => {
      closed = true;
      stop?.();
      setLive(false);
    };
  }, [round]);

  useEffect(() => {
    const timer = window.setInterval(() => dispatch({ kind: "tick", now: Date.now() }), 5000);
    return () => window.clearInterval(timer);
  }, []);

  return { ...state, live, failed, reload: () => setRound((r) => r + 1) };
}

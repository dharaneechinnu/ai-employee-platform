import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmtCost, fmtTokens } from "../../lib/agents";
import { api, type Agent, type AgentRunRow } from "../../lib/api";
import { toolLabel } from "../../lib/labels";
import type { NodeLive, StoryItem } from "../../lib/liveTree";
import { Icon, type IconName } from "../icons";
import { Button, StatusChip, relativeTime } from "../ui";
import AgentAvatar from "./AgentAvatar";
import AgentFlow from "./AgentFlow";

export interface PanelNode {
  id: string;
  name: string;
  icon: IconName;
  tone: string;
  kind: "scheduler" | "you" | "lead" | "agent" | "helper";
  /** Which picture and which way of working: a helper's key, or the kind. */
  role: string;
  agent: Agent | null;
}

const STATE_WORDS: Record<string, string> = {
  idle: "Idle",
  working: "Working",
  waiting: "Waiting for you",
  failed: "Needs attention",
  done: "Finished",
};

/**
 * The right-hand side of the tree: whatever is selected, and a live
 * step-by-step of its run. Steps arrive as the agent works, so the
 * panel reads like a short story: what has happened, what is happening.
 */
export default function RunPanel({
  node,
  live,
  agents,
  runs,
  busy,
  onClose,
  onRunNow,
  onStop,
  onApprove,
}: {
  node: PanelNode | null;
  live: NodeLive | null;
  agents: Agent[];
  runs: AgentRunRow[];
  busy: boolean;
  onClose: () => void;
  onRunNow: (agent: Agent) => void;
  onStop: (taskId: string) => void;
  onApprove: (id: string) => void;
}) {
  if (!node || !live) {
    return (
      <aside className="side-panel rounded-2xl border p-5 max-lg:hidden" aria-label="Run details">
        <p className="font-display text-[16px] font-semibold">Pick an agent</p>
        <p className="mt-1 text-[14px] text-muted">
          Choose any agent in the tree to see what it is doing right now, what it can use, and how its last runs went.
        </p>
      </aside>
    );
  }

  const running = live.state === "working" || live.state === "waiting";
  const hasStory = live.story.length > 0;

  return (
    <aside className="side-panel flex flex-col gap-4 rounded-2xl border p-5" aria-label="Run details" key={node.id}>
      <div className="flex items-start justify-between gap-3">
        <span
          className="flex h-12 w-12 flex-none items-center justify-center rounded-2xl"
          style={{ color: node.tone, background: `color-mix(in srgb, ${node.tone} 12%, transparent)` }}
        >
          <AgentAvatar role={node.role} size={30} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-semibold uppercase tracking-[0.08em] text-accent-text">
            {running ? "Live run" : hasStory ? "Last run" : STATE_WORDS[live.state]}
          </div>
          <h3 className="font-display text-[20px] font-semibold leading-tight">{node.name}</h3>
          <p className="text-[13px] text-muted">
            {hasStory && live.startedAt
              ? `Started by ${live.trigger ?? "you"} · ${new Date(live.startedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
              : subtitle(node)}
          </p>
        </div>
        <button type="button" className="btn btn-sm btn-ghost" aria-label="Close details" onClick={onClose}>
          <Icon name="x" size={16} />
        </button>
      </div>

      {node.kind === "scheduler" && <SchedulerBody agents={agents} />}
      {node.kind === "you" && (
        <p className="text-[14px] text-muted">
          You start work two ways: ask in Chat, or mention an agent by name. Agents on a schedule start without you.
        </p>
      )}

      {(node.kind === "agent" || node.kind === "lead" || node.kind === "helper") && (
        <>
          <Progress live={live} max={node.agent?.max_steps ?? null} />

          {hasStory ? (
            <ol className="stagger flex flex-col text-[14px]" aria-label="Steps">
              {live.story.map((item) => (
                <Step key={item.id} item={item} />
              ))}
            </ol>
          ) : (
            <p className="text-[14px] text-muted">
              {node.kind === "helper"
                ? "Your assistant calls this helper when part of a job suits it. Nothing yet."
                : "Nothing running right now. When it starts, each step appears here."}
            </p>
          )}

          <AgentFlow kind={node.kind} flowKey={node.role} agent={node.agent} name={node.name} />

          {live.problem && (
            <p role="alert" className="rounded-xl bg-bad-soft px-3.5 py-2.5 text-[13.5px] text-bad-text">
              {live.problem}
            </p>
          )}

          <Tiles node={node} live={live} />

          <div className="flex flex-wrap gap-2">
            {live.state === "waiting" && (
              <Button size="sm" variant="ok" icon="check" onClick={() => onApprove(node.id)}>
                Approve
              </Button>
            )}
            {node.agent && !running && (
              <Button size="sm" icon="play" disabled={busy} onClick={() => node.agent && onRunNow(node.agent)}>
                Run now
              </Button>
            )}
            {running && live.taskId && node.kind !== "helper" && (
              <Button size="sm" variant="danger-ghost" icon="stop" onClick={() => live.taskId && onStop(live.taskId)}>
                Stop
              </Button>
            )}
            {replayLink(node) && (
              <Link to={replayLink(node) as string} className="btn btn-sm btn-ghost">
                Open full replay
              </Link>
            )}
          </div>

          {node.agent && <AgentFacts agent={node.agent} runs={runs} />}
        </>
      )}
    </aside>
  );
}

function subtitle(node: PanelNode): string {
  if (node.kind === "scheduler") return "Starts your agents on time";
  if (node.kind === "you") return "Chat or @mention";
  if (node.kind === "lead") return "Your assistant, with its helpers";
  if (node.kind === "helper") return "Built-in helper";
  return node.agent?.schedule_text ?? "Runs when you ask";
}

function replayLink(node: PanelNode): string | null {
  if (node.kind === "agent") return node.agent?.run_conversation_id ? `/chat/${node.agent.run_conversation_id}` : null;
  return node.kind === "lead" ? "/chat" : null;
}

function Step({ item }: { item: StoryItem }) {
  const done = item.state === "done";
  const failed = item.state === "failed";
  return (
    <li className="flex gap-3 py-2">
      <span
        aria-hidden="true"
        className={`mt-0.5 flex h-[22px] w-[22px] flex-none items-center justify-center rounded-full border-2 ${
          done ? "border-ok bg-ok text-bg" : failed ? "border-bad bg-bad text-bg" : "border-ok"
        } ${item.state === "now" ? "tn-now" : ""}`}
      >
        {done && <Icon name="check" size={12} strokeWidth={3} />}
        {failed && <Icon name="x" size={12} strokeWidth={3} />}
      </span>
      <div className="min-w-0">
        <b className="font-semibold">{item.title}</b>
        <span className="sr-only">{done ? " (done)" : failed ? " (did not work)" : " (in progress)"}</span>
        {item.detail && <div className="text-[12.5px] text-muted">{item.detail}</div>}
      </div>
    </li>
  );
}

function Progress({ live, max }: { live: NodeLive; max: number | null }) {
  if (live.state !== "working" && live.state !== "waiting") return null;
  const step = live.llmCalls + 1;
  return (
    <div className="flex flex-col gap-1.5">
      {max ? (
        <div className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={live.llmCalls}>
          <i className="bg-gradient-to-r from-accent to-ok" style={{ ["--fill" as string]: Math.min(live.llmCalls / max, 1) }} />
        </div>
      ) : null}
      <span className="text-[12.5px] text-muted">
        Step {step}
        {max ? ` of up to ${max}` : ""}
      </span>
    </div>
  );
}

/** Model and size so far, and the cost once the run has ended. */
function Tiles({ node, live }: { node: PanelNode; live: NodeLive }) {
  const [cost, setCost] = useState<string | null>(null);
  const ended = live.state === "done" || live.state === "idle" || live.state === "failed";

  useEffect(() => {
    setCost(null);
    // A helper's cost is part of the assistant's run, so it has none of its own.
    if (!ended || !live.runId || node.kind === "helper") return;
    let closed = false;
    api
      .get<{ estimated_cost_usd: string }>(`/me/runs/${live.runId}`)
      .then((run) => !closed && setCost(fmtCost(run.estimated_cost_usd)))
      .catch(() => undefined);
    return () => {
      closed = true;
    };
  }, [ended, live.runId, node.kind]);

  if (!live.model && live.tokens === 0 && !cost) return null;
  return (
    <div className="grid grid-cols-2 gap-2.5">
      <div className="rounded-xl border border-line bg-sunken p-3">
        <div className="text-[12px] text-muted">Model</div>
        <div className="truncate font-display text-[17px] font-semibold">{live.model ?? "Not chosen yet"}</div>
      </div>
      <div className="rounded-xl border border-line bg-sunken p-3">
        <div className="text-[12px] text-muted">{cost ? "Cost (estimate)" : "Words used so far"}</div>
        <div className="font-display text-[17px] font-semibold">{cost ?? `${fmtTokens(live.tokens)} tokens`}</div>
      </div>
    </div>
  );
}

function SchedulerBody({ agents }: { agents: Agent[] }) {
  const upcoming = agents
    .filter((a) => a.schedule_enabled && a.next_run_at)
    .sort((a, b) => Date.parse(a.next_run_at ?? "") - Date.parse(b.next_run_at ?? ""));
  if (upcoming.length === 0) {
    return <p className="text-[14px] text-muted">Nothing is scheduled. Give an agent a time and it starts here by itself.</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="text-[12.5px] font-semibold text-muted">Next starts</div>
      <ul className="flex flex-col gap-1.5 text-[14px]">
        {upcoming.map((a) => (
          <li key={a.id} className="flex items-baseline justify-between gap-3">
            <span className="truncate">{a.name}</span>
            <span className="flex-none text-[12.5px] text-muted">{relativeTime(a.next_run_at as string)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AgentFacts({ agent, runs }: { agent: Agent; runs: AgentRunRow[] }) {
  const mine = runs.filter((r) => r.agent_id === agent.id).slice(0, 4);
  return (
    <div className="flex flex-col gap-4 border-t border-line pt-4">
      <div>
        <div className="mb-1.5 text-[12.5px] font-semibold text-muted">What it can use</div>
        {agent.tools === null ? (
          <p className="text-[13.5px] text-muted">Every tool your Permissions allow.</p>
        ) : agent.tools.length === 0 ? (
          <p className="text-[13.5px] text-muted">No tools.</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {agent.tools.map((t) => (
              <li key={t} className="rounded-full border border-line bg-sunken px-2.5 py-0.5 text-[12.5px] text-muted">
                {toolLabel(t)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="mb-1.5 text-[12.5px] font-semibold text-muted">Recent runs</div>
        {mine.length === 0 ? (
          <p className="text-[13.5px] text-muted">No runs yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {mine.map((r) => (
              <li key={r.run_id}>
                <Link
                  to={`/chat/${r.conversation_id}`}
                  className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-[13.5px] hover:bg-raised"
                >
                  <span className="flex items-center gap-2">
                    <StatusChip status={r.status} />
                    <span className="text-muted">{r.started_at ? relativeTime(r.started_at) : ""}</span>
                  </span>
                  <span className="font-mono text-[12px] text-dim">{fmtCost(r.cost_usd)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

import { fmtCost, fmtTokens } from "../../lib/agents";
import type { Agent, AgentStarter, AgentUsage } from "../../lib/api";
import { Icon } from "../icons";

const NODE_W = 210;
const NODE_H = 86;
const GAP = 14;
const COL_YOU = 0;
const COL_ASSISTANT = 250;
const COL_AGENTS = 520;

interface Branch {
  id: string;
  name: string;
  note: string;
  usage: AgentUsage | null;
  dim: boolean;
}

/**
 * Who your assistant can call, and where the money went.
 *
 * A branch is as thick as its share of what you spent, and it moves
 * only if that agent has actually run. An agent you made but never used
 * is drawn dashed and quiet, so the tree answers "which of my agents
 * earn their place" at a glance rather than just listing them.
 */
export default function AgentTree({
  agents,
  starters,
  assistantUsage,
  onOpen,
}: {
  agents: Agent[];
  starters: AgentStarter[];
  assistantUsage: AgentUsage;
  onOpen: (agent: Agent) => void;
}) {
  const branches: Branch[] = [
    ...agents.map((a) => ({
      id: a.id,
      name: a.name,
      note: a.tools === null ? "Every tool you allow" : `${a.tools.length} tool${a.tools.length === 1 ? "" : "s"}`,
      usage: a.usage,
      dim: false,
    })),
    ...starters
      .filter((s) => s.kind === "specialist")
      .map((s) => ({ id: s.key, name: s.name, note: "Built-in teammate", usage: null, dim: true })),
  ];

  const total =
    Number(assistantUsage.cost_usd) + agents.reduce((sum, a) => sum + Number(a.usage.cost_usd), 0) || 0;
  const rows = Math.max(branches.length, 2);
  const height = rows * NODE_H + (rows - 1) * GAP;
  const mid = height / 2;
  const centre = (i: number) => i * (NODE_H + GAP) + NODE_H / 2;
  const share = (u: AgentUsage | null) => (u && total > 0 ? Number(u.cost_usd) / total : 0);
  const stroke = (u: AgentUsage | null) => 1.5 + Math.min(share(u), 1) * 6;

  const curve = (x1: number, y1: number, x2: number, y2: number) => {
    const m = (x1 + x2) / 2;
    return `M${x1} ${y1} C${m} ${y1}, ${m} ${y2}, ${x2} ${y2}`;
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-[18px] font-semibold">Your agent tree</h2>
        <p className="text-[14px] text-muted">
          Thicker lines mean more of your spend. Moving lines are agents that have run. Costs are estimates.
        </p>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-line bg-panel p-5">
        <div className="relative" style={{ width: COL_AGENTS + NODE_W, height }}>
          <svg className="absolute inset-0" width={COL_AGENTS + NODE_W} height={height} aria-hidden="true">
            <path
              d={curve(COL_YOU + NODE_W, mid, COL_ASSISTANT, mid)}
              className="tree-line is-live"
              strokeWidth={2.5}
              fill="none"
            />
            {branches.map((b, i) => {
              const ran = !!b.usage && b.usage.runs > 0;
              return (
                <path
                  key={b.id}
                  d={curve(COL_ASSISTANT + NODE_W, mid, COL_AGENTS, centre(i))}
                  className={`tree-line ${ran ? "is-live" : "is-idle"}`}
                  strokeWidth={ran ? stroke(b.usage) : 1.5}
                  fill="none"
                />
              );
            })}
          </svg>

          <div className="tree-node is-you" style={{ left: COL_YOU, top: mid - NODE_H / 2, width: NODE_W, height: NODE_H }}>
            <Icon name="members" size={16} />
            <b>You</b>
            <span>Ask in chat, or @mention an agent</span>
          </div>

          <div
            className="tree-node is-lead"
            style={{ left: COL_ASSISTANT, top: mid - NODE_H / 2, width: NODE_W, height: NODE_H }}
          >
            <Icon name="sparkle" size={16} />
            <b>Your assistant</b>
            <span>
              {assistantUsage.runs} chat{assistantUsage.runs === 1 ? "" : "s"} · {fmtCost(assistantUsage.cost_usd)}
            </span>
          </div>

          {branches.map((b, i) => {
            const agent = agents.find((a) => a.id === b.id);
            const ran = !!b.usage && b.usage.runs > 0;
            return (
              <button
                key={b.id}
                type="button"
                disabled={!agent}
                onClick={() => agent && onOpen(agent)}
                className={`tree-node ${b.dim ? "is-starter" : "is-agent"} ${ran ? "is-ran" : ""}`}
                style={{ left: COL_AGENTS, top: i * (NODE_H + GAP), width: NODE_W, height: NODE_H }}
              >
                <Icon name={b.dim ? "employees" : "tree"} size={16} />
                <b>{b.name}</b>
                <span>{b.note}</span>
                {b.usage && (
                  <span className="font-mono">
                    {b.usage.runs} run{b.usage.runs === 1 ? "" : "s"} · {fmtCost(b.usage.cost_usd)} ·{" "}
                    {fmtTokens(b.usage.prompt_tokens + b.usage.output_tokens)} tok
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {agents.length === 0 && (
        <p className="text-[14px] text-dim">
          You have no agents yet. Make one in the Build tab and it appears here, next to the built-in teammates.
        </p>
      )}
    </div>
  );
}

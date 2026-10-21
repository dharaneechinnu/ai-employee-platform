import { useEffect, useMemo, useState } from "react";
import { deriveFlow, fmtCost, fmtMs, fmtTokens, type FlowLane } from "../../lib/agents";
import { api, type Agent, type AgentRunRow, type RunEvent } from "../../lib/api";
import { toolLabel } from "../../lib/labels";
import { Empty, ErrorNote, Spinner, StatusChip, relativeTime } from "../ui";

interface Trace {
  events: { seq: number; type: string; payload: Record<string, unknown>; at: string }[];
}

/** Lane colours: the assistant first, then one per specialist, repeating. */
const LANE_COLOUR = ["var(--accent)", "var(--run)", "var(--ok)", "var(--ask)", "var(--spark)"];

/**
 * Who did what, and what it cost.
 *
 * Chat already draws the route a request took. This is the other
 * question: laid out by time, one lane per agent that worked on the
 * answer, with the spend split across them. Lanes that overlap ran at
 * the same time, which is the whole point of asking several
 * specialists in one step.
 */
export default function FlowCost({ runs, agents }: { runs: AgentRunRow[]; agents: Agent[] }) {
  const [selected, setSelected] = useState<string | null>(runs[0]?.run_id ?? null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) return;
    let closed = false;
    setTrace(null);
    setError(null);
    api
      .get<Trace>(`/me/runs/${selected}/trace`)
      .then((t) => !closed && setTrace(t))
      .catch(() => !closed && setError("Could not load that run."));
    return () => {
      closed = true;
    };
  }, [selected]);

  const run = runs.find((r) => r.run_id === selected) ?? null;
  const flow = useMemo(() => {
    if (!trace || !run) return null;
    const events = trace.events.map((e) => ({ ...e.payload, seq: e.seq, type: e.type, at: e.at }) as RunEvent);
    return deriveFlow(events, Number(run.cost_usd), toolLabel);
  }, [trace, run]);

  if (runs.length === 0) {
    return (
      <Empty
        message="Nothing to chart yet."
        hint="Ask something in Chat. Each answer appears here with who worked on it and what it cost."
      />
    );
  }

  const agentName = (id: string | null) => agents.find((a) => a.id === id)?.name ?? "Assistant";

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-[18px] font-semibold">Flow and cost</h2>
        <p className="text-[14px] text-muted">
          Pick an answer to see who worked on it, in what order, and what each part cost. Costs are estimates from
          your own keys.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <ul className="flex max-h-[420px] flex-col gap-1.5 overflow-y-auto" aria-label="Recent answers">
          {runs.map((r) => (
            <li key={r.run_id}>
              <button
                type="button"
                aria-pressed={r.run_id === selected}
                className="flow-pick"
                onClick={() => setSelected(r.run_id)}
              >
                <span className="truncate text-[14px] font-medium">{r.title}</span>
                <span className="flex items-center gap-2 text-[12px] text-dim">
                  <span className="truncate">{agentName(r.agent_id)}</span>
                  <span className="font-mono">{fmtCost(r.cost_usd)}</span>
                  {r.started_at && <span>{relativeTime(r.started_at)}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="flex min-w-0 flex-col gap-4 rounded-2xl border border-line bg-panel p-4 sm:p-5">
          <ErrorNote message={error} />
          {!flow && !error && <Spinner rows={3} />}
          {flow && run && <Chart flow={flow} total={Number(run.cost_usd)} tokens={run.prompt_tokens + run.output_tokens} status={run.status} />}
        </div>
      </div>
    </div>
  );
}

function Chart({
  flow,
  total,
  tokens,
  status,
}: {
  flow: ReturnType<typeof deriveFlow>;
  total: number;
  tokens: number;
  status: string;
}) {
  const pct = (ms: number) => `${Math.min(100, Math.max(0, (ms / flow.duration) * 100))}%`;
  const spent = flow.lanes.reduce((s, l) => s + (l.cost ?? 0), 0) || total;

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Stat label="Estimated cost" value={fmtCost(total)} />
        <Stat label="Tokens" value={fmtTokens(tokens)} />
        <Stat label="Took" value={fmtMs(flow.duration)} />
        <Stat label="Agents" value={String(flow.lanes.length)} />
        <StatusChip status={status} />
      </div>

      <div className="flex flex-col gap-2.5" role="img" aria-label="Timeline of each agent's work on this answer">
        {flow.lanes.map((lane, i) => (
          <div key={lane.id} className="grid grid-cols-[120px_1fr] items-center gap-3 sm:grid-cols-[150px_1fr]">
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-medium">{lane.label}</div>
              <div className="truncate font-mono text-[11.5px] text-dim">
                {lane.cost === null ? "cost not recorded" : fmtCost(lane.cost)}
              </div>
            </div>
            <div className="flow-track">
              <div
                className={`flow-bar ${lane.ok === false ? "is-failed" : ""}`}
                style={{
                  left: pct(lane.start),
                  width: `max(${pct(lane.end - lane.start)}, 14px)`,
                  background: LANE_COLOUR[i % LANE_COLOUR.length],
                }}
                title={`${lane.label}: ${fmtMs(lane.end - lane.start)}`}
              />
              {lane.steps.map((s, k) => (
                <span
                  key={k}
                  className={`flow-tick is-${s.kind}`}
                  style={{ left: pct(s.at) }}
                  title={`${s.label} at ${fmtMs(s.at)}`}
                />
              ))}
            </div>
          </div>
        ))}
        <div className="grid grid-cols-[120px_1fr] gap-3 sm:grid-cols-[150px_1fr]">
          <span />
          <div className="flex justify-between font-mono text-[11px] text-dim">
            <span>0</span>
            <span>{fmtMs(flow.duration / 2)}</span>
            <span>{fmtMs(flow.duration)}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-[12px] font-medium uppercase tracking-wider text-dim">Where the money went</span>
        <div className="flow-split" role="img" aria-label="Share of cost by agent">
          {flow.lanes.map((lane, i) =>
            (lane.cost ?? 0) > 0 ? (
              <span
                key={lane.id}
                title={`${lane.label}: ${fmtCost(lane.cost)}`}
                style={{
                  width: `${((lane.cost ?? 0) / spent) * 100}%`,
                  background: LANE_COLOUR[i % LANE_COLOUR.length],
                }}
              />
            ) : null,
          )}
        </div>
        <ul className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-muted">
          {flow.lanes.map((lane, i) => (
            <LaneKey key={lane.id} lane={lane} colour={LANE_COLOUR[i % LANE_COLOUR.length]} share={(lane.cost ?? 0) / spent} />
          ))}
        </ul>
      </div>

      <div className="flex flex-wrap gap-4 text-[12px] text-dim">
        <span className="flex items-center gap-1.5">
          <span className="flow-tick is-think static-tick" /> thinks
        </span>
        <span className="flex items-center gap-1.5">
          <span className="flow-tick is-tool static-tick" /> uses a tool
        </span>
        <span className="flex items-center gap-1.5">
          <span className="flow-tick is-blocked static-tick" /> blocked by your Permissions
        </span>
      </div>
    </>
  );
}

function LaneKey({ lane, colour, share }: { lane: FlowLane; colour: string; share: number }) {
  return (
    <li className="flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: colour }} aria-hidden="true" />
      {lane.label}
      <span className="font-mono text-dim">
        {lane.cost === null ? "n/a" : `${Math.round(share * 100)}%`}
        {lane.promptTokens !== null && ` · ${fmtTokens((lane.promptTokens ?? 0) + (lane.outputTokens ?? 0))} tok`}
      </span>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11.5px] uppercase tracking-wider text-dim">{label}</span>
      <span className="font-mono text-[18px] font-semibold">{value}</span>
    </div>
  );
}

import { useEffect, useState } from "react";
import FlowCost from "../components/agents/FlowCost";
import { Card, ErrorNote, PageBody, PageHeader, Spinner } from "../components/ui";
import { fmtCost, fmtTokens } from "../lib/agents";
import { api, type AgentUsage, type AgentsOverview } from "../lib/api";

/** The assistant's own usage plus every agent's, added up. */
function total(data: AgentsOverview): { runs: number; tokens: number; cost: number } {
  const all: AgentUsage[] = [data.assistant_usage, ...data.agents.map((a) => a.usage)];
  return all.reduce(
    (sum, u) => ({
      runs: sum.runs + u.runs,
      tokens: sum.tokens + u.prompt_tokens + u.output_tokens,
      cost: sum.cost + (Number(u.cost_usd) || 0),
    }),
    { runs: 0, tokens: 0, cost: 0 },
  );
}

/**
 * Usage: what everything has cost, across the assistant and every
 * agent. It used to be a tab inside AI Agents, but the spend is the
 * whole account's, not one agent's.
 */
export default function Usage() {
  const [data, setData] = useState<AgentsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AgentsOverview>("/me/agents/overview")
      .then(setData)
      .catch(() => setError("Could not load your usage."));
  }, []);

  const sums = data ? total(data) : null;

  return (
    <>
      <PageHeader title="Usage" />
      <PageBody>
        <ErrorNote message={error} />
        {!data && !error && <Spinner rows={3} />}
        {data && sums && (
          <>
            <Card className="flex flex-col gap-3 p-5">
              <div className="flex flex-wrap items-end gap-x-10 gap-y-3">
                <Stat label="Runs" value={String(sums.runs)} />
                <Stat label="Tokens" value={fmtTokens(sums.tokens)} />
                <Stat label="Estimated cost" value={fmtCost(sums.cost)} />
              </div>
              <p className="text-[13px] text-dim">
                The assistant and all your agents together. The cost is an estimate worked out from token counts; your AI
                provider's bill is the real figure.
              </p>
            </Card>
            <FlowCost runs={data.recent_runs} agents={data.agents} />
          </>
        )}
      </PageBody>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11.5px] uppercase tracking-wider text-dim">{label}</span>
      <span className="font-mono text-[22px] font-semibold">{value}</span>
    </div>
  );
}

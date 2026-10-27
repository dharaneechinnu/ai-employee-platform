import { useEffect, useRef, useState } from "react";
import { fmtCost, fmtTokens } from "../../lib/agents";
import { api, type Usage, type UsageModel } from "../../lib/api";
import { modelName, planWords } from "../../lib/history";
import { ProviderMark } from "../ProviderMark";
import { Empty, ErrorNote, Spinner } from "../ui";

type Range = Usage["range"];

const RANGE_CHOICES: { value: Range; label: string }[] = [
  { value: "30d", label: "30 days" },
  { value: "7d", label: "7 days" },
  { value: "all", label: "All time" },
];

/** "$3.42"; a spend under a cent keeps its detail instead of rounding to nothing. */
function money(n: number): string {
  if (n === 0) return "$0.00";
  return n < 0.01 ? fmtCost(n) : `$${n.toFixed(2)}`;
}

function percent(part: number, whole: number): number {
  return whole > 0 ? Math.round((part / whole) * 100) : 0;
}

/** Counts up to `target` on load. Reduced motion jumps straight to it. */
function useCountUp(target: number): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (target === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / 700);
      setValue(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return value;
}

/**
 * Models and cost: what your AI models cost, which ones did the work, and
 * what the free ones saved you. Everything is an estimate worked out from
 * token counts; your AI provider's bill is the real figure.
 */
export default function CostView() {
  const [range, setRange] = useState<Range>("30d");
  const [reference, setReference] = useState("");
  const [data, setData] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  useEffect(() => {
    const mine = ++latest.current;
    const params = new URLSearchParams({ range });
    if (reference) params.set("reference", reference);
    api
      .get<Usage>(`/me/usage?${params.toString()}`)
      .then((found) => {
        if (mine !== latest.current) return;
        setData(found);
        setError(null);
      })
      .catch(() => {
        if (mine === latest.current) setError("Could not load your usage.");
      });
  }, [range, reference]);

  if (!data) {
    return (
      <>
        <ErrorNote message={error} />
        {!error && <Spinner rows={3} />}
      </>
    );
  }

  const empty = data.calls === 0;

  return (
    <div className="flex flex-col gap-5">
      <ErrorNote message={error} />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Time range">
          {RANGE_CHOICES.map((r) => (
            <button
              key={r.value}
              type="button"
              aria-pressed={range === r.value}
              onClick={() => setRange(r.value)}
              className={`rounded-full border px-3.5 py-1.5 text-[13px] transition-colors ${
                range === r.value
                  ? "border-accent-line bg-accent-soft font-medium text-ink"
                  : "border-line bg-panel text-muted hover:text-ink"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <ReferenceNote data={data} value={reference} onChange={setReference} />
      </div>

      {empty ? (
        <Empty
          message="No model use in this time yet."
          hint="Ask something in Chat or run an agent. What each model did, and what it cost, appears here."
        />
      ) : (
        <>
          <Kpis data={data} />
          <div className="grid gap-6 rounded-2xl border border-line bg-panel p-5 lg:grid-cols-2">
            <FreeVsPaid data={data} />
            <SpendByAgent data={data} />
          </div>
          <ModelTable data={data} />
        </>
      )}

      <p className="text-[13px] text-dim">
        Costs are estimates worked out from token counts; your AI provider's bill is the real figure. A model counts as
        Free when its calls cost nothing and Paid when they were charged for.
        {data.unpriced_calls > 0 &&
          ` ${data.unpriced_calls} call${data.unpriced_calls === 1 ? "" : "s"} used a model with no price on file, so ${
            data.unpriced_calls === 1 ? "it is" : "they are"
          } left out of what you saved.`}
      </p>
    </div>
  );
}

function ReferenceNote({
  data,
  value,
  onChange,
}: {
  data: Usage;
  value: string;
  onChange: (next: string) => void;
}) {
  if (!data.reference) {
    return <span className="text-[13px] text-dim sm:ml-auto">Connect an AI with a known price to see what you saved.</span>;
  }
  const current = `${data.reference.provider_key}:${data.reference.model}`;
  return (
    <label className="flex flex-wrap items-center gap-2 text-[13px] text-muted sm:ml-auto">
      <span>
        Saved is measured against
        {data.reference_is_default && " your priciest connected model"}:
      </span>
      <select
        className="field !w-auto max-w-full !py-1 text-[13px] text-ink"
        value={current}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Model to measure what you saved against"
      >
        {data.reference_choices.map((c) => (
          <option key={`${c.provider_key}:${c.model}`} value={`${c.provider_key}:${c.model}`}>
            {c.provider_name} · {modelName(c.model)}
          </option>
        ))}
      </select>
      {value && (
        <button type="button" className="text-accent-text underline" onClick={() => onChange("")}>
          Use the default
        </button>
      )}
    </label>
  );
}

function Kpis({ data }: { data: Usage }) {
  const spent = useCountUp(Number(data.total_cost_usd));
  const saved = useCountUp(Number(data.saved_usd));
  const free = useCountUp(percent(data.free.calls, data.calls));
  const paid = useCountUp(percent(data.paid.calls, data.calls));
  return (
    <div className="stagger grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr))]">
      <Kpi label="You spent" value={money(spent)} note={`across ${data.runs} run${data.runs === 1 ? "" : "s"}`} />
      <Kpi
        label="Estimated saved"
        value={money(saved)}
        note={data.reference ? "if every call had used the reference model" : "needs a model with a known price"}
        accent
      />
      <Kpi label="Free model share" value={`${Math.round(free)}%`} note="of all calls" />
      <Kpi label="Paid model share" value={`${Math.round(paid)}%`} note="of all calls" />
    </div>
  );
}

function Kpi({ label, value, note, accent }: { label: string; value: string; note: string; accent?: boolean }) {
  return (
    <div className="card p-4" style={accent ? { borderColor: "var(--ok)" } : undefined}>
      <div className="text-[12px] font-medium uppercase tracking-wider text-dim">{label}</div>
      <div className={`mt-1 font-display text-[28px] font-bold tabular-nums ${accent ? "text-ok-text" : ""}`}>{value}</div>
      <div className="text-[13px] text-muted">{note}</div>
    </div>
  );
}

/** One sentence about the split, in plain words. */
function splitSentence(data: Usage): string {
  const { free, paid, unknown } = data;
  if (free.calls === 0 && paid.calls === 0) return "No call here can be called free or paid yet.";
  const parts: string[] = [];
  if (free.calls > 0)
    parts.push(
      `Free models took ${percent(free.calls, data.calls)}% of your calls (${fmtTokens(free.tokens)} tokens) and cost nothing.`,
    );
  if (paid.calls > 0)
    parts.push(
      `Paid models took ${percent(paid.calls, data.calls)}% (${fmtTokens(paid.tokens)} tokens) and cost ${money(Number(paid.cost_usd))}.`,
    );
  if (unknown.calls > 0) parts.push(`${percent(unknown.calls, data.calls)}% used a model with no price on file.`);
  return parts.join(" ");
}

function FreeVsPaid({ data }: { data: Usage }) {
  const segments = [
    { key: "free", label: "Free", calls: data.free.calls, colour: "var(--ok)" },
    { key: "paid", label: "Paid", calls: data.paid.calls, colour: "var(--accent)" },
    { key: "unknown", label: "Price unknown", calls: data.unknown.calls, colour: "var(--ask)" },
  ];
  return (
    <section>
      <h2 className="font-display text-[17px] font-semibold">How free and paid models were used</h2>
      <div
        className="my-3.5 flex h-[22px] gap-0.5 overflow-hidden rounded-lg bg-raised"
        role="img"
        aria-label={`Share of calls: ${segments.map((s) => `${s.label} ${percent(s.calls, data.calls)}%`).join(", ")}`}
      >
        {segments
          .filter((s) => s.calls > 0)
          .map((s) => (
            <i
              key={s.key}
              className="lane-bar block h-full"
              style={{ width: `${(s.calls / data.calls) * 100}%`, background: s.colour }}
            />
          ))}
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.colour }} aria-hidden="true" />
            {s.label}
            <span className="font-mono text-dim">
              {s.calls} call{s.calls === 1 ? "" : "s"}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[13.5px] text-muted">{splitSentence(data)}</p>
    </section>
  );
}

function SpendByAgent({ data }: { data: Usage }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  const biggest = Math.max(...data.agents.map((a) => Number(a.cost_usd)), 0);
  return (
    <section>
      <h2 className="font-display text-[17px] font-semibold">Spend by agent</h2>
      <ul className="mt-3 flex flex-col gap-2.5 text-[13.5px]">
        {data.agents.map((a) => {
          const cost = Number(a.cost_usd);
          const fill = biggest > 0 ? Math.max(cost / biggest, 0.012) : 0.012;
          return (
            <li
              key={a.agent_id ?? "assistant"}
              className="grid grid-cols-[minmax(80px,120px)_1fr_64px] items-center gap-2.5"
            >
              <span className="truncate" title={a.name}>
                {a.name}
              </span>
              <div className="meter" role="img" aria-label={`${a.name}: ${money(cost)} over ${a.runs} runs`}>
                <i style={{ ["--fill" as string]: ready ? fill : 0, background: cost > 0 ? "var(--accent)" : "var(--ok)" }} />
              </div>
              <span className="text-right font-mono tabular-nums">{money(cost)}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function PlanPill({ plan }: { plan: UsageModel["plan"] }) {
  const look =
    plan === "free" ? "bg-ok-soft text-ok-text" : plan === "paid" ? "bg-accent-soft text-accent-text" : "bg-ask-soft text-ask-text";
  return <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold ${look}`}>{planWords(plan)}</span>;
}

const COLUMNS = "md:grid-cols-[minmax(170px,1.4fr)_110px_60px_80px_90px_90px_minmax(100px,1fr)]";

function ModelTable({ data }: { data: Usage }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-panel">
      <div
        className={`hidden gap-3 px-5 py-2.5 text-[11.5px] font-medium uppercase tracking-wider text-dim md:grid ${COLUMNS}`}
      >
        <span>Model</span>
        <span>Type</span>
        <span>Runs</span>
        <span>Tokens</span>
        <span>Cost</span>
        <span>Saved</span>
        <span>Share of use</span>
      </div>
      <ul>
        {data.models.map((m) => (
          <ModelRow key={`${m.provider_key}:${m.model}`} m={m} />
        ))}
      </ul>
    </div>
  );
}

function ModelRow({ m }: { m: UsageModel }) {
  const priced = m.plan !== "unknown";
  const accent = m.plan === "free" ? "var(--ok)" : m.plan === "paid" ? "var(--accent)" : "var(--ask)";
  const saved = m.is_reference ? (
    <span className="text-dim">reference</span>
  ) : m.saved_usd === null ? (
    <span className="text-dim">n/a</span>
  ) : (
    <span className="text-ok-text">{money(Number(m.saved_usd))}</span>
  );
  return (
    <li
      className={`grid grid-cols-2 items-center gap-x-3 gap-y-2 border-t border-line px-4 py-3 text-[14px] tabular-nums transition-colors hover:bg-raised md:gap-3 md:px-5 ${COLUMNS}`}
    >
      <div className="col-span-2 flex min-w-0 items-center gap-2.5 md:col-span-1">
        <ProviderMark provider={m.provider_key} size={34} />
        <div className="min-w-0">
          <div className="truncate font-semibold" title={m.model}>
            {modelName(m.model)}
          </div>
          <div className="truncate text-[12px] text-dim">{m.provider_name}</div>
        </div>
        <span className="ml-auto md:hidden">
          <PlanPill plan={m.plan} />
        </span>
      </div>
      <span className="hidden md:block">
        <PlanPill plan={m.plan} />
      </span>
      <Cell label="Runs">{m.runs}</Cell>
      <Cell label="Tokens">{fmtTokens(m.tokens)}</Cell>
      <Cell label="Cost">{priced ? money(Number(m.cost_usd)) : <span className="text-dim">n/a</span>}</Cell>
      <Cell label="Saved">{saved}</Cell>
      <div className="col-span-2 flex items-center gap-2 md:col-span-1">
        <div className="meter flex-1" role="img" aria-label={`${Math.round(m.share * 100)}% of your calls`}>
          <i style={{ ["--fill" as string]: Math.max(m.share, 0.012), background: accent }} />
        </div>
        <span className="w-9 text-right font-mono text-[12px] text-dim md:hidden">{Math.round(m.share * 100)}%</span>
      </div>
    </li>
  );
}

/** A figure that shows its own label on a phone, where the table header is hidden. */
function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex items-baseline justify-between gap-2 md:block">
      <span className="text-[12px] text-dim md:hidden">{label}</span>
      <span>{children}</span>
    </span>
  );
}

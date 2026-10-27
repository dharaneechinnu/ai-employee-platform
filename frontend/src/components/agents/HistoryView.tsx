import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmtCost, fmtTokens } from "../../lib/agents";
import {
  ApiError,
  api,
  type Agent,
  type HistoryDetail,
  type HistoryItem,
  type HistoryLane,
  type HistoryPage,
  type RunEvent,
  type RunNowResult,
} from "../../lib/api";
import {
  RANGES,
  STARTED_BY,
  STATUS_CHOICES,
  fmtDuration,
  modelName,
  modelsLine,
  planWords,
  sinceFor,
} from "../../lib/history";
import { toolLabel } from "../../lib/labels";
import RunFlow from "../RunFlow";
import { Icon } from "../icons";
import { Button, Chip, Empty, ErrorNote, SearchBox, Spinner, StatusChip, relativeTime, useToast } from "../ui";

const PAGE = 25;

interface Filters {
  q: string;
  agent: string;
  status: string;
  range: string;
  model: string;
  cost: string;
}

const NO_FILTERS: Filters = { q: "", agent: "", status: "", range: "7", model: "", cost: "" };

/** "Today 23:30", "Yesterday 09:05", "14 Nov 18:20". */
function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

function nameOf(run: HistoryItem): string {
  return run.agent_name ?? run.title ?? "Chat";
}

function query(f: Filters, before?: string | null): string {
  const p = new URLSearchParams({ limit: String(PAGE) });
  const since = sinceFor(RANGES.find((r) => r.value === f.range)?.days ?? null);
  if (before) p.set("before", before);
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.agent) p.set("agent_id", f.agent);
  if (f.status) p.set("status", f.status);
  if (since) p.set("since", since);
  if (f.model) p.set("model", f.model);
  if (f.cost) p.set("cost", f.cost);
  return p.toString();
}

/**
 * Every run you have had, newest first: the ones your agents started on
 * their schedule, the ones you started with Run now, and your chats.
 * Open one for who did what over time, the AI it used, and its result,
 * and replay it step by step.
 */
export default function HistoryView({ agents }: { agents: Agent[] }) {
  const toast = useToast();
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [typed, setTyped] = useState("");
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const latest = useRef(0);

  // Typing waits a moment, so a search is one request and not one per letter.
  useEffect(() => {
    const timer = window.setTimeout(() => setFilters((f) => (f.q === typed ? f : { ...f, q: typed })), 300);
    return () => window.clearTimeout(timer);
  }, [typed]);

  useEffect(() => {
    api.get<string[]>("/me/history/models").then(setModels).catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    const mine = ++latest.current;
    try {
      const page = await api.get<HistoryPage>(`/me/history/runs?${query(filters)}`);
      if (mine !== latest.current) return;
      setItems(page.items);
      setNext(page.next);
      setError(null);
    } catch {
      if (mine === latest.current) setError("Could not load your history.");
    }
  }, [filters]);

  useEffect(() => {
    setItems(null);
    void load();
  }, [load]);

  // A run that is going changes under you: look again while one is on screen.
  const going = items?.some((r) => r.status === "running" || r.status === "awaiting_approval") ?? false;
  useEffect(() => {
    if (!going) return;
    const timer = window.setInterval(() => {
      const mine = ++latest.current;
      api
        .get<HistoryPage>(`/me/history/runs?${query(filters)}`)
        .then((page) => {
          if (mine !== latest.current) return;
          // Refresh the newest page in place; older pages already loaded stay.
          setItems((old) => {
            const fresh = new Set(page.items.map((r) => r.id));
            const oldest = page.items.at(-1)?.created_at ?? "";
            const kept = (old ?? []).filter((r) => !fresh.has(r.id) && r.created_at < oldest);
            return [...page.items, ...kept];
          });
        })
        .catch(() => undefined);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [going, filters]);

  async function older() {
    if (!next) return;
    setMore(true);
    try {
      const page = await api.get<HistoryPage>(`/me/history/runs?${query(filters, next)}`);
      setItems((old) => [...(old ?? []), ...page.items]);
      setNext(page.next);
    } catch {
      toast("Could not load older runs.");
    } finally {
      setMore(false);
    }
  }

  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));
  const filtered = filters.agent || filters.status || filters.model || filters.cost || filters.q.trim() || filters.range !== "all";
  const clear = () => {
    setTyped("");
    setFilters({ ...NO_FILTERS, range: "all" });
  };

  // Esc closes the panel, unless something else (a dialog, the palette) owns the keyboard.
  useEffect(() => {
    if (!selected) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !document.querySelector("[role=dialog]")) setSelected(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchBox value={typed} onChange={setTyped} placeholder="Search runs. Press /" label="Search your history" />
          <Pick label="Agent" value={filters.agent} onChange={(agent) => set({ agent })}>
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Pick>
          <Pick label="Status" value={filters.status} onChange={(status) => set({ status })}>
            {STATUS_CHOICES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Pick>
          <Pick label="Time" value={filters.range} onChange={(range) => set({ range })}>
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Pick>
          <Pick label="AI model" value={filters.model} onChange={(model) => set({ model })}>
            <option value="">Any model</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {modelName(m)}
              </option>
            ))}
          </Pick>
          <Pick label="Cost" value={filters.cost} onChange={(cost) => set({ cost })}>
            <option value="">Free and paid</option>
            <option value="free">Cost nothing</option>
            <option value="paid">Cost something</option>
          </Pick>
        </div>

        <ErrorNote message={error} />
        {!items && !error && <Spinner rows={4} />}

        {items && items.length === 0 && (
          <Empty
            message={filtered ? "No runs match those filters." : "No runs yet."}
            hint={
              filtered
                ? "Try a wider time range, or clear the filters."
                : "When an agent runs, or you ask your assistant something, it shows up here to read and replay."
            }
          >
            {filtered && (
              <Button variant="ghost" size="sm" onClick={clear}>
                Show every run
              </Button>
            )}
          </Empty>
        )}

        {items && items.length > 0 && (
          <div className="overflow-hidden rounded-2xl border border-line bg-panel">
            <ul className="stagger">
              {items.map((run) => (
                <li key={run.id} className="border-t border-line first:border-t-0">
                  <Row run={run} on={run.id === selected} onOpen={() => setSelected(run.id)} />
                </li>
              ))}
            </ul>
            {next && (
              <button
                type="button"
                disabled={more}
                onClick={() => void older()}
                className="w-full border-t border-line px-4 py-3 text-center text-[13.5px] text-accent-text hover:bg-raised disabled:opacity-60"
              >
                {more ? "Loading…" : "Load older runs"}
              </button>
            )}
          </div>
        )}
        {items && items.length > 0 && !next && (
          <p className="text-center text-[13px] text-dim">That is every run for these filters.</p>
        )}
        <p className="text-[12.5px] text-dim">Costs are estimates. Your AI provider's bill is the real figure.</p>
      </div>

      {selected ? (
        <Detail key={selected} id={selected} onClose={() => setSelected(null)} onChanged={() => void load()} />
      ) : (
        <aside className="side-panel rounded-2xl border p-5 max-lg:hidden" aria-label="Run details">
          <p className="font-display text-[16px] font-semibold">Pick a run</p>
          <p className="mt-1 text-[14px] text-muted">
            Open any run to see who did what and when, which AI it used, and what it said. You can replay it step by step.
          </p>
        </aside>
      )}
    </div>
  );
}

function Pick({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="min-w-0">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="field h-11 max-w-[11.5rem] cursor-pointer py-0 pr-8 text-[13.5px]"
        aria-label={label}
      >
        {children}
      </select>
    </label>
  );
}

function Row({ run, on, onOpen }: { run: HistoryItem; on: boolean; onOpen: () => void }) {
  const failed = run.status === "failed";
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={on}
      className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-raised ${on ? "card-on" : ""}`}
    >
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-9 w-9 flex-none items-center justify-center rounded-[10px] bg-raised text-ink"
      >
        <Icon name={run.agent_id ? "clock" : "chat"} size={18} />
      </span>
      <span className="grid min-w-0 flex-1 gap-x-4 gap-y-1 sm:grid-cols-[minmax(0,1fr)_auto]">
        <span className="min-w-0">
          <b className="block truncate text-[14.5px] font-semibold">{nameOf(run)}</b>
          <span className={`block truncate text-[13px] ${failed ? "text-bad-text" : "text-muted"}`}>
            {run.status === "running" ? "Working on it…" : run.summary || "No result yet."}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted sm:justify-end">
          <StatusChip status={run.status} />
          <span>{STARTED_BY[run.trigger]}</span>
          <span className="max-w-[9rem] truncate">{modelsLine(run.models)}</span>
          <span>{when(run.started_at ?? run.created_at)}</span>
          <span>{fmtDuration(run.duration_seconds)}</span>
          <span className="font-mono text-[12px] text-dim">{fmtCost(run.estimated_cost_usd)}</span>
        </span>
      </span>
    </button>
  );
}

// ------------------------------------------------------------- one run

function Detail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [run, setRun] = useState<HistoryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[] | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let closed = false;
    api
      .get<HistoryDetail>(`/me/history/runs/${id}`)
      .then((r) => !closed && setRun(r))
      .catch(() => !closed && setError("Could not load this run."));
    return () => {
      closed = true;
    };
  }, [id]);

  async function replay() {
    if (replaying) return setReplaying(false);
    setReplaying(true);
    if (events) return;
    try {
      const trace = await api.get<{ events: RunEvent[] }>(`/me/runs/${id}/trace`);
      // The trace nests each event's details under `payload`; the view wants them flat.
      setEvents(
        trace.events.map((e) => {
          const { payload, ...rest } = e as RunEvent & { payload?: Record<string, unknown> };
          return { ...(payload ?? {}), ...rest } as RunEvent;
        }),
      );
    } catch {
      setReplaying(false);
      toast("Could not load the steps of this run.");
    }
  }

  async function again() {
    if (!run?.agent_id) return;
    setBusy(true);
    try {
      const res = await api.post<RunNowResult>(`/me/agents/${run.agent_id}/run`, {});
      toast(res.status === "started" ? `${nameOf(run)} is running now.` : res.message || "It could not start.");
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start it.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(run?.result ?? "");
      toast("Result copied.");
    } catch {
      toast("Could not copy. Select the text instead.");
    }
  }

  const shell = "side-panel flex flex-col gap-4 rounded-2xl border p-5 max-lg:fixed max-lg:inset-0 max-lg:z-40 max-lg:overflow-y-auto max-lg:rounded-none";

  if (!run) {
    return (
      <aside className={shell} aria-label="Run details">
        <div className="flex justify-end">
          <CloseButton onClose={onClose} />
        </div>
        {error ? <ErrorNote message={error} /> : <Spinner rows={3} />}
      </aside>
    );
  }

  const waiting = run.status === "awaiting_approval";
  return (
    <aside className={shell} aria-label="Run details">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <StatusChip status={run.status} />
          <h3 className="mt-2 font-display text-[20px] font-semibold leading-tight">{nameOf(run)}</h3>
          <p className="text-[13px] text-muted">
            {when(run.started_at ?? run.created_at)} · started by {STARTED_BY[run.trigger].toLowerCase()}
            {run.started_at && ` · ${relativeTime(run.started_at)}`}
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>

      {(run.status === "failed" || run.status === "cancelled") && (
        <p role="alert" className="rounded-xl bg-bad-soft px-3.5 py-2.5 text-[13.5px] text-bad-text">
          {run.error_message ||
            (run.status === "cancelled" ? "You stopped this run." : "This run did not finish. The steps below show how far it got.")}
        </p>
      )}
      {waiting && (
        <p className="rounded-xl bg-ask-soft px-3.5 py-2.5 text-[13.5px] text-ask-text">
          This run is waiting for you. <Link to="/approvals" className="underline">Open approvals</Link>
        </p>
      )}

      <div className="grid grid-cols-3 gap-2.5">
        <Tile label="Time" value={fmtDuration(run.duration_seconds)} />
        <Tile label="Cost (estimate)" value={fmtCost(run.estimated_cost_usd)} />
        <Tile label="Steps" value={String(run.step_count)} />
      </div>

      <Section title="Who did what, over time">
        <Lanes lanes={run.lanes} />
      </Section>

      <Section title="AI used">
        {run.models.length === 0 ? (
          <p className="text-[13.5px] text-muted">No AI was called.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {run.models.map((m) => (
              <li key={`${m.provider_key}:${m.model}`} className="flex flex-wrap items-center gap-2 text-[13.5px]">
                <Chip tone={m.plan === "free" ? "ok" : m.plan === "paid" ? "brand" : "mute"} dot={false}>
                  {modelName(m.model)} · {planWords(m.plan)}
                </Chip>
                <span className="text-[12.5px] text-muted">
                  {fmtTokens(m.prompt_tokens + m.output_tokens)} tokens · {fmtCost(m.estimated_cost_usd)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Result">
        {run.result ? (
          <div className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl border border-line bg-sunken p-3 text-[14px] text-ink">
            {run.result}
          </div>
        ) : (
          <p className="text-[13.5px] text-muted">{run.status === "running" ? "Still working on it." : "It did not leave a written result."}</p>
        )}
      </Section>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" icon="play" className="flex-1" onClick={() => void replay()} aria-expanded={replaying}>
          {replaying ? "Hide the replay" : "Replay step by step"}
        </Button>
        {run.can_run_again && (
          <Button size="sm" variant="ghost" icon="refresh" disabled={busy} onClick={() => void again()}>
            Run again
          </Button>
        )}
        <Button size="sm" variant="ghost" icon="chat" onClick={() => navigate(`/chat/${run.conversation_id}`)}>
          Open chat
        </Button>
        {run.result && (
          <Button size="sm" variant="ghost" icon="copy" onClick={() => void copy()}>
            Copy result
          </Button>
        )}
      </div>

      {replaying && (
        <div className="rounded-xl border border-line bg-sunken p-4">
          {events ? (
            events.length > 0 ? (
              <RunFlow events={events} assistant={run.agent_name ?? "Your assistant"} runStatus={run.status} />
            ) : (
              <p className="text-[13.5px] text-muted">This run has no recorded steps.</p>
            )
          ) : (
            <div className="skeleton h-16 rounded-xl" />
          )}
        </div>
      )}
    </aside>
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button type="button" className="btn btn-sm btn-ghost flex-none" aria-label="Close details" onClick={onClose}>
      <Icon name="x" size={16} />
    </button>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken p-3">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="font-display text-[17px] font-semibold">{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-dim">{title}</div>
      {children}
    </div>
  );
}

/** Each bar starts when the thing began and ends when it finished. */
function Lanes({ lanes }: { lanes: HistoryLane[] }) {
  const total = useMemo(() => Math.max(1, ...lanes.map((l) => l.end_ms)), [lanes]);
  if (lanes.length <= 1) {
    return <p className="text-[13.5px] text-muted">It did not use any tools.</p>;
  }
  return (
    <ul className="flex flex-col gap-2 text-[12.5px] text-muted" aria-label="Timeline">
      {lanes.map((l, i) => {
        const left = (l.start_ms / total) * 100;
        const width = Math.max(((l.end_ms - l.start_ms) / total) * 100, 2.5);
        const tone = l.ok === false ? "var(--bad)" : l.kind === "tool" ? "var(--ok)" : l.kind === "agent" ? "var(--accent)" : "var(--run)";
        const label = l.kind === "tool" ? toolLabel(l.key) : l.label;
        return (
          <li key={i} className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-2">
            <span className="truncate" title={label}>
              {label}
            </span>
            <span className="block">
              <i
                className="lane-bar block h-3 rounded-md"
                style={{ background: tone, marginLeft: `${Math.min(left, 100 - width)}%`, width: `${width}%` }}
                title={`${fmtDuration(Math.round((l.end_ms - l.start_ms) / 1000))}${l.ok === false ? " · did not work" : ""}`}
              />
              <span className="sr-only">
                {`${((l.end_ms - l.start_ms) / 1000).toFixed(1)} seconds${l.ok === false ? ", did not work" : ""}`}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

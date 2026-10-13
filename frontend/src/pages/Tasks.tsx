import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AgentTree from "../components/AgentTree";
import SetupGuide, { type SetupStatus } from "../components/SetupGuide";
import VoiceInput from "../components/VoiceInput";
import { Icon, type IconName } from "../components/icons";
import {
  Avatar,
  Button,
  Chip,
  Empty,
  ErrorNote,
  PageBody,
  PageHeader,
  SearchBox,
  Spinner,
  StatusChip,
  Switch,
  Tabs,
  TextArea,
  relativeTime,
  useToast,
} from "../components/ui";
import { notifyActivity } from "../lib/activity";
import {
  ApiError,
  api,
  streamRun,
  type EmployeeList,
  type EmployeeListItem,
  type RunEvent,
  type Task,
  type TaskListItem,
} from "../lib/api";
import { useAuth, useIsAdmin } from "../lib/auth";
import { formatDateTime, toolLabel } from "../lib/labels";

/**
 * Phase 4. Assigning a task returns immediately; the run happens in a
 * worker and arrives here as a live event stream.
 *
 * The run panel is the screen that matters: it is the difference
 * between watching an agent work and staring at a spinner. Timeline,
 * agent tree and result are three views of one run, so they are tabs
 * rather than pages.
 */

type Filter = "all" | "running" | "needs" | "done" | "failed";

const FILTER_OF: Record<string, Filter> = {
  queued: "running",
  running: "running",
  awaiting_approval: "needs",
  completed: "done",
  failed: "failed",
  cancelled: "failed",
};

const POLL_MS = 15_000;

export default function Tasks() {
  const { org } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const selected = params.get("task");
  const treeView = params.get("view") === "tree";

  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeList | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [input, setInput] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const isAdmin = useIsAdmin();
  const [setup, setSetup] = useState<SetupStatus | null>(null);

  async function loadTasks() {
    if (!org) return;
    setTasks(await api.get<TaskListItem[]>(`/orgs/${org.id}/tasks`));
    setSetup(await api.get<SetupStatus>(`/orgs/${org.id}/setup`).catch(() => null));
  }

  useEffect(() => {
    if (!org) return;
    void (async () => {
      const list = await api.get<EmployeeList>(`/orgs/${org.id}/ai-employees`);
      setEmployees(list);
      const firstActive = list.items.find((e) => e.status === "active");
      setEmployeeId((current) => current || firstActive?.id || "");
      await loadTasks();
    })();
    const timer = window.setInterval(() => void loadTasks(), POLL_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  // The sidebar's "New task" button lands here with ?new=1.
  useEffect(() => {
    if (params.get("new") && employees) {
      composer.current?.focus();
      const next = new URLSearchParams(params);
      next.delete("new");
      setParams(next, { replace: true });
    }
  }, [params, setParams, employees]);

  // Open the newest task when nothing is chosen, so the panel is never blank.
  useEffect(() => {
    if (!selected && tasks?.length) {
      const next = new URLSearchParams(params);
      next.set("task", tasks[0].id);
      setParams(next, { replace: true });
    }
  }, [tasks, selected, params, setParams]);

  const names = useMemo(() => {
    const map = new Map<string, EmployeeListItem>();
    employees?.items.forEach((e) => map.set(e.id, e));
    return map;
  }, [employees]);

  const counts = useMemo(() => {
    const result: Record<Filter, number> = { all: 0, running: 0, needs: 0, done: 0, failed: 0 };
    tasks?.forEach((t) => {
      result.all += 1;
      const bucket = FILTER_OF[t.status];
      if (bucket) result[bucket] += 1;
    });
    return result;
  }, [tasks]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (tasks ?? []).filter(
      (t) =>
        (filter === "all" || FILTER_OF[t.status] === filter) &&
        (!term || (t.title ?? "").toLowerCase().includes(term)),
    );
  }, [tasks, filter, search]);

  function select(id: string) {
    const next = new URLSearchParams(params);
    next.set("task", id);
    setParams(next);
  }

  async function assign(e?: React.FormEvent) {
    e?.preventDefault();
    if (!org || !employeeId || !input.trim()) return;
    setError(null);
    setBusy(true);
    try {
      const task = await api.post<Task>(`/orgs/${org.id}/tasks`, {
        employee_id: employeeId,
        input,
        dry_run: dryRun,
      });
      setInput("");
      select(task.id);
      await loadTasks();
      notifyActivity();
      toast(`Assigned to ${names.get(employeeId)?.name ?? "your AI Employee"}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not assign that.");
    } finally {
      setBusy(false);
    }
  }

  if (!tasks || !employees) {
    return (
      <>
        <PageHeader crumb="Work" title="Tasks" />
        <Spinner />
      </>
    );
  }

  const active = employees.items.filter((e) => e.status === "active");
  const pickedName = names.get(employeeId)?.name;

  return (
    <>
      <PageHeader crumb={<>Work</>} title="Tasks">
        {counts.running > 0 && <Chip tone="run">{counts.running} running</Chip>}
        {counts.needs > 0 && (
          <Link to="/approvals" className="no-underline">
            <Chip tone="ask">{counts.needs} waiting on a person</Chip>
          </Link>
        )}
      </PageHeader>

      <PageBody>
        {setup && <SetupGuide status={setup} isAdmin={isAdmin} />}
        <form onSubmit={assign} className="card rise flex flex-col gap-4 p-5">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="flex-1 font-display text-[17px] font-semibold">Assign work</h2>
            {active.length > 0 && (
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="AI Employee">
                {active.map((employee) => {
                  const on = employee.id === employeeId;
                  return (
                    <button
                      key={employee.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => setEmployeeId(employee.id)}
                      className={`flex h-11 items-center gap-2 rounded-full border pl-1.5 pr-3.5 text-sm font-medium transition-colors ${
                        on
                          ? "border-accent bg-accent-soft text-ink"
                          : "border-line2 text-muted hover:border-accent-line hover:text-ink"
                      }`}
                    >
                      <Avatar name={employee.name} size={30} />
                      {employee.name}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {active.length === 0 ? (
            <Empty
              message="No active AI Employees yet"
              hint="Create one, or switch one on, before assigning work."
            >
              <Link to="/employees" className="btn btn-ghost btn-sm mt-1">
                Go to AI Employees
              </Link>
            </Empty>
          ) : (
            <>
              <TextArea
                label="What should it do?"
                hideLabel
                rows={2}
                value={input}
                onChange={setInput}
                inputRef={composer}
                placeholder="What should it do? For example: summarise yesterday's support emails."
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void assign();
                }}
              />
              <ErrorNote message={error} />
              <div className="flex flex-wrap items-center gap-3.5">
                {org && (
                  <VoiceInput
                    orgId={org.id}
                    onError={setError}
                    onText={(spoken) => {
                      // Added to what is already typed, so speaking can
                      // finish a sentence started on the keyboard.
                      setInput((typed) => (typed.trim() ? `${typed.trimEnd()} ${spoken}` : spoken));
                      composer.current?.focus();
                    }}
                  />
                )}
                <span className="flex items-center gap-2.5 text-[13px] text-muted">
                  <Switch checked={dryRun} onChange={setDryRun} label="Dry run" />
                  Dry run: plan only, nothing is changed or sent
                </span>
                <span className="ml-auto flex items-center gap-2.5">
                  <span className="hidden text-xs text-dim sm:inline">
                    <span className="kbd">Ctrl</span> + <span className="kbd">Enter</span>
                  </span>
                  <Button
                    type="submit"
                    disabled={busy || !input.trim() || !employeeId || setup?.ai_connected === false}
                    title={setup?.ai_connected === false ? "Connect an AI key first" : undefined}
                  >
                    {busy ? "Assigning…" : `Assign to ${pickedName ?? "…"}`}
                    <Icon name="arrow" size={16} strokeWidth={2.2} />
                  </Button>
                </span>
              </div>
            </>
          )}
        </form>

        {/* The agent tree needs the full width; the list steps aside until
            you go back to the timeline. */}
        <div className={`grid grid-cols-1 items-start gap-5 ${treeView ? "" : "xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]"}`}>
          <section className={`flex flex-col gap-3 ${treeView ? "hidden" : ""}`}>
            <div className="flex flex-wrap items-center gap-2.5">
              <Tabs
                label="Filter tasks"
                value={filter}
                onChange={setFilter}
                items={[
                  { key: "all", label: "All", count: counts.all },
                  { key: "running", label: "Running", count: counts.running },
                  { key: "needs", label: "Needs you", count: counts.needs },
                  { key: "done", label: "Done", count: counts.done },
                  { key: "failed", label: "Failed", count: counts.failed },
                ]}
              />
              <SearchBox value={search} onChange={setSearch} placeholder="Search tasks" label="Search tasks" />
            </div>

            {tasks.length === 0 ? (
              <Empty message="No tasks yet" hint="Assign one above. It appears here and runs in the background." />
            ) : visible.length === 0 ? (
              <Empty message="Nothing matches" hint="Try another filter or search term." />
            ) : (
              visible.map((task, i) => {
                const employee = names.get(task.employee_id);
                const running = task.status === "running" || task.status === "queued";
                const isSelected = task.id === selected;
                return (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => select(task.id)}
                    aria-current={isSelected}
                    className={`slide-in flex w-full flex-col gap-2.5 rounded-2xl border bg-panel px-4 py-3.5 text-left transition-[transform,border-color,box-shadow] duration-300 hover:-translate-y-0.5 hover:shadow-lift ${
                      isSelected ? "border-accent shadow-[0_0_0_3px_var(--accent-soft)]" : "border-line hover:border-accent-line"
                    }`}
                    style={{ animationDelay: `${Math.min(i, 8) * 0.04}s` }}
                  >
                    <span className="flex w-full items-center gap-2.5">
                      <span className="min-w-0 flex-1 truncate text-[15px] font-medium">{task.title ?? "Untitled"}</span>
                      <StatusChip status={task.status} />
                    </span>
                    <span className="flex w-full items-center gap-2 text-[13px] text-muted">
                      <Avatar name={employee?.name ?? "?"} size={20} />
                      {employee?.name ?? "Unknown"}
                      <span className="ml-auto font-mono text-xs text-dim" title={formatDateTime(task.created_at)}>
                        {relativeTime(task.created_at)}
                      </span>
                    </span>
                    {running && <span className="scan-bar block w-full" />}
                  </button>
                );
              })
            )}
          </section>

          {selected ? (
            <RunPanel
              key={selected}
              taskId={selected}
              names={names}
              onChanged={() => {
                void loadTasks();
                notifyActivity();
              }}
            />
          ) : tasks?.length ? (
            <Empty message="Pick a task" hint="Its live run appears here." />
          ) : null}
        </div>
      </PageBody>
    </>
  );
}

// ----------------------------------------------------------- run panel

type View = "timeline" | "tree" | "result";

function RunPanel({
  taskId,
  names,
  onChanged,
}: {
  taskId: string;
  names: Map<string, EmployeeListItem>;
  onChanged: () => void;
}) {
  const { org } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) || "timeline";
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const closeStream = useRef<(() => void) | null>(null);

  function setView(next: View) {
    const copy = new URLSearchParams(params);
    if (next === "timeline") copy.delete("view");
    else copy.set("view", next);
    setParams(copy, { replace: true });
  }

  useEffect(() => {
    if (!org) return;
    setEvents([]);
    let cancelled = false;

    void (async () => {
      const loaded = await api.get<Task>(`/orgs/${org.id}/tasks/${taskId}`);
      if (cancelled) return;
      setTask(loaded);
      if (!loaded.run) return;

      // Always load the history first, then stream. A task that
      // finished before this page opened still shows its full trace.
      const trace = await api.get<{ events: RunEvent[] }>(`/orgs/${org.id}/runs/${loaded.run.id}/trace`);
      if (cancelled) return;
      setEvents(trace.events);

      if (["running", "awaiting_approval", "queued"].includes(loaded.run.status)) {
        const lastSeq = trace.events.at(-1)?.seq ?? 0;
        closeStream.current = streamRun(
          org.id,
          loaded.run.id,
          (event) => {
            setEvents((previous) => [...previous, event]);
            // A finishing event changes the totals and the result: refresh them.
            if (["run_finished", "run_stopped", "provider_error"].includes(event.type)) {
              void api.get<Task>(`/orgs/${org.id}/tasks/${taskId}`).then((t) => {
                if (!cancelled) setTask(t);
              });
              onChanged();
            }
          },
          lastSeq,
        );
      }
    })();

    return () => {
      cancelled = true;
      closeStream.current?.();
      closeStream.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org, taskId]);

  async function cancel() {
    if (!org || !task) return;
    await api.post(`/orgs/${org.id}/tasks/${task.id}/cancel`);
    setTask(await api.get<Task>(`/orgs/${org.id}/tasks/${task.id}`));
    onChanged();
    toast("Run cancelled.", "info");
  }

  if (!task) {
    return (
      <div className="card p-2">
        <Spinner rows={4} />
      </div>
    );
  }

  const running = ["queued", "running"].includes(task.status);
  const manager = names.get(task.employee_id)?.name ?? "AI Employee";
  const delegations = events.filter((e) => e.type === "tool_call" && e.tool === "delegate_to_specialist").length;

  return (
    <section className="card rise overflow-hidden" aria-label="Run">
      <div className="flex flex-col gap-3.5 border-b border-line px-5 pb-4 pt-5">
        <div className="flex items-start gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <h2 className="font-display text-[19px] font-semibold tracking-[-0.015em]">{task.title ?? "Untitled"}</h2>
            <p className="whitespace-pre-wrap text-sm leading-normal text-muted">{task.input}</p>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <StatusChip status={task.status} />
            {task.dry_run && <Chip tone="brand">dry run</Chip>}
          </div>
        </div>

        {task.run && (
          <div className="grid grid-cols-3 gap-2.5">
            <Stat label="Steps" value={String(task.run.step_count)} />
            <Stat label="AI usage (tokens)" value={(task.run.prompt_tokens + task.run.output_tokens).toLocaleString("en-IN")} />
            {/* Estimated, not billed: with BYOK we never see their invoice. */}
            <Stat label="Est. cost" value={`~$${Number(task.run.estimated_cost_usd).toFixed(4)}`} />
          </div>
        )}

        <Tabs
          label="Run view"
          value={view}
          onChange={setView}
          items={[
            { key: "timeline", label: "Timeline", count: events.length },
            { key: "tree", label: "Agent tree", count: delegations },
            { key: "result", label: "Result" },
          ]}
        />
      </div>

      <div className="px-5 py-4">
        {view === "timeline" && <Timeline events={events} running={running} />}
        {view === "tree" && (
          <AgentTree
            events={events}
            managerName={manager}
            taskTitle={task.title ?? "Untitled"}
            runStatus={task.run?.status ?? task.status}
          />
        )}
        {view === "result" &&
          (task.run?.output ? (
            <div className="rounded-xl border border-line bg-sunken p-4">
              <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{task.run.output}</p>
            </div>
          ) : (
            <Empty
              message={running ? "No result yet" : "No result"}
              hint={running ? `${manager} writes the result when the run finishes.` : "This run ended without one."}
            />
          ))}
        {task.run?.error_message && (
          <div className="mt-3">
            <ErrorNote message={task.run.error_message} />
          </div>
        )}
      </div>

      {running && (
        <div className="flex gap-2.5 border-t border-line px-5 py-3.5">
          <Button variant="ghost" onClick={() => void cancel()}>
            Cancel run
          </Button>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <div className="text-xs text-dim">{label}</div>
      <div className="truncate font-mono text-[17px]">{value}</div>
    </div>
  );
}

// ------------------------------------------------------------ timeline

const EVENT_LABELS: Record<string, string> = {
  run_started: "Started",
  thinking: "Thinking",
  llm_call: "Asked the AI",
  tool_call: "Using a tool",
  tool_result: "Got the result",
  tool_blocked: "Not allowed by your Permissions",
  approval_requested: "Waiting for a person to approve",
  approval_granted: "Approved",
  parallel_started: "Running in parallel",
  run_finished: "Finished",
  run_stopped: "Stopped",
  provider_error: "The AI service returned an error",
};

const STOP_CAUSES: Record<string, string> = {
  max_steps: "hit its step limit",
  max_tokens: "hit its usage limit",
  timeout: "took longer than 10 minutes",
  cancelled: "cancelled by a person",
  provider_not_connected: "no AI key is connected",
  provider_error: "the AI service failed",
  rejected: "a person said no",
  expired: "nobody approved in time",
};

/** The row's headline: the plain name of the tool when there is one. */
function eventTitle(event: RunEvent): string {
  const tool = typeof event.tool === "string" ? toolLabel(event.tool) : null;
  if (tool && event.type === "tool_call" && event.tool !== "delegate_to_specialist") return tool;
  if (tool && event.type === "tool_result") return event.ok === false ? `Didn't work: ${tool}` : `Done: ${tool}`;
  if (tool && event.type === "tool_blocked") return `Not allowed: ${tool}`;
  if (tool && event.type === "approval_requested") return `Waiting for approval: ${tool}`;
  if (event.type === "tool_call" && event.tool === "delegate_to_specialist") return "Asked a colleague";
  return EVENT_LABELS[event.type] ?? event.type;
}

/** The technical detail, kept for the curious as a tooltip. */
function eventTechnical(event: RunEvent): string {
  return [event.type, event.tool, event.model, event.prompt_tokens != null ? `${Number(event.prompt_tokens) + Number(event.output_tokens ?? 0)} tokens` : null]
    .filter(Boolean)
    .join(" · ");
}

function eventStyle(event: RunEvent): { tone: "run" | "ok" | "ask" | "bad" | "brand" | "mute"; icon?: IconName } {
  if (event.tool === "delegate_to_specialist" && event.type === "tool_call") return { tone: "brand", icon: "tree" };
  switch (event.type) {
    case "tool_blocked":
    case "provider_error":
      return { tone: "bad", icon: "x" };
    case "tool_result":
      return event.ok === false ? { tone: "bad" } : { tone: "mute" };
    case "approval_requested":
      return { tone: "ask", icon: "approvals" };
    case "approval_granted":
    case "run_finished":
      return { tone: "ok", icon: "check" };
    case "run_stopped":
      return { tone: "bad", icon: "x" };
    case "parallel_started":
      return { tone: "brand", icon: "tree" };
    default:
      return { tone: "mute" };
  }
}

function eventDetail(event: RunEvent): string {
  const args = (event.arguments ?? {}) as Record<string, unknown>;
  if (event.tool === "delegate_to_specialist" && event.type === "tool_call") {
    return `asked ${String(args.specialist_name ?? "a specialist")}`;
  }
  if (event.type === "parallel_started") return `${event.count} at once`;
  if (event.type === "llm_call") return event.latency_ms ? `answered in ${(Number(event.latency_ms) / 1000).toFixed(1)} s` : "";
  if (event.type === "tool_call") {
    // The one argument that says what this step is about.
    const key = ["url", "query", "to", "subject", "file_id", "content"].find((k) => typeof args[k] === "string");
    return key ? String(args[key]).slice(0, 90) : "";
  }
  if (event.type === "tool_result") return event.ok === false ? String(event.error ?? "it reported a problem") : "";
  if (event.type === "run_stopped" || event.type === "run_finished") {
    return event.cause && event.cause !== "completed" ? STOP_CAUSES[String(event.cause)] ?? String(event.cause) : "";
  }
  return [event.reason, event.error].filter(Boolean).join(" · ");
}

const TONE_STEP: Record<string, string> = {
  run: "bg-run-soft border-run text-run-text",
  ok: "bg-ok-soft border-ok text-ok-text",
  ask: "bg-ask-soft border-ask text-ask-text",
  bad: "bg-bad-soft border-bad text-bad-text",
  brand: "bg-accent-soft border-accent-line text-accent-text",
  mute: "bg-raised border-line2 text-dim",
};

function Timeline({ events, running }: { events: RunEvent[]; running: boolean }) {
  const end = useRef<HTMLLIElement>(null);

  // Keep the newest step in view while the run is live.
  useEffect(() => {
    if (running) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [events.length, running]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col gap-3 py-2">
        <div className="flex items-center gap-3.5">
          <span className="halo h-10 w-10 shrink-0 rounded-xl p-[1.5px]">
            <span className="flex h-full w-full items-center justify-center rounded-[10.5px] bg-panel">
              <Icon name="spinner" size={16} className="spin text-accent-text" />
            </span>
          </span>
          <span className="text-sm text-muted">Waiting for the worker to pick this up…</span>
        </div>
      </div>
    );
  }

  return (
    <ol className="relative flex max-h-[30rem] flex-col gap-0.5 overflow-y-auto pr-1">
      <li aria-hidden="true" className="absolute bottom-6 left-[19px] top-6 w-0.5" style={{ background: "linear-gradient(var(--line2),var(--run))" }} />
      {events.map((event, i) => {
        const style = eventStyle(event);
        const last = i === events.length - 1;
        const live = last && running;
        const detail = eventDetail(event);
        return (
          <li key={event.seq} className="slide-in relative flex gap-3.5 py-1.5" style={{ animationDelay: `${Math.min(i, 10) * 0.03}s` }}>
            {live ? (
              <span className="halo relative h-10 w-10 shrink-0 rounded-xl p-[1.5px]">
                <span className="flex h-full w-full items-center justify-center rounded-[10.5px] bg-run-soft font-mono text-xs text-run-text">
                  {event.seq}
                </span>
              </span>
            ) : (
              <span className={`relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border font-mono text-xs ${TONE_STEP[style.tone]}`}>
                {style.icon ? <Icon name={style.icon} size={17} /> : event.seq}
              </span>
            )}
            <div className="flex min-w-0 flex-col gap-0.5 pt-0.5" title={eventTechnical(event)}>
              <span className={`text-sm font-medium ${live ? "text-run-text" : ""}`}>
                {eventTitle(event)}
                {live && <span className="caret">_</span>}
              </span>
              {detail && <span className="truncate text-xs text-muted">{detail}</span>}
            </div>
          </li>
        );
      })}
      <li ref={end} aria-hidden="true" />
    </ol>
  );
}

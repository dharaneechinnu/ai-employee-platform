import { useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Spinner,
  TextArea,
  statusTone,
} from "../components/ui";
import {
  ApiError,
  api,
  streamRun,
  type EmployeeList,
  type RunEvent,
  type Task,
  type TaskListItem,
} from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Phase 4. Assigning a task returns immediately; the run happens in a
 * worker and arrives here as a live event stream.
 *
 * The timeline is the screen that matters: it is the difference
 * between watching an agent work and staring at a spinner.
 */
export default function Tasks() {
  const { org } = useAuth();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeList | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!org) return;
    setTasks(await api.get<TaskListItem[]>(`/orgs/${org.id}/tasks`));
    const list = await api.get<EmployeeList>(`/orgs/${org.id}/ai-employees`);
    setEmployees(list);
    if (!employeeId && list.items.length) setEmployeeId(list.items[0].id);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function assign(e: React.FormEvent) {
    e.preventDefault();
    if (!org || !employeeId) return;
    setError(null);
    try {
      const task = await api.post<Task>(`/orgs/${org.id}/tasks`, {
        employee_id: employeeId,
        input,
      });
      setInput("");
      setSelected(task.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not assign that.");
    }
  }

  if (!tasks || !employees) return <Spinner />;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
      <div className="space-y-4">
        <Card>
          <form onSubmit={assign} className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs text-neutral-400">AI Employee</span>
              <select
                value={employeeId}
                onChange={(e) => setEmployeeId(e.target.value)}
                className="w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
              >
                {employees.items.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.name}
                  </option>
                ))}
              </select>
            </label>
            <TextArea
              label="What should it do?"
              value={input}
              onChange={setInput}
              rows={3}
              placeholder="Look at bug 42 and suggest a fix"
            />
            <ErrorNote message={error} />
            <Button type="submit" disabled={!input.trim() || !employees.items.length}>
              Assign
            </Button>
          </form>
        </Card>

        {tasks.length === 0 ? (
          <Empty message="No tasks yet." />
        ) : (
          <div className="space-y-2">
            {tasks.map((task) => (
              <button
                key={task.id}
                onClick={() => setSelected(task.id)}
                className={`w-full rounded-lg border p-3 text-left transition ${
                  selected === task.id
                    ? "border-sky-700 bg-neutral-900"
                    : "border-neutral-800 hover:bg-neutral-900"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm">{task.title ?? "Untitled"}</span>
                  <Badge tone={statusTone(task.status)}>{task.status}</Badge>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div>{selected ? <RunTimeline taskId={selected} /> : <Empty message="Pick a task." />}</div>
    </div>
  );
}

function RunTimeline({ taskId }: { taskId: string }) {
  const { org } = useAuth();
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const closeStream = useRef<(() => void) | null>(null);

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
      const trace = await api.get<{ events: RunEvent[] }>(
        `/orgs/${org.id}/runs/${loaded.run.id}/trace`,
      );
      if (cancelled) return;
      setEvents(trace.events);

      if (["running", "awaiting_approval"].includes(loaded.run.status)) {
        const lastSeq = trace.events.at(-1)?.seq ?? 0;
        closeStream.current = streamRun(
          org.id,
          loaded.run.id,
          (event) => setEvents((previous) => [...previous, event]),
          lastSeq,
        );
      }
    })();

    return () => {
      cancelled = true;
      closeStream.current?.();
      closeStream.current = null;
    };
  }, [org, taskId]);

  async function cancel() {
    if (!org || !task) return;
    await api.post(`/orgs/${org.id}/tasks/${task.id}/cancel`);
    setTask(await api.get<Task>(`/orgs/${org.id}/tasks/${task.id}`));
  }

  if (!task) return <Spinner />;

  const running = ["queued", "running"].includes(task.status);

  return (
    <Card className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm">{task.title}</p>
          <p className="mt-1 text-xs text-neutral-500">{task.input}</p>
        </div>
        <Badge tone={statusTone(task.status)}>{task.status}</Badge>
      </div>

      {task.run && (
        <div className="flex flex-wrap gap-3 border-y border-neutral-800 py-2 text-xs text-neutral-400">
          <span>{task.run.step_count} steps</span>
          <span>{task.run.prompt_tokens + task.run.output_tokens} tokens</span>
          {/* Estimated, not billed: with BYOK we never see their invoice. */}
          <span>~${Number(task.run.estimated_cost_usd).toFixed(4)} est.</span>
        </div>
      )}

      <div className="max-h-[26rem] space-y-1.5 overflow-y-auto">
        {events.length === 0 ? (
          <p className="text-xs text-neutral-600">Waiting for the worker…</p>
        ) : (
          events.map((event) => <EventRow key={event.seq} event={event} />)
        )}
      </div>

      {task.run?.output && (
        <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
          <p className="mb-1 text-xs text-neutral-500">Result</p>
          <p className="whitespace-pre-wrap text-sm">{task.run.output}</p>
        </div>
      )}

      {task.run?.error_message && <ErrorNote message={task.run.error_message} />}

      {running && (
        <Button variant="ghost" onClick={() => void cancel()}>
          Cancel
        </Button>
      )}
    </Card>
  );
}

const EVENT_LABELS: Record<string, string> = {
  run_started: "Started",
  thinking: "Thinking",
  llm_call: "Model call",
  tool_call: "Using tool",
  tool_result: "Tool result",
  tool_blocked: "Blocked by policy",
  approval_requested: "Waiting for approval",
  approval_granted: "Approved",
  parallel_started: "Running in parallel",
  run_finished: "Finished",
  run_stopped: "Stopped",
  provider_error: "Provider error",
};

function EventRow({ event }: { event: RunEvent }) {
  const tone =
    event.type === "tool_blocked" || event.type === "provider_error"
      ? "red"
      : event.type === "approval_requested"
        ? "amber"
        : event.type === "run_finished"
          ? "green"
          : "gray";

  const detail = [event.tool, event.model, event.cause, event.reason]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="w-6 shrink-0 text-right text-neutral-700">{event.seq}</span>
      <Badge tone={tone}>{EVENT_LABELS[event.type] ?? event.type}</Badge>
      {detail && <span className="truncate text-neutral-500">{String(detail)}</span>}
    </div>
  );
}

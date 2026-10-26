import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AgentTree from "../components/agents/AgentTree";
import FlowCost from "../components/agents/FlowCost";
import ReadinessList from "../components/agents/ReadinessList";
import ScheduleEditor from "../components/agents/ScheduleEditor";
import StarterSetup from "../components/agents/StarterSetup";
import ToolPicker from "../components/agents/ToolPicker";
import { Icon } from "../components/icons";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  HoldButton,
  Input,
  PageBody,
  PageHeader,
  Spinner,
  StatusChip,
  Tabs,
  TextArea,
  relativeTime,
  useToast,
} from "../components/ui";
import { fmtCost } from "../lib/agents";
import { groupKey, groupTitle } from "../lib/labels";
import {
  ApiError,
  api,
  type Agent,
  type AgentSchedule,
  type AgentsOverview,
  type Readiness,
  type RunNowResult,
} from "../lib/api";

type Tab = "agents" | "tree" | "flow";

const START_A_REQUEST = "I want an agent that ";

/**
 * AI Agents: manage the helpers you have made, see how they work
 * together and what they cost. Agents are made in Chat, by describing
 * one; this is where they are scheduled, run, paused and edited.
 */
export default function Agents() {
  const toast = useToast();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("agents");
  const [data, setData] = useState<AgentsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [settingUp, setSettingUp] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get<AgentsOverview>("/me/agents/overview"));
      setError(null);
    } catch {
      setError("Could not load your agents.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A run that is going is worth watching: pick up its result when it ends.
  const running = data?.agents.some((a) => a.last_status === "running") ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  function describeInChat() {
    navigate("/chat", { state: { prefill: START_A_REQUEST } });
  }

  const packOf = Object.fromEntries((data?.tools ?? []).map((t) => [t.name, t.pack]));

  async function chatWith(agent: Agent) {
    try {
      // The agent's own chat: its runs and what you say to it are in one place.
      const chat = await api.post<{ conversation_id: string }>(`/me/agents/${agent.id}/chat`, {});
      navigate(`/chat/${chat.conversation_id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start a chat.");
    }
  }

  async function remove(agent: Agent) {
    await api.del(`/me/agents/${agent.id}`);
    toast(`${agent.name} removed. Chats that used it are kept.`);
    await load();
  }

  return (
    <>
      <PageHeader title="AI Agents">
        <Button icon="plus" size="sm" onClick={describeInChat}>
          New agent in Chat
        </Button>
      </PageHeader>
      <PageBody>
        <Tabs
          label="AI Agents sections"
          value={tab}
          onChange={setTab}
          items={[
            { key: "agents", label: "My agents", count: data?.agents.length },
            { key: "tree", label: "Agent tree" },
            { key: "flow", label: "Flow and cost" },
          ]}
        />
        <ErrorNote message={error} />
        {!data && !error && <Spinner rows={4} />}

        {data && tab === "agents" && (
          <div className="flex flex-col gap-6">
            {data.agents.length === 0 ? (
              <Empty
                message="No agents yet."
                hint="Describe one in Chat, for example: I want an agent that finds Chennai developer events every night and updates my sheet."
              >
                <Button icon="chat" onClick={describeInChat}>
                  Describe one in Chat
                </Button>
              </Empty>
            ) : (
              <ul className="grid gap-4 md:grid-cols-2">
                {data.agents.map((agent) => (
                  <li key={agent.id}>
                    {editing === agent.id ? (
                      <Editor
                        agent={agent}
                        data={data}
                        onDone={async (changed) => {
                          setEditing(null);
                          if (changed) await load();
                        }}
                      />
                    ) : (
                      <AgentCard
                        agent={agent}
                        packs={packOf}
                        onChat={() => void chatWith(agent)}
                        onEdit={() => setEditing(agent.id)}
                        onRemove={() => void remove(agent)}
                        onChanged={load}
                      />
                    )}
                  </li>
                ))}
              </ul>
            )}

            <section className="flex flex-col gap-3">
              <h2 className="font-display text-[16px] font-semibold">Built in</h2>
              <p className="text-[13.5px] text-muted">
                Pick one, say what it should do, choose when it runs, and start it. No need to find it afterwards.
              </p>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {data.starters.map((s) =>
                  settingUp === s.key ? (
                    <li key={s.key} className="sm:col-span-2 lg:col-span-3">
                      <StarterSetup
                        starter={s}
                        onCancel={() => setSettingUp(null)}
                        onStarted={(conversationId) => navigate(`/chat/${conversationId}`)}
                        onCreated={async () => {
                          setSettingUp(null);
                          await load();
                          setTab("agents");
                        }}
                      />
                    </li>
                  ) : (
                    <li key={s.key} className="flex flex-col gap-2 rounded-xl border border-line p-3">
                      <div className="flex items-center gap-2">
                        <Icon name={s.kind === "mode" ? "chat" : "employees"} size={15} className="text-dim" />
                        <b className="text-[14px]">{s.name}</b>
                        <span className="text-[11.5px] uppercase tracking-wider text-dim">
                          {s.kind === "mode" ? "style" : "teammate"}
                        </span>
                      </div>
                      <p className="text-[13px] text-muted">{s.description}</p>
                      <Button size="sm" variant="ghost" className="self-start" onClick={() => setSettingUp(s.key)}>
                        Set up
                      </Button>
                    </li>
                  ),
                )}
              </ul>
            </section>
          </div>
        )}

        {data && tab === "tree" && (
          <AgentTree
            agents={data.agents}
            starters={data.starters}
            assistantUsage={data.assistant_usage}
            onOpen={(agent) => {
              setEditing(agent.id);
              setTab("agents");
            }}
          />
        )}

        {data && tab === "flow" && <FlowCost runs={data.recent_runs} agents={data.agents} />}
      </PageBody>
    </>
  );
}

// ----------------------------------------------------------------- one agent

/** "Works with: The web, Google Sheets", from the tools it was given. */
function worksWith(tools: string[] | null, packs: Record<string, string>): string {
  if (tools === null) return "Works with what you allow";
  const apps = [
    ...new Set(
      tools
        .map((t) => groupKey(packs[t] ?? ""))
        .filter((g) => g && g !== "basics")
        .map(groupTitle),
    ),
  ];
  return apps.length > 0 ? `Works with: ${apps.join(", ")}` : "Talks only, no outside tools";
}

function AgentCard({
  agent,
  packs,
  onChat,
  onEdit,
  onRemove,
  onChanged,
}: {
  agent: Agent;
  /** Which app each tool belongs to, to say what the agent works with. */
  packs: Record<string, string>;
  onChat: () => void;
  onEdit: () => void;
  onRemove: () => void;
  onChanged: () => Promise<void>;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [showReadiness, setShowReadiness] = useState(false);

  const scheduled = agent.schedule !== null;
  const attention = agent.last_status === "needs_attention";

  // A scheduled agent is checked as the card opens, so a broken link is
  // seen here and not discovered at the next run.
  const check = useCallback(async () => {
    try {
      setReadiness(await api.get<Readiness>(`/me/agents/${agent.id}/readiness`));
    } catch {
      setReadiness(null);
    }
  }, [agent.id]);

  useEffect(() => {
    if (scheduled || (agent.tools?.length ?? 0) > 0) void check();
  }, [check, scheduled, agent.tools]);

  const broken = readiness !== null && !readiness.ok;

  async function act(path: string, done: string) {
    setBusy(true);
    try {
      await api.post(`/me/agents/${agent.id}/${path}`, {});
      toast(done);
      await onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    setBusy(true);
    try {
      const result = await api.post<RunNowResult>(`/me/agents/${agent.id}/run`, {});
      if (result.status === "started" && result.conversation_id) {
        // Its output is written into its own chat, which also shows live.
        navigate(`/chat/${result.conversation_id}`);
        return;
      } else if (result.status === "busy") toast("It is still running its last job.");
      else {
        setReadiness(result.readiness);
        setShowReadiness(true);
        toast("It could not start. See what needs fixing on its card.");
      }
      await onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start it.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-start gap-3">
        <span className="agent-glyph" aria-hidden="true">
          {agent.name.charAt(0).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-display text-[16px] font-semibold">{agent.name}</h3>
          <p className="text-[13.5px] text-muted">{agent.description || "No description."}</p>
        </div>
        {agent.last_status && <StatusChip status={agent.last_status} />}
      </div>

      <p className="text-[12.5px] text-dim">
        {worksWith(agent.tools, packs)}
        {" · "}
        {agent.usage.runs} run{agent.usage.runs === 1 ? "" : "s"} · {fmtCost(agent.usage.cost_usd)}
      </p>

      {scheduled && (
        <div className="flex flex-col gap-1 rounded-xl border border-line bg-raised px-3 py-2 text-[13px]">
          <span className="flex items-center gap-2 font-medium">
            <Icon name="calendar" size={14} className="text-dim" />
            {agent.schedule_text}
            {!agent.schedule_enabled && <span className="text-ask-text">· paused</span>}
          </span>
          <span className="text-dim">
            {agent.schedule_enabled && agent.next_run_at ? `Next run ${relativeTime(agent.next_run_at)}` : "Not scheduled right now"}
            {agent.last_run_at ? ` · last run ${relativeTime(agent.last_run_at)}` : ""}
          </span>
        </div>
      )}

      {agent.last_summary && (
        <p className={`text-[13px] ${attention || agent.last_status === "failed" ? "text-bad-text" : "text-muted"}`}>
          {agent.last_summary.length > 220 ? `${agent.last_summary.slice(0, 220)}…` : agent.last_summary}
        </p>
      )}

      {(broken || showReadiness) && readiness && (
        <ReadinessList
          readiness={{ ...readiness, checks: readiness.checks.filter((c) => !c.ok) }}
          loading={false}
          onRecheck={() => void check()}
        />
      )}
      {!broken && readiness && scheduled && (
        <button
          type="button"
          className="self-start text-[12.5px] text-ok-text underline-offset-2 hover:underline"
          onClick={() => setShowReadiness((s) => !s)}
        >
          Everything it needs is ready
        </button>
      )}

      <div className="mt-auto flex flex-wrap gap-2">
        <Button
          size="sm"
          icon="arrow"
          disabled={busy}
          title="Run it now; the result is saved in its chat"
          onClick={() => void runNow()}
        >
          Run now
        </Button>
        {scheduled &&
          (agent.schedule_enabled ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act("pause", "Paused.")}>
              Pause
            </Button>
          ) : (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act("resume", "Resumed.")}>
              Resume
            </Button>
          ))}
        {agent.run_conversation_id && (
          <Link to={`/chat/${agent.run_conversation_id}`} className="btn btn-sm btn-ghost">
            Results
          </Link>
        )}
        <Button size="sm" variant="ghost" icon="chat" onClick={onChat}>
          Chat
        </Button>
        <Button size="sm" variant="ghost" onClick={onEdit}>
          Edit
        </Button>
        <HoldButton variant="danger-ghost" onConfirm={onRemove}>
          Hold to remove
        </HoldButton>
      </div>
    </Card>
  );
}

// --------------------------------------------------------------- editing

function Editor({
  agent,
  data,
  onDone,
}: {
  agent: Agent;
  data: AgentsOverview;
  onDone: (changed: boolean) => void | Promise<void>;
}) {
  const toast = useToast();
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [instructions, setInstructions] = useState(agent.instructions);
  const [tools, setTools] = useState<string[] | null>(agent.tools_auto ? null : agent.tools);
  const [schedule, setSchedule] = useState<AgentSchedule | null>(agent.schedule);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      // `schedule` is always sent: null is how it is switched off.
      await api.patch(`/me/agents/${agent.id}`, {
        name,
        description,
        instructions,
        tools,
        schedule,
      });
      toast("Saved.");
      await onDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <Input label="Name" value={name} onChange={setName} />
      <Input label="What it is for" value={description} onChange={setDescription} />
      <TextArea label="Instructions" value={instructions} onChange={setInstructions} rows={9} />
      <div className="rounded-xl border border-line bg-panel p-3">
        <ScheduleEditor value={schedule} onChange={setSchedule} />
      </div>
      <details className="rounded-xl border border-line px-3 py-2.5">
        <summary className="cursor-pointer text-[13.5px] text-muted">
          Advanced: choose its tools by hand
        </summary>
        <div className="mt-3">
          <ToolPicker
            tools={data.tools}
            value={tools}
            onChange={setTools}
            seed={agent.tools ?? []}
          />
        </div>
      </details>
      <ErrorNote message={error} />
      <div className="flex gap-2">
        <Button
          size="sm"
          icon="check"
          disabled={busy || !name.trim() || instructions.trim().length < 10}
          onClick={() => void save()}
        >
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void onDone(false)}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}

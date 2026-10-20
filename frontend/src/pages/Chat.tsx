import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Icon, type IconName } from "../components/icons";
import Prose from "../components/Prose";
import ProposedAction from "../components/ProposedAction";
import VoiceInput from "../components/VoiceInput";
import { Button, ErrorNote, relativeTime, useToast } from "../components/ui";
import {
  ApiError,
  api,
  streamRun,
  type Approval,
  type AssistantInfo,
  type ChatMessage,
  type ChatMode,
  type Conversation,
  type ConversationItem,
  type ModelOption,
  type RunEvent,
  type Task,
  type ToolEntry,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { effectLabel, learnToolLabels, modelLabel, packLabel, toolLabel } from "../lib/labels";

/**
 * The personal assistant: ChatGPT-style, on the agent loop.
 *
 * Every message is answered by a run, so the person can watch the steps
 * live, approve anything that changes the world, and stop it. A mode
 * says who they are (student, professional, researcher); the AI can be
 * switched mid-conversation; and with Team on, the assistant splits a
 * big question between specialists working at the same time.
 */

const MODE_ICON: Record<ChatMode, IconName> = {
  general: "chat",
  study: "info",
  work: "tasks",
  research: "search",
};

const ROLE_LABEL: Record<string, string> = {
  researcher: "Researcher",
  analyst: "Analyst",
  writer: "Writer",
  critic: "Critic",
};

const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);

interface Draft {
  mode: ChatMode;
  model: string;
  team: boolean;
  tools: string[] | null;
}

function greeting(name: string | null | undefined): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const first = name?.trim().split(/\s+/)[0];
  return first ? `${part}, ${first}` : part;
}

export default function Chat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { me } = useAuth();
  const toast = useToast();

  const [info, setInfo] = useState<AssistantInfo | null>(null);
  const [list, setList] = useState<ConversationItem[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [catalogue, setCatalogue] = useState<ToolEntry[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState<Draft>({ mode: "general", model: "auto", team: false, tools: null });
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // On a phone the conversation list is a drawer.
  const [listOpen, setListOpen] = useState(false);

  useEffect(() => setListOpen(false), [id]);

  const loadList = useCallback(async () => {
    setList(await api.get<ConversationItem[]>("/me/conversations"));
  }, []);

  useEffect(() => {
    void api.get<AssistantInfo>("/me/assistant").then(setInfo);
    void api.get<ModelOption[]>("/me/models").then(setModels).catch(() => setModels([]));
    void api
      .get<ToolEntry[]>("/me/tools")
      .then((tools) => {
        learnToolLabels(tools);
        setCatalogue(tools.filter((t) => !t.permanently_blocked && t.name !== "delegate_to_specialist"));
      })
      .catch(() => setCatalogue([]));
    void loadList();
  }, [loadList]);

  const loadConversation = useCallback(async (cid: string) => {
    try {
      const c = await api.get<Conversation>(`/me/conversations/${cid}`);
      setConversation(c);
      return c;
    } catch {
      setConversation(null);
      navigate("/chat", { replace: true });
      return null;
    }
  }, [navigate]);

  useEffect(() => {
    setError(null);
    if (id) void loadConversation(id);
    else setConversation(null);
  }, [id, loadConversation]);

  // The settings the composer shows: the open conversation's, or the
  // draft for a conversation not started yet.
  const settings: Draft = conversation
    ? { mode: conversation.mode, model: conversation.model, team: conversation.team, tools: conversation.tools }
    : draft;
  const modeInfo = info?.modes.find((m) => m.key === settings.mode);
  const tools = settings.tools ?? modeInfo?.suggested_tools.filter((t) => catalogue.some((c) => c.name === t)) ?? [];

  async function change(patch: Partial<Draft>) {
    if (!conversation) {
      setDraft((d) => ({ ...d, ...patch, tools: patch.mode && !patch.tools ? null : (patch.tools ?? d.tools) }));
      return;
    }
    try {
      const updated = await api.patch<Conversation>(`/me/conversations/${conversation.id}`, patch);
      setConversation(updated);
      if (patch.model) toast(`Next answer comes from ${modelLabel(patch.model)}.`, "info");
      void loadList();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    }
  }

  const busy = Boolean(conversation?.turn && ACTIVE.has(conversation.turn.status));

  async function send(content = text) {
    const message = content.trim();
    if (!message || sending || busy) return;
    setSending(true);
    setError(null);
    try {
      let current = conversation;
      if (!current) {
        current = await api.post<Conversation>("/me/conversations", {
          mode: draft.mode,
          model: draft.model,
          team: draft.team,
          tools: draft.tools ?? tools,
        });
      }
      await api.post(`/me/conversations/${current.id}/messages`, { content: message });
      setText("");
      if (current.id !== id) navigate(`/chat/${current.id}`);
      await loadConversation(current.id);
      void loadList();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send that.");
    } finally {
      setSending(false);
    }
  }

  async function stop() {
    if (!conversation?.turn) return;
    await api.post(`/me/tasks/${conversation.turn.task_id}/cancel`).catch(() => undefined);
  }

  async function remove(item: ConversationItem) {
    await api.del(`/me/conversations/${item.id}`);
    if (item.id === id) navigate("/chat");
    void loadList();
  }

  const onTurnSettled = useCallback(() => {
    if (id) void loadConversation(id);
    void loadList();
  }, [id, loadConversation, loadList]);

  const empty = !conversation || conversation.messages.length === 0;

  return (
    <div className="chat-shell">
      {listOpen && <button type="button" className="chat-scrim" aria-label="Close conversations" onClick={() => setListOpen(false)} />}
      <aside className={`chat-side ${listOpen ? "open" : ""}`} aria-label="Conversations">
        <Button
          className="w-full justify-center"
          icon="plus"
          onClick={() => {
            setDraft({ mode: settings.mode, model: settings.model, team: settings.team, tools: null });
            navigate("/chat");
          }}
          data-coach="chat-new"
        >
          New chat
        </Button>
        <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto pr-1">
          {list.length === 0 && <p className="px-2 py-3 text-[13px] text-dim">Your conversations appear here.</p>}
          {list.map((item) => (
            <div key={item.id} className={`chat-item group ${item.id === id ? "on" : ""}`}>
              <Link to={`/chat/${item.id}`} className="flex min-w-0 flex-1 items-center gap-2.5">
                <Icon name={MODE_ICON[item.mode]} size={15} className="shrink-0 text-dim" />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-[13.5px] text-ink">{item.title}</span>
                  <span className="truncate text-[11.5px] text-dim">
                    {relativeTime(item.updated_at)}
                    {item.team ? " · team" : ""}
                  </span>
                </span>
              </Link>
              <button
                type="button"
                className="chat-item-del"
                aria-label={`Delete ${item.title}`}
                onClick={() => void remove(item)}
              >
                <Icon name="x" size={14} />
              </button>
            </div>
          ))}
        </nav>
      </aside>

      <section className="chat-main">
        <header className="chat-topbar">
          <button type="button" className="icon-btn h-10 w-10" aria-label="Conversations" onClick={() => setListOpen(true)}>
            <Icon name="menu" />
          </button>
          <span className="min-w-0 flex-1 truncate text-[15px] font-medium">{conversation?.title ?? "New chat"}</span>
          <button type="button" className="icon-btn h-10 w-10" aria-label="New chat" onClick={() => navigate("/chat")}>
            <Icon name="plus" />
          </button>
        </header>
        <div className="chat-scroll">
          <div className="chat-column">
            {empty ? (
              <Welcome
                name={me?.full_name ?? null}
                info={info}
                mode={settings.mode}
                onMode={(mode) => void change({ mode })}
                onExample={(example) => setText(example)}
                hasAi={models.length > 0}
              />
            ) : (
              <Thread conversation={conversation!} onSettled={onTurnSettled} />
            )}
          </div>
        </div>

        <div className="chat-dock">
          <div className="chat-column">
            <ErrorNote message={error} />
            <Composer
              text={text}
              setText={setText}
              onSend={() => void send()}
              onStop={() => void stop()}
              busy={busy}
              sending={sending}
              settings={settings}
              tools={tools}
              info={info}
              models={models}
              catalogue={catalogue}
              onChange={(patch) => void change(patch)}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

// ------------------------------------------------------------- welcome

function Welcome({
  name,
  info,
  mode,
  onMode,
  onExample,
  hasAi,
}: {
  name: string | null;
  info: AssistantInfo | null;
  mode: ChatMode;
  onMode: (mode: ChatMode) => void;
  onExample: (text: string) => void;
  hasAi: boolean;
}) {
  const current = info?.modes.find((m) => m.key === mode);
  return (
    <div className="flex flex-col gap-7 pb-6 pt-[8vh]">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">
          {greeting(name)}
        </h1>
        <p className="text-[15px] text-muted">
          Ask anything. Your assistant can use your tools, work through problems step by step, and bring in a team of
          specialists for bigger questions.
        </p>
      </div>

      {!hasAi && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-ask/40 bg-ask-soft px-4 py-3 text-[14px]">
          <Icon name="warn" className="text-ask-text" />
          <span className="flex-1">Connect an AI first: Claude, ChatGPT, Gemini, or your own model.</span>
          <Link to="/providers" className="btn btn-sm btn-ghost">
            Connect an AI
          </Link>
        </div>
      )}

      <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr))]" role="radiogroup" aria-label="Mode">
        {info?.modes.map((m) => (
          <button
            key={m.key}
            type="button"
            role="radio"
            aria-checked={m.key === mode}
            className={`chat-mode ${m.key === mode ? "on" : ""}`}
            onClick={() => onMode(m.key)}
          >
            <Icon name={MODE_ICON[m.key]} size={18} />
            <span className="text-[14px] font-semibold text-ink">{m.label}</span>
            <span className="text-[12.5px] leading-snug text-muted">{m.for_whom}</span>
          </button>
        ))}
      </div>

      {current && (
        <div className="flex flex-col gap-2">
          <span className="text-[12px] font-medium uppercase tracking-[0.06em] text-dim">Try</span>
          <div className="flex flex-col gap-1.5">
            {current.examples.map((example) => (
              <button key={example} type="button" className="chat-example" onClick={() => onExample(example)}>
                <Icon name="arrow" size={14} className="text-dim" />
                {example}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- thread

function Thread({ conversation, onSettled }: { conversation: Conversation; onSettled: () => void }) {
  const end = useRef<HTMLDivElement>(null);
  const turn = conversation.turn;
  const live = turn && ACTIVE.has(turn.status) ? turn : null;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [conversation.messages.length, live?.status]);

  // Pair each message with its reply; the open turn has none yet.
  const replies = new Map(
    conversation.messages.filter((m) => m.role === "assistant" && m.task_id).map((m) => [m.task_id!, m]),
  );

  return (
    <div className="flex flex-col gap-7 py-8">
      {conversation.messages
        .filter((m) => m.role === "user")
        .map((m) => {
          const reply = m.task_id ? replies.get(m.task_id) : undefined;
          return (
            <div key={m.id} className="flex flex-col gap-4">
              <div className="chat-user">{m.content}</div>
              {reply ? (
                <Reply message={reply} team={conversation.team} />
              ) : live && live.task_id === m.task_id ? (
                <LiveTurn turn={live} onSettled={onSettled} />
              ) : null}
            </div>
          );
        })}
      <div ref={end} />
    </div>
  );
}

function Reply({ message, team }: { message: ChatMessage; team: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="chat-reply">
      <div className="flex items-center gap-2 text-[12.5px] text-dim">
        <span className="chat-avatar" aria-hidden="true">
          <Icon name="sparkle" size={13} />
        </span>
        <span className="font-medium text-muted">Assistant</span>
        {message.model && <span>· {modelLabel(message.model)}</span>}
      </div>
      {message.error ? (
        <div className="rounded-xl border border-bad/30 bg-bad-soft px-4 py-3 text-[14px] text-bad-text">{message.error}</div>
      ) : (
        <div className="chat-answer">
          <Prose text={message.content} />
        </div>
      )}
      {message.task_id && (
        <div className="flex flex-col gap-2">
          <button type="button" className="chat-how" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <Icon name={team ? "tree" : "terminal"} size={13} />
            {open ? "Hide how I worked this out" : "How I worked this out"}
          </button>
          {open && <Trace taskId={message.task_id} />}
        </div>
      )}
    </div>
  );
}

/** A finished turn's steps, loaded on demand. */
function Trace({ taskId }: { taskId: string }) {
  const [events, setEvents] = useState<RunEvent[] | null>(null);
  const [cost, setCost] = useState<string | null>(null);
  useEffect(() => {
    void (async () => {
      const task = await api.get<Task>(`/me/tasks/${taskId}`);
      if (!task.run) return setEvents([]);
      const r = task.run;
      setCost(`${r.step_count} ${r.step_count === 1 ? "step" : "steps"} · ${(r.prompt_tokens + r.output_tokens).toLocaleString()} tokens · ~$${Number(r.estimated_cost_usd).toFixed(4)}`);
      const trace = await api.get<{ events: RunEvent[] }>(`/me/runs/${task.run.id}/trace`);
      setEvents(trace.events.map(flatten));
    })();
  }, [taskId]);
  if (!events) return <div className="skeleton h-16 rounded-xl" />;
  return (
    <div className="flex flex-col gap-2">
      <Steps events={events} live={false} />
      {cost && <span className="pl-1 font-mono text-[11.5px] text-dim">{cost}</span>}
    </div>
  );
}

function flatten(e: RunEvent): RunEvent {
  const { payload, ...rest } = e as RunEvent & { payload?: Record<string, unknown> };
  return { ...(payload ?? {}), ...rest } as RunEvent;
}

/** The turn being answered now: its steps stream in, and an approval it waits on appears inline. */
function LiveTurn({
  turn,
  onSettled,
}: {
  turn: NonNullable<Conversation["turn"]>;
  onSettled: () => void;
}) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [deciding, setDeciding] = useState(false);
  const seen = useRef(0);

  // Poll the conversation lightly while the turn is open: it is what
  // tells us the run id (once a worker picks it up) and when it ends.
  useEffect(() => {
    const timer = window.setInterval(onSettled, turn.status === "awaiting_approval" ? 4000 : 1500);
    return () => window.clearInterval(timer);
  }, [onSettled, turn.status]);

  useEffect(() => {
    if (!turn.run_id) return;
    let closed = false;
    void api.get<{ events: RunEvent[] }>(`/me/runs/${turn.run_id}/trace`).then((trace) => {
      if (closed) return;
      const flat = trace.events.map(flatten);
      seen.current = flat.at(-1)?.seq ?? 0;
      setEvents(flat);
    });
    const close = streamRun(turn.run_id, (event) => {
      if (event.seq <= seen.current) return;
      seen.current = event.seq;
      setEvents((current) => [...current, event]);
      if (["run_finished", "run_stopped", "approval_requested"].includes(event.type)) {
        window.setTimeout(onSettled, 300);
      }
    });
    return () => {
      closed = true;
      close();
    };
  }, [turn.run_id, onSettled]);

  useEffect(() => {
    if (turn.status !== "awaiting_approval" || !turn.run_id) return setApproval(null);
    void api.get<Approval[]>("/me/approvals").then((all) => setApproval(all.find((a) => a.run_id === turn.run_id) ?? null));
  }, [turn.status, turn.run_id]);

  async function decide(approve: boolean) {
    if (!approval) return;
    setDeciding(true);
    try {
      await api.post(`/me/approvals/${approval.id}/${approve ? "approve" : "reject"}`);
      setApproval(null);
      onSettled();
    } finally {
      setDeciding(false);
    }
  }

  return (
    <div className="chat-reply">
      <div className="flex items-center gap-2 text-[12.5px] text-dim">
        <span className="chat-avatar is-live" aria-hidden="true">
          <Icon name="sparkle" size={13} />
        </span>
        <span className="font-medium text-muted">Assistant</span>
        <span>· {turn.status === "awaiting_approval" ? "waiting for you" : turn.run_id ? "working" : "starting"}</span>
      </div>
      <Steps events={events} live />
      {approval && (
        <div className="flex flex-col gap-3 rounded-xl border border-ask/40 bg-ask-soft/60 p-4" data-coach="chat-approval">
          <div className="flex items-center gap-2 text-[14px]">
            <Icon name="approvals" className="text-ask-text" />
            <span>
              Wants to <b className="font-semibold">{toolLabel(approval.tool_name).toLowerCase()}</b>
              <span className="text-dim"> · {effectLabel(approval.side_effect).toLowerCase()}</span>
            </span>
          </div>
          <ProposedAction values={approval.proposed} />
          <div className="flex gap-2">
            <Button size="sm" variant="ok" icon="check" disabled={deciding} onClick={() => void decide(true)}>
              Approve
            </Button>
            <Button size="sm" variant="danger-ghost" disabled={deciding} onClick={() => void decide(false)}>
              Reject
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------- steps

interface Specialist {
  id: string;
  role: string;
  task: string;
  state: "working" | "done" | "failed";
  steps: string[];
}

/** What happened, in plain words: tool steps for the lead, and a card per specialist when the team works. */
function Steps({ events, live }: { events: RunEvent[]; live: boolean }) {
  const { lead, team } = useMemo(() => summarise(events), [events]);
  const finished = events.some((e) => e.type === "run_finished" || e.type === "run_stopped");
  // Paused for a person: nothing is thinking until they decide.
  const last = events.filter((e) => e.type === "approval_requested" || e.type === "approval_granted").at(-1);
  const waiting = last?.type === "approval_requested";
  return (
    <div className="chat-steps" data-coach="chat-steps">
      {lead.map((step, i) => (
        <div key={i} className="chat-step">
          <span className={`chat-step-dot ${step.tone}`}>
            <Icon name={step.icon} size={11} strokeWidth={2.6} />
          </span>
          <span className="min-w-0 flex-1 truncate">{step.text}</span>
        </div>
      ))}
      {team.length > 0 && (
        <div className="chat-team" data-coach="chat-team">
          {team.map((s) => (
            <div key={s.id} className={`chat-specialist ${s.state}`}>
              <div className="flex items-center gap-2">
                <span className="chat-role">{ROLE_LABEL[s.role] ?? s.role}</span>
                <span className="ml-auto text-[11.5px] text-dim">
                  {s.state === "working" ? "working…" : s.state === "done" ? "done" : "could not finish"}
                </span>
              </div>
              <p className="line-clamp-2 text-[12.5px] leading-snug text-muted">{s.task}</p>
              {s.steps.length > 0 && <p className="truncate text-[11.5px] text-dim">{s.steps.join(" · ")}</p>}
            </div>
          ))}
        </div>
      )}
      {live && !finished && !waiting && (
        <div className="chat-step">
          <span className="chat-step-dot run">
            <Icon name="spinner" size={11} className="spin" />
          </span>
          <span className="text-muted">{team.some((s) => s.state === "working") ? "The team is working…" : "Thinking…"}</span>
        </div>
      )}
    </div>
  );
}

function summarise(events: RunEvent[]) {
  const lead: { text: string; icon: IconName; tone: string }[] = [];
  const team = new Map<string, Specialist>();
  for (const e of events) {
    const tool = typeof e.tool === "string" ? e.tool : null;
    if (e.type === "specialist_started") {
      team.set(String(e.id), { id: String(e.id), role: String(e.role), task: String(e.task ?? ""), state: "working", steps: [] });
    } else if (e.type === "specialist_step" && e.kind === "tool_call" && e.tool) {
      team.get(String(e.id))?.steps.push(toolLabel(String(e.tool)));
    } else if (e.type === "specialist_finished") {
      const s = team.get(String(e.id));
      if (s) s.state = e.ok ? "done" : "failed";
    } else if (e.type === "parallel_started") {
      lead.push({ text: `Running ${String(e.count)} steps at the same time`, icon: "tree", tone: "brand" });
    } else if (e.type === "tool_call" && tool && tool !== "ask_specialist") {
      lead.push({ text: toolLabel(tool), icon: "check", tone: "ok" });
    } else if (e.type === "tool_blocked" && tool) {
      lead.push({ text: `Not allowed: ${toolLabel(tool)}`, icon: "x", tone: "bad" });
    } else if (e.type === "approval_requested" && tool) {
      lead.push({ text: `Needs your approval: ${toolLabel(tool)}`, icon: "approvals", tone: "ask" });
    } else if (e.type === "approval_granted") {
      lead.push({ text: "You approved", icon: "check", tone: "ok" });
    } else if (e.type === "provider_error") {
      lead.push({ text: "The AI service returned an error", icon: "warn", tone: "bad" });
    }
  }
  const specialists = [...team.values()];
  if (specialists.length > 0) {
    lead.unshift({
      text: `Split the work between ${specialists.length} specialist${specialists.length > 1 ? "s" : ""}`,
      icon: "tree",
      tone: "brand",
    });
  }
  return { lead, team: specialists };
}

// ------------------------------------------------------------ composer

function Composer({
  text,
  setText,
  onSend,
  onStop,
  busy,
  sending,
  settings,
  tools,
  info,
  models,
  catalogue,
  onChange,
}: {
  text: string;
  setText: (t: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  sending: boolean;
  settings: Draft;
  tools: string[];
  info: AssistantInfo | null;
  models: ModelOption[];
  catalogue: ToolEntry[];
  onChange: (patch: Partial<Draft>) => void;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  const modelOptions = [
    { value: "auto", label: "Automatic" },
    ...models.map((m) => ({ value: `${m.provider_key}:${m.model}`, label: `${m.display_name} · ${m.model}` })),
  ];
  if (!modelOptions.some((o) => o.value === settings.model)) {
    modelOptions.push({ value: settings.model, label: modelLabel(settings.model) });
  }

  return (
    <div className="chat-composer" data-coach="chat-composer">
      <textarea
        ref={box}
        rows={1}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSend();
          }
        }}
        placeholder={busy ? "Wait for the answer, or stop it…" : "Message your assistant"}
        aria-label="Message"
        className="chat-input"
      />
      {voiceError && <p className="px-1 text-[12px] text-bad-text">{voiceError}</p>}
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="chat-pill" title="How the assistant works with you">
          <Icon name={MODE_ICON[settings.mode]} size={14} />
          <span className="sr-only">Mode</span>
          <select
            value={settings.mode}
            onChange={(e) => onChange({ mode: e.target.value as ChatMode })}
            aria-label="Mode"
            data-coach="chat-mode"
          >
            {info?.modes.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="chat-pill" title="Which AI answers. You can switch at any time.">
          <Icon name="providers" size={14} />
          <span className="sr-only">AI model</span>
          <select
            value={settings.model}
            onChange={(e) => onChange({ model: e.target.value })}
            aria-label="AI model"
            data-coach="chat-model"
          >
            {modelOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          className={`chat-pill ${settings.team ? "on" : ""}`}
          aria-pressed={settings.team}
          onClick={() => onChange({ team: !settings.team })}
          title="Let the assistant split big questions between specialists working at the same time"
          data-coach="chat-team-toggle"
        >
          <Icon name="tree" size={14} />
          Team
        </button>

        <div className="relative">
          <button
            type="button"
            className={`chat-pill ${tools.length ? "on-soft" : ""}`}
            aria-expanded={toolsOpen}
            onClick={() => setToolsOpen((o) => !o)}
            data-coach="chat-tools"
          >
            <Icon name="sparkle" size={14} />
            Tools{tools.length ? ` · ${tools.length}` : ""}
          </button>
          {toolsOpen && (
            <ToolsMenu
              catalogue={catalogue}
              chosen={tools}
              onClose={() => setToolsOpen(false)}
              onChange={(next) => onChange({ tools: next })}
            />
          )}
        </div>

        <span className="flex-1" />
        <VoiceInput onText={(t) => setText(text ? `${text} ${t}` : t)} onError={setVoiceError} />
        {busy ? (
          <button type="button" className="chat-send stop" onClick={onStop} aria-label="Stop">
            <Icon name="stop" size={16} />
          </button>
        ) : (
          <button
            type="button"
            className="chat-send"
            onClick={onSend}
            disabled={!text.trim() || sending}
            aria-label="Send"
          >
            <Icon name={sending ? "spinner" : "arrow"} size={17} strokeWidth={2.4} className={sending ? "spin" : "-rotate-90"} />
          </button>
        )}
      </div>
    </div>
  );
}

function ToolsMenu({
  catalogue,
  chosen,
  onChange,
  onClose,
}: {
  catalogue: ToolEntry[];
  chosen: string[];
  onChange: (tools: string[]) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);

  const set = new Set(chosen);
  const packs = [...new Set(catalogue.map((t) => t.pack))];
  return (
    <div ref={ref} className="chat-menu" role="dialog" aria-label="Tools for this conversation">
      <p className="px-3 pb-1 pt-2.5 text-[12px] text-dim">
        Tools this conversation may use. Your Permissions still apply.
      </p>
      <div className="max-h-[300px] overflow-y-auto pb-1.5">
        {packs.map((pack) => (
          <div key={pack} className="flex flex-col">
            <span className="px-3 pb-0.5 pt-2 text-[11px] font-medium uppercase tracking-[0.06em] text-dim">{packLabel(pack)}</span>
            {catalogue
              .filter((t) => t.pack === pack)
              .map((t) => (
                <label key={t.name} className="flex cursor-pointer items-center gap-2.5 px-3 py-1.5 text-[13.5px] hover:bg-raised">
                  <input
                    type="checkbox"
                    className="accent-[var(--accent)]"
                    checked={set.has(t.name)}
                    onChange={(e) => {
                      const next = new Set(set);
                      if (e.target.checked) next.add(t.name);
                      else next.delete(t.name);
                      onChange([...next]);
                    }}
                  />
                  <span className="flex-1 truncate">{toolLabel(t.name)}</span>
                  {t.side_effect !== "read" && <span className="text-[11px] text-dim">{effectLabel(t.side_effect)}</span>}
                </label>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}

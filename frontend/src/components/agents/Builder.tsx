import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  type Agent,
  type AgentDraft,
  type AgentToolInfo,
  type ChatMessage,
  type Conversation,
} from "../../lib/api";
import { Icon } from "../icons";
import Prose from "../Prose";
import { Button, ErrorNote, TextArea, useToast } from "../ui";

const IDEAS = [
  "A study buddy that quizzes me on what I just learned",
  "A weekly digest writer that turns my notes into five bullets",
  "A code reviewer that checks pull requests for risky changes",
  "A polite email drafter for chasing late payments",
];

const REMEMBER = "agents.builder";

function forget() {
  try {
    localStorage.removeItem(REMEMBER);
  } catch {
    /* ignore */
  }
}

/**
 * Making an agent by talking.
 *
 * The builder is an ordinary conversation in builder mode, so it uses
 * the person's own AI and costs what any chat costs. Its only tool
 * shows a draft; the draft appears as a card, and nothing exists until
 * the person presses Create. That button, not the model, is the
 * confirmation.
 */
export default function Builder({
  tools,
  onCreated,
}: {
  tools: AgentToolInfo[];
  onCreated: (agent: Agent) => void;
}) {
  const toast = useToast();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Record<string, string>>({});
  const bottom = useRef<HTMLDivElement>(null);

  const working = conversation?.turn != null && !["completed", "failed", "cancelled"].includes(conversation.turn.status);

  const refresh = useCallback(async (id: string) => {
    const loaded = await api.get<Conversation>(`/me/conversations/${id}`);
    setConversation(loaded);
    try {
      localStorage.setItem(REMEMBER, id);
    } catch {
      /* private window: the chat simply starts fresh next time */
    }
  }, []);

  // Pick up where the person left off, so a half-made agent survives a reload.
  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(REMEMBER);
    } catch {
      /* ignore */
    }
    if (saved) void refresh(saved).catch(() => forget());
  }, [refresh]);

  // Follow the builder's reply until it settles.
  useEffect(() => {
    if (!conversation || !working) return;
    const timer = window.setInterval(() => void refresh(conversation.id), 1200);
    return () => window.clearInterval(timer);
  }, [conversation, working, refresh]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [conversation?.messages.length, working]);

  async function send(content: string) {
    const message = content.trim();
    if (!message || busy) return;
    setBusy(true);
    setError(null);
    try {
      let current = conversation;
      if (!current) {
        // `builder` is not one of the chat modes, so it is sent as is.
        current = await api.post<Conversation>("/me/conversations", { mode: "builder" });
      }
      await api.post(`/me/conversations/${current.id}/messages`, { content: message });
      setText("");
      await refresh(current.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send that. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function create(message: ChatMessage, draft: AgentDraft) {
    try {
      const agent = await api.post<Agent>("/me/agents", draft);
      setCreated((c) => ({ ...c, [message.id]: agent.name }));
      toast(`${agent.name} is ready.`);
      onCreated(agent);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the agent.");
    }
  }

  function startOver() {
    forget();
    setConversation(null);
    setCreated({});
    setError(null);
  }

  const messages = conversation?.messages ?? [];

  return (
    <div className="flex flex-col gap-4" data-coach="agent-builder">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-[18px] font-semibold">Describe the agent you want</h2>
          <p className="text-[14px] text-muted">
            Say what it should do. I will ask what I need, then show you a draft to create, change or throw away.
          </p>
        </div>
        {conversation && (
          <Button variant="ghost" size="sm" onClick={startOver}>
            Start over
          </Button>
        )}
      </div>

      <div className="flex min-h-[280px] flex-col gap-4 rounded-2xl border border-line bg-panel p-4 sm:p-5">
        {messages.length === 0 && !working && (
          <div className="flex flex-col gap-3">
            <p className="text-[14px] text-dim">Try one of these, or write your own:</p>
            <div className="flex flex-wrap gap-2">
              {IDEAS.map((idea) => (
                <button
                  key={idea}
                  type="button"
                  className="agent-idea"
                  disabled={busy}
                  onClick={() => void send(idea)}
                >
                  {idea}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="chat-user">
              {message.content}
            </div>
          ) : (
            <div key={message.id} className="chat-reply">
              {message.error ? (
                <ErrorNote message={message.error} />
              ) : (
                message.content && (
                  <div className="chat-answer">
                    <Prose text={message.content} />
                  </div>
                )
              )}
              {message.draft && (
                <DraftCard
                  draft={message.draft}
                  tools={tools}
                  createdAs={created[message.id] ?? null}
                  isLatest={message.id === messages.filter((m) => m.draft).at(-1)?.id}
                  onCreate={(draft) => void create(message, draft)}
                />
              )}
            </div>
          ),
        )}

        {working && (
          <div className="flex items-center gap-2 text-[13px] text-dim" aria-live="polite">
            <span className="chat-avatar is-live" aria-hidden="true">
              <Icon name="sparkle" size={13} />
            </span>
            Designing your agent…
          </div>
        )}
        <div ref={bottom} />
      </div>

      <ErrorNote message={error} />

      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
      >
        <TextArea
          label="Your message"
          value={text}
          onChange={setText}
          rows={2}
          placeholder={conversation ? "Ask for a change, or answer a question…" : "An agent that…"}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(text);
            }
          }}
        />
        <div className="flex justify-end">
          <Button type="submit" icon="arrow" disabled={busy || working || !text.trim()}>
            {conversation ? "Send" : "Start designing"}
          </Button>
        </div>
      </form>
    </div>
  );
}

/**
 * The agent the builder proposed, as something to read and change
 * before it exists. Only the newest draft in a thread can be created,
 * so an old one cannot be made by accident after it was replaced.
 */
function DraftCard({
  draft,
  tools,
  createdAs,
  isLatest,
  onCreate,
}: {
  draft: AgentDraft;
  tools: AgentToolInfo[];
  createdAs: string | null;
  isLatest: boolean;
  onCreate: (draft: AgentDraft) => void;
}) {
  const [name, setName] = useState(draft.name);
  const [description, setDescription] = useState(draft.description);
  const [instructions, setInstructions] = useState(draft.instructions);
  const [picked, setPicked] = useState<string[] | null>(draft.tools);
  const [open, setOpen] = useState(false);

  const known = new Map(tools.map((t) => [t.name, t]));
  const everything = picked === null;

  function toggle(tool: string) {
    const base = picked ?? [];
    setPicked(base.includes(tool) ? base.filter((t) => t !== tool) : [...base, tool]);
  }

  return (
    <div className={`agent-draft ${createdAs ? "is-made" : ""} ${isLatest ? "" : "is-old"}`}>
      <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wider text-dim">
        <Icon name={createdAs ? "check" : "sparkle"} size={14} />
        {createdAs ? "Created" : isLatest ? "Draft" : "Earlier draft"}
      </div>

      <input
        aria-label="Agent name"
        className="agent-draft-name"
        value={name}
        maxLength={80}
        disabled={!!createdAs}
        onChange={(e) => setName(e.target.value)}
      />
      <input
        aria-label="What it is for"
        className="agent-draft-line"
        value={description}
        maxLength={300}
        disabled={!!createdAs}
        onChange={(e) => setDescription(e.target.value)}
      />

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-medium text-dim">Tools it may use</span>
        <div className="flex flex-wrap gap-1.5">
          {everything && <span className="agent-tool is-on">Everything you allow</span>}
          {(picked ?? []).map((tool) => (
            <button
              key={tool}
              type="button"
              className="agent-tool is-on"
              disabled={!!createdAs}
              title={known.get(tool)?.description ?? "Not one of your tools right now"}
              onClick={() => toggle(tool)}
            >
              {tool}
              {!createdAs && <Icon name="x" size={12} />}
            </button>
          ))}
          {picked !== null && picked.length === 0 && (
            <span className="text-[13px] text-dim">None: it will only talk.</span>
          )}
        </div>
        {!createdAs && (
          <details className="text-[13px] text-muted">
            <summary className="cursor-pointer select-none text-dim">Change tools</summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button type="button" className={`agent-tool ${everything ? "is-on" : ""}`} onClick={() => setPicked(null)}>
                Everything you allow
              </button>
              {tools.map((t) => (
                <button
                  key={t.name}
                  type="button"
                  title={t.description}
                  className={`agent-tool ${picked?.includes(t.name) ? "is-on" : ""}`}
                  onClick={() => toggle(t.name)}
                >
                  {t.name}
                  {t.side_effect !== "read" && <span className="text-ask-text"> · {t.side_effect}</span>}
                </button>
              ))}
            </div>
          </details>
        )}
        <p className="text-[12px] text-dim">
          Your Permissions still apply: an agent can use fewer tools than you allow, never more.
        </p>
      </div>

      <button type="button" className="text-left text-[13px] text-dim underline-offset-2 hover:underline" onClick={() => setOpen((o) => !o)}>
        {open ? "Hide the instructions" : "Read or change the instructions"}
      </button>
      {open && (
        <TextArea
          label="Instructions"
          value={instructions}
          onChange={setInstructions}
          rows={7}
          disabled={!!createdAs}
        />
      )}

      {createdAs ? (
        <p className="text-[13px] text-ok-text">
          {createdAs} is in your list. Open it from the Agents tab to chat with it.
        </p>
      ) : (
        isLatest && (
          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              icon="check"
              disabled={!name.trim() || instructions.trim().length < 10}
              onClick={() => onCreate({ name: name.trim(), description, instructions, tools: picked })}
            >
              Create agent
            </Button>
            <span className="self-center text-[13px] text-dim">or ask for a change below</span>
          </div>
        )
      )}
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AgentTree from "../components/agents/AgentTree";
import Builder from "../components/agents/Builder";
import FlowCost from "../components/agents/FlowCost";
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
  Tabs,
  TextArea,
  useToast,
} from "../components/ui";
import { fmtCost } from "../lib/agents";
import { ApiError, api, type Agent, type AgentStarter, type AgentsOverview, type Conversation } from "../lib/api";

type Tab = "build" | "agents" | "tree" | "flow";

/**
 * AI Agents: make helpers by talking, manage them, see how they work
 * together and what they cost. Chat stays the home screen; this is
 * where the helpers it can use are designed.
 */
export default function Agents() {
  const toast = useToast();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("build");
  const [data, setData] = useState<AgentsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

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

  async function chatWith(agent: Agent) {
    try {
      const chat = await api.post<Conversation>("/me/conversations", { agent_id: agent.id });
      navigate(`/chat/${chat.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start a chat.");
    }
  }

  async function remove(agent: Agent) {
    await api.del(`/me/agents/${agent.id}`);
    toast(`${agent.name} removed. Chats that used it are kept.`);
    await load();
  }

  async function copyStarter(starter: AgentStarter) {
    try {
      await api.post("/me/agents", {
        name: `My ${starter.name}`,
        description: starter.description,
        instructions: starter.instructions,
      });
      toast(`Copied. Change it under My agents.`);
      await load();
      setTab("agents");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not copy that.");
    }
  }

  return (
    <>
      <PageHeader title="AI Agents">
        <Button icon="plus" size="sm" onClick={() => setTab("build")}>
          New agent
        </Button>
      </PageHeader>
      <PageBody>
        <Tabs
          label="AI Agents sections"
          value={tab}
          onChange={setTab}
          items={[
            { key: "build", label: "Build by chat" },
            { key: "agents", label: "My agents", count: data?.agents.length },
            { key: "tree", label: "Agent tree" },
            { key: "flow", label: "Flow and cost" },
          ]}
        />
        <ErrorNote message={error} />
        {!data && !error && <Spinner rows={4} />}

        {data && tab === "build" && (
          <Builder
            tools={data.tools}
            onCreated={() => {
              void load();
            }}
          />
        )}

        {data && tab === "agents" && (
          <div className="flex flex-col gap-6">
            {data.agents.length === 0 ? (
              <Empty message="No agents yet." hint="Describe one in the Build tab and it will show up here.">
                <Button icon="plus" onClick={() => setTab("build")}>
                  Build one by chat
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
                      <Card className="flex h-full flex-col gap-3 p-4">
                        <div className="flex items-start gap-3">
                          <span className="agent-glyph" aria-hidden="true">
                            {agent.name.charAt(0).toUpperCase()}
                          </span>
                          <div className="min-w-0 flex-1">
                            <h3 className="truncate font-display text-[16px] font-semibold">{agent.name}</h3>
                            <p className="text-[13.5px] text-muted">{agent.description || "No description."}</p>
                          </div>
                        </div>
                        <p className="text-[12.5px] text-dim">
                          {agent.tools === null
                            ? "Uses every tool you allow"
                            : agent.tools.length === 0
                              ? "Talks only, no tools"
                              : `Tools: ${agent.tools.join(", ")}`}
                          {" · "}
                          {agent.usage.runs} run{agent.usage.runs === 1 ? "" : "s"} · {fmtCost(agent.usage.cost_usd)}
                        </p>
                        <div className="mt-auto flex flex-wrap gap-2">
                          <Button size="sm" icon="chat" onClick={() => void chatWith(agent)}>
                            Chat with it
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditing(agent.id)}>
                            Edit
                          </Button>
                          <HoldButton variant="danger-ghost" onConfirm={() => void remove(agent)}>
                            Hold to remove
                          </HoldButton>
                        </div>
                      </Card>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <section className="flex flex-col gap-3">
              <h2 className="font-display text-[16px] font-semibold">Built in</h2>
              <p className="text-[13.5px] text-muted">
                These ship with the product. Copy one to make it yours, then change it.
              </p>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {data.starters.map((s) => (
                  <li key={s.key} className="flex flex-col gap-2 rounded-xl border border-line p-3">
                    <div className="flex items-center gap-2">
                      <Icon name={s.kind === "mode" ? "chat" : "employees"} size={15} className="text-dim" />
                      <b className="text-[14px]">{s.name}</b>
                      <span className="text-[11.5px] uppercase tracking-wider text-dim">
                        {s.kind === "mode" ? "style" : "teammate"}
                      </span>
                    </div>
                    <p className="text-[13px] text-muted">{s.description}</p>
                    <Button size="sm" variant="ghost" className="self-start" onClick={() => void copyStarter(s)}>
                      Make my own copy
                    </Button>
                  </li>
                ))}
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
  const [tools, setTools] = useState<string[] | null>(agent.tools);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(tool: string) {
    const base = tools ?? [];
    setTools(base.includes(tool) ? base.filter((t) => t !== tool) : [...base, tool]);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/me/agents/${agent.id}`, { name, description, instructions, tools });
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
      <TextArea label="Instructions" value={instructions} onChange={setInstructions} rows={7} />
      <div className="flex flex-col gap-1.5">
        <span className="label">Tools it may use</span>
        <div className="flex flex-wrap gap-1.5">
          <button type="button" className={`agent-tool ${tools === null ? "is-on" : ""}`} onClick={() => setTools(null)}>
            Everything you allow
          </button>
          {data.tools.map((t) => (
            <button
              key={t.name}
              type="button"
              title={t.description}
              className={`agent-tool ${tools?.includes(t.name) ? "is-on" : ""}`}
              onClick={() => toggle(t.name)}
            >
              {t.name}
            </button>
          ))}
        </div>
      </div>
      <ErrorNote message={error} />
      <div className="flex gap-2">
        <Button size="sm" icon="check" disabled={busy || !name.trim() || instructions.trim().length < 10} onClick={() => void save()}>
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void onDone(false)}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}

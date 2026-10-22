import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  api,
  type Agent,
  type AgentDraft,
  type AgentSchedule,
  type AgentToolInfo,
  type AgentsOverview,
  type Readiness,
} from "../../lib/api";
import { Icon } from "../icons";
import { Button, ErrorNote, TextArea, useToast } from "../ui";
import ReadinessList from "./ReadinessList";
import ScheduleEditor from "./ScheduleEditor";

/**
 * The agent the assistant designed in Chat, as something to read, change
 * and check before it exists. Nothing is saved until Create is pressed,
 * and Create stays off while any link in the chain behind the agent is
 * broken: an agent that cannot do its job is not worth making.
 *
 * Only the newest draft in a thread can be created, so an old one cannot
 * be made by accident after it was replaced.
 */
export default function DraftCard({
  draft,
  isLatest,
  createdAs,
  onCreated,
}: {
  draft: AgentDraft;
  isLatest: boolean;
  createdAs: string | null;
  onCreated: (agent: Agent) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(draft.name);
  const [description, setDescription] = useState(draft.description);
  const [instructions, setInstructions] = useState(draft.instructions);
  const [picked, setPicked] = useState<string[] | null>(draft.tools);
  const [schedule, setSchedule] = useState<AgentSchedule | null>(draft.schedule ?? null);
  const [sheet, setSheet] = useState(draft.spreadsheet ?? "");
  const [open, setOpen] = useState(false);
  const [tools, setTools] = useState<AgentToolInfo[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<Agent | null>(null);

  const locked = !!createdAs || !!made;
  const everything = picked === null;
  const known = new Map(tools.map((t) => [t.name, t]));

  // The list of tools, only to name them and let the person change them.
  useEffect(() => {
    void api
      .get<AgentsOverview>("/me/agents/overview")
      .then((o) => setTools(o.tools))
      .catch(() => undefined);
  }, []);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      setReadiness(
        await api.post<Readiness>("/me/agents/readiness", {
          tools: picked ?? [],
          scheduled: schedule !== null,
          scope: { sheet_ids: sheet.trim() ? [sheet.trim()] : [] },
        }),
      );
    } catch {
      setReadiness({ ok: false, checks: [] });
    } finally {
      setChecking(false);
    }
  }, [picked, schedule, sheet]);

  // Asked again whenever what the agent needs changes, after a short pause.
  useEffect(() => {
    if (locked) return;
    const timer = window.setTimeout(() => void check(), 400);
    return () => window.clearTimeout(timer);
  }, [check, locked]);

  // Coming back from the Connections page in another tab.
  useEffect(() => {
    if (locked) return;
    const onFocus = () => void check();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [check, locked]);

  function toggle(tool: string) {
    const base = picked ?? [];
    setPicked(base.includes(tool) ? base.filter((t) => t !== tool) : [...base, tool]);
  }

  const needsTools = schedule !== null && picked === null;
  const canCreate =
    !busy && !!name.trim() && instructions.trim().length >= 10 && !needsTools && !!readiness?.ok && !checking;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const agent = await api.post<Agent>("/me/agents", {
        name: name.trim(),
        description,
        instructions,
        tools: picked,
        schedule,
        scope: { sheet_ids: sheet.trim() ? [sheet.trim()] : [] },
      });
      setMade(agent);
      toast(`${agent.name} is ready.`);
      onCreated(agent);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the agent.");
    } finally {
      setBusy(false);
    }
  }

  const makesItsOwn = (picked ?? []).includes("sheets_create");
  const writesToSheet =
    makesItsOwn || (picked ?? []).some((t) => t === "sheets_append_rows" || t === "sheets_update_cells");

  return (
    <div className={`agent-draft ${locked ? "is-made" : ""} ${isLatest || locked ? "" : "is-old"}`} data-coach="agent-draft">
      <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wider text-dim">
        <Icon name={locked ? "check" : "sparkle"} size={14} />
        {locked ? "Created" : isLatest ? "Draft agent" : "Earlier draft"}
      </div>

      <input
        aria-label="Agent name"
        className="agent-draft-name"
        value={name}
        maxLength={80}
        disabled={locked}
        onChange={(e) => setName(e.target.value)}
      />
      <input
        aria-label="What it is for"
        className="agent-draft-line"
        value={description}
        maxLength={300}
        disabled={locked}
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
              disabled={locked}
              title={known.get(tool)?.description ?? "Not one of your tools right now"}
              onClick={() => toggle(tool)}
            >
              {tool}
              {!locked && <Icon name="x" size={12} />}
            </button>
          ))}
          {picked !== null && picked.length === 0 && <span className="text-[13px] text-dim">None: it will only talk.</span>}
        </div>
        {!locked && (
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

      <div className="flex flex-col gap-2 rounded-xl border border-line bg-panel p-3">
        <ScheduleEditor value={schedule} onChange={setSchedule} disabled={locked} />
        {needsTools && (
          <p className="text-[13px] text-bad-text">
            An agent that runs on its own needs a list of tools. Pick the ones it should use above.
          </p>
        )}
      </div>

      {(writesToSheet || sheet) && (
        <label className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-dim">
            {makesItsOwn ? "A spreadsheet to start from (optional)" : "The one spreadsheet it may write to"}
          </span>
          <input
            className="field"
            placeholder="Paste the sheet's address"
            value={sheet}
            disabled={locked}
            onChange={(e) => setSheet(e.target.value)}
          />
          <span className="text-[12px] text-dim">
            {makesItsOwn
              ? "Leave it empty and the agent creates a new sheet on its first run, then keeps using that one."
              : "It cannot read or change any other spreadsheet."}
          </span>
        </label>
      )}

      {!locked && isLatest && (
        <div className="flex flex-col gap-2">
          <span className="text-[12px] font-medium text-dim">Can it really do this?</span>
          <ReadinessList readiness={readiness} loading={checking} onRecheck={() => void check()} />
        </div>
      )}

      <button
        type="button"
        className="text-left text-[13px] text-dim underline-offset-2 hover:underline"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide the instructions" : "Read or change the instructions"}
      </button>
      {open && <TextArea label="Instructions" value={instructions} onChange={setInstructions} rows={10} disabled={locked} />}

      <ErrorNote message={error} />

      {locked ? (
        <p className="text-[13px] text-ok-text">
          {createdAs ?? made?.name} is saved.{" "}
          <Link to="/agents" className="underline underline-offset-2">
            Manage it under AI Agents
          </Link>
          {made?.schedule_text ? `. It runs: ${made.schedule_text}.` : "."}
        </p>
      ) : (
        isLatest && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button icon="check" disabled={!canCreate} onClick={() => void create()}>
              Create agent
            </Button>
            <span className="text-[13px] text-dim">
              {!readiness?.ok && readiness ? "Create turns on when everything above is ready." : "or ask for a change below"}
            </span>
          </div>
        )
      )}
    </div>
  );
}

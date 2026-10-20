import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "../components/icons";
import { ToolPicker } from "../components/ToolPicker";
import {
  Avatar,
  Button,
  Chip,
  Empty,
  ErrorNote,
  Input,
  PageBody,
  PageHeader,
  Select,
  Spinner,
  StatusChip,
  Switch,
  TextArea,
  UsageMeter,
  useToast,
} from "../components/ui";
import { ApiError, api, type Employee, type EmployeeList, type Template } from "../lib/api";
import { AUTO_CHOICES, aiChoiceLabel, aiChoiceValue, modelLabel, parseAiChoice } from "../lib/labels";

type ModelChoice = { provider_key: string; display_name: string; model: string };

/**
 * Phase 2. The creation form asks three guided questions rather than
 * offering one empty instructions box: the people using this are sales
 * and HR, and "be helpful" produces a bad worker they then blame the
 * product for.
 */

const TEMPLATE_ICONS: IconName[] = ["terminal", "chat", "search", "sparkle"];

export default function Employees() {
  const toast = useToast();

  const [list, setList] = useState<EmployeeList | null>(null);
  const [details, setDetails] = useState<Record<string, Employee>>({});
  const [templates, setTemplates] = useState<Template[]>([]);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [does, setDoes] = useState("");
  const [never, setNever] = useState("");
  const [askHuman, setAskHuman] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  // The employee whose tools are open for editing, if any.
  const [editing, setEditing] = useState<Employee | null>(null);
  const [editTools, setEditTools] = useState<string[]>([]);
  const [editModel, setEditModel] = useState("auto");
  const [models, setModels] = useState<ModelChoice[]>([]);
  const firstField = useRef<HTMLDivElement>(null);

  async function load() {
    const loaded = await api.get<EmployeeList>(`/me/ai-employees`);
    setList(loaded);
    setTemplates(await api.get<Template[]>(`/me/templates`));

    // The list omits configuration; each card's one-line description
    // and tool count come from the detail record.
    const entries = await Promise.all(
      loaded.items.map((item) =>
        api
          .get<Employee>(`/me/ai-employees/${item.id}`)
          .then((detail) => [item.id, detail] as const)
          .catch(() => null),
      ),
    );
    setDetails(Object.fromEntries(entries.filter((e): e is readonly [string, Employee] => e !== null)));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, ["me"]);

  function openForm(template?: Template) {
    const guided = template?.config.guided;
    setName(template?.name ?? "");
    setJobTitle("");
    setDoes(guided?.what_it_does ?? "");
    setNever(guided?.what_it_must_never_do ?? "");
    setAskHuman(guided?.when_to_ask_a_human ?? "");
    setTools(template?.config.enabled_tools ?? []);
    setError(null);
    setEditing(null);
    setCreating(true);
    window.setTimeout(() => firstField.current?.querySelector("input")?.focus(), 50);
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("create");
    try {
      await api.post(`/me/ai-employees`, {
        name,
        job_title: jobTitle || null,
        config: {
          guided: {
            what_it_does: does,
            what_it_must_never_do: never || null,
            when_to_ask_a_human: askHuman || null,
          },
          enabled_tools: tools,
        },
      });
      setCreating(false);
      toast(`${name} created as a draft. Switch it on when you are ready.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create it.");
    } finally {
      setBusy(null);
    }
  }

  function openTools(employee: Employee) {
    setCreating(false);
    setError(null);
    setEditing(employee);
    setEditTools(employee.config.enabled_tools);
    setEditModel(aiChoiceValue(employee.config.model, employee.config.routing));
    {
      void api
        .get<ModelChoice[]>(`/me/models`)
        .then(setModels)
        .catch(() => setModels([]));
    }
  }

  async function saveTools() {
    if (!editing) return;
    setBusy("tools");
    setError(null);
    try {
      // PATCH replaces the whole configuration, so send it all back
      // with only the tool list changed.
      await api.patch(`/me/ai-employees/${editing.id}`, {
        config: { ...editing.config, enabled_tools: editTools, ...parseAiChoice(editModel) },
      });
      const chosen = parseAiChoice(editModel);
      toast(`Saved. ${editing.name} has ${editTools.length} tools and uses ${aiChoiceLabel(chosen.model, chosen.routing)}.`);
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the tools.");
    } finally {
      setBusy(null);
    }
  }

  async function setActive(id: string, displayName: string, on: boolean) {
    setBusy(id);
    try {
      await api.post(`/me/ai-employees/${id}/${on ? "activate" : "pause"}`);
      toast(on ? `${displayName} is active.` : `${displayName} is paused.`, on ? "ok" : "info");
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  if (!list) {
    return (
      <>
        <PageHeader crumb="Work" title="AI Employees" />
        <Spinner />
      </>
    );
  }

  const atLimit = list.used >= list.limit;
  const visible = list.items.filter((e) => e.status !== "archived");

  return (
    <>
      <PageHeader crumb="Work" title="AI Employees">
        <UsageMeter used={list.used} limit={list.limit} label="Seats" />
        {!creating && (
          <Button icon="plus" onClick={() => openForm()} disabled={atLimit} title={atLimit ? "Every seat is in use" : undefined} data-coach="new-employee">
            New AI Employee
          </Button>
        )}
      </PageHeader>

      <PageBody>
        {atLimit && (
          <div className="flex items-center gap-2.5 rounded-xl bg-ask-soft px-4 py-3 text-sm text-ask-text">
            <Icon name="warn" />
            Every seat is in use. Archive one, or ask support to raise your limit.
          </div>
        )}

        <div className="flex flex-wrap items-start gap-5">
          <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-6">
            {visible.length === 0 ? (
              <Empty
                message="No AI Employees yet"
                hint={true ? "Start from a template below, or create one from scratch." : "An admin needs to create one."}
              />
            ) : (
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(280px,100%),1fr))]">
                {visible.map((employee, i) => {
                  const detail = details[employee.id];
                  const on = employee.status === "active";
                  return (
                    <article
                      key={employee.id}
                      className="card lift rise flex flex-col gap-3.5 p-5"
                      style={{ animationDelay: `${i * 0.06}s` }}
                      data-coach="employee-card"
                    >
                      <div className="flex items-center gap-3.5">
                        <Avatar name={employee.name} size={52} rounded="rounded-2xl" muted={!on} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-display text-lg font-semibold">{employee.name}</div>
                          <div className="truncate text-[13px] text-muted">
                            {[employee.job_title, employee.department].filter(Boolean).join(" · ") || "No job title"}
                          </div>
                        </div>
                        {(
                          <span data-coach="employee-switch" className="flex">
                          <Switch
                            checked={on}
                            disabled={busy === employee.id}
                            onChange={(next) => void setActive(employee.id, employee.name, next)}
                            label={on ? `Pause ${employee.name}` : `Activate ${employee.name}`}
                          />
                          </span>
                        )}
                      </div>
                      <p className="line-clamp-3 min-h-[1.5em] text-sm leading-relaxed text-muted">
                        {detail?.config.guided?.what_it_does || (detail ? "No description yet." : "…")}
                      </p>
                      <div className="mt-auto flex flex-wrap items-center gap-2">
                        <StatusChip status={employee.status} />
                        {detail && (
                          <span className="ml-auto text-xs text-dim">
                            {aiChoiceLabel(detail.config.model, detail.config.routing)} · {detail.config.enabled_tools.length} tools
                          </span>
                        )}
                        {detail && (
                          <Button size="sm" variant="ghost" icon="sparkle" onClick={() => openTools(detail)} data-coach="employee-tools">
                            Tools &amp; AI
                          </Button>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}

            {templates.length > 0 && (
              <section className="flex flex-col gap-3" data-coach="templates">
                <h2 className="font-display text-[17px] font-semibold">Start from a template</h2>
                <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr))]">
                  {templates.map((template, i) => (
                    <button
                      key={template.id}
                      type="button"
                      onClick={() => openForm(template)}
                      disabled={atLimit}
                      className="card lift flex items-center gap-3.5 p-4 text-left disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
                        <Icon name={TEMPLATE_ICONS[i % TEMPLATE_ICONS.length]} size={20} />
                      </span>
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="flex items-center gap-2 font-medium">
                          {template.name}
                          {!template.is_platform_template && <Chip tone="brand" dot={false}>yours</Chip>}
                        </span>
                        <span className="line-clamp-2 text-[13px] text-muted">{template.description}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>

          {creating && (
            <aside
              className="halo w-full max-w-[460px] flex-[1_1_360px] rounded-[22px] p-[1.5px]"
              style={{ animation: "ring 5s linear infinite, slide-in .5s cubic-bezier(.16,1,.3,1) both" }}
              aria-label="New AI Employee"
            >
              <form onSubmit={create} className="flex flex-col gap-4 rounded-[21px] bg-panel p-5">
                <div className="flex items-center gap-2.5">
                  <h2 className="flex-1 font-display text-[19px] font-semibold">New AI Employee</h2>
                  <button type="button" className="icon-btn h-10 w-10" aria-label="Close" onClick={() => setCreating(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <p className="text-[13px] leading-normal text-muted">
                  Three plain questions instead of one blank instructions box. It starts as a draft.
                </p>
                <div ref={firstField} className="grid grid-cols-2 gap-2.5">
                  <Input label="Name" value={name} onChange={setName} required />
                  <Input label="Job title" value={jobTitle} onChange={setJobTitle} />
                </div>
                <TextArea
                  label="What should it do?"
                  badge={<StepNumber n={1} />}
                  rows={2}
                  value={does}
                  onChange={setDoes}
                  placeholder="Read new support emails and draft a reply to each one."
                />
                <TextArea
                  label="What must it never do?"
                  badge={<StepNumber n={2} />}
                  rows={2}
                  value={never}
                  onChange={setNever}
                  placeholder="Never promise a refund. Never email a customer without approval."
                />
                <TextArea
                  label="When should it ask a human first?"
                  badge={<StepNumber n={3} />}
                  rows={2}
                  value={askHuman}
                  onChange={setAskHuman}
                  placeholder="Before anything goes to a customer."
                />
                <div className="flex flex-col gap-2">
                  <span className="label">What can it use?</span>
                  {<ToolPicker value={tools} onChange={setTools} />}
                </div>
                <ErrorNote message={error} />
                <div className="flex gap-2.5">
                  <Button type="submit" className="flex-1" disabled={busy === "create" || !name.trim() || !does.trim()}>
                    {busy === "create" ? "Creating…" : "Create as draft"}
                  </Button>
                  <Button variant="ghost" onClick={() => setCreating(false)}>
                    Cancel
                  </Button>
                </div>
              </form>
            </aside>
          )}

          {editing && (
            <aside
              className="halo w-full max-w-[460px] flex-[1_1_360px] rounded-[22px] p-[1.5px]"
              style={{ animation: "ring 5s linear infinite, slide-in .5s cubic-bezier(.16,1,.3,1) both" }}
              aria-label={`Tools for ${editing.name}`}
              data-coach="tools-panel"
            >
              <div className="flex flex-col gap-4 rounded-[21px] bg-panel p-5">
                <div className="flex items-center gap-2.5">
                  <h2 className="flex-1 font-display text-[19px] font-semibold">Tools and AI for {editing.name}</h2>
                  <button type="button" className="icon-btn h-10 w-10" aria-label="Close" onClick={() => setEditing(null)}>
                    <Icon name="x" />
                  </button>
                </div>
                <p className="text-[13px] leading-normal text-muted">
                  Anything left unticked does not exist as far as it is concerned. Sends and invites still wait for approval.
                </p>
                <div data-coach="model-select">
                <Select
                  label="Which AI does the thinking?"
                  value={editModel}
                  onChange={setEditModel}
                  options={[
                    // Automatic: each task goes to whichever connected AI suits it.
                    ...AUTO_CHOICES.map((c) => ({ value: `auto|${c.routing}`, label: c.label })),
                    ...models.map((m) => ({
                      value: `${m.provider_key}:${m.model}`,
                      label: `${m.display_name} · ${m.model}`,
                    })),
                    // Keep a pinned model visible even if its provider was disconnected.
                    ...(!editModel.startsWith("auto|") && !models.some((m) => `${m.provider_key}:${m.model}` === editModel)
                      ? [{ value: editModel, label: `${modelLabel(editModel)} (not connected)` }]
                      : []),
                  ]}
                />
                </div>
                <div data-coach="tool-picker">
                  {<ToolPicker value={editTools} onChange={setEditTools} />}
                </div>
                <ErrorNote message={error} />
                <div className="flex gap-2.5">
                  <Button className="flex-1" disabled={busy === "tools"} onClick={() => void saveTools()}>
                    {busy === "tools" ? "Saving…" : `Save · ${editTools.length} tools`}
                  </Button>
                  <Button variant="ghost" onClick={() => setEditing(null)}>
                    Cancel
                  </Button>
                </div>
              </div>
            </aside>
          )}
        </div>
      </PageBody>
    </>
  );
}

function StepNumber({ n }: { n: number }) {
  return (
    <span className="flex h-[22px] w-[22px] items-center justify-center rounded-[7px] bg-accent-soft font-mono text-xs font-semibold text-accent-text">
      {n}
    </span>
  );
}

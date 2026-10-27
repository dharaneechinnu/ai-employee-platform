import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../components/icons";
import { ProviderMark } from "../components/ProviderMark";
import {
  Button,
  Chip,
  ErrorNote,
  HoldButton,
  Input,
  PageBody,
  PageHeader,
  Select,
  Spinner,
  relativeTime,
  statusTone,
  useToast,
} from "../components/ui";
import {
  ApiError,
  api,
  type AutoModelResult,
  type ConnectedProvider,
  type GuideStep,
  type ProviderOption,
  type Usage,
} from "../lib/api";
import { fmtCost } from "../lib/agents";
import { formatDateTime } from "../lib/labels";
import { notifySetup, useSetup } from "../lib/setup";

/** What auto-select found, in a sentence a person can act on. */
function autoModelMessage(found: AutoModelResult | null): string {
  if (!found) return "Key saved. Test it to make sure it works.";
  if (found.selected) return `Key saved. Using ${found.selected}, which your key can reach.`;
  const first = found.tried[0]?.reason;
  return first
    ? `Key saved, but no model answered: ${first} Pick one yourself, or check the key.`
    : "Key saved. Test it to make sure it works.";
}

// Any open-source model on the person's own machine or server: Ollama,
// LM Studio, vLLM and LiteLLM all speak the OpenAI format.
const CUSTOM = "custom";

function byRank(a: ProviderOption, b: ProviderOption): number {
  const ra = a.recommended_rank ?? 99;
  const rb = b.recommended_rank ?? 99;
  if (ra !== rb) return ra - rb;
  if (a.free_tier !== b.free_tier) return a.free_tier ? -1 : 1;
  return a.display_name.localeCompare(b.display_name);
}

/**
 * AI keys: every provider as a card, a guide beside it, and a Web search
 * section for the search key. Bring your own key: you pay your own model
 * costs. A saved key is never shown again, so the form only ever writes;
 * the last four characters are all the UI gets back.
 */
export default function Providers() {
  const [ais, setAis] = useState<ProviderOption[] | null>(null);
  const [searches, setSearches] = useState<ProviderOption[]>([]);
  const [connected, setConnected] = useState<ConnectedProvider[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  // What each AI has cost so far, by provider. Left empty if it cannot be read.
  const [spent, setSpent] = useState<Record<string, number>>({});

  const load = useCallback(async () => {
    const [a, s, c, cs] = await Promise.all([
      api.get<ProviderOption[]>(`/me/providers/available`),
      api.get<ProviderOption[]>(`/me/providers/available?kind=search`),
      api.get<ConnectedProvider[]>(`/me/providers`),
      api.get<ConnectedProvider[]>(`/me/providers?kind=search`),
    ]);
    setAis(a.sort(byRank));
    setSearches(s.sort(byRank));
    setConnected([...c, ...cs]);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .get<Usage>("/me/usage?range=all")
      .then((u) => {
        const byProvider: Record<string, number> = {};
        for (const m of u.models) byProvider[m.provider_key] = (byProvider[m.provider_key] ?? 0) + Number(m.cost_usd);
        setSpent(byProvider);
      })
      .catch(() => undefined);
  }, []);

  const find = useMemo(() => new Map(connected.map((c) => [c.provider_key, c])), [connected]);
  const all = useMemo(() => [...(ais ?? []), ...searches], [ais, searches]);
  const panel = open ? all.find((p) => p.key === open) : undefined;
  const aiConnected = (ais ?? []).filter((p) => find.has(p.key)).length;

  if (!ais) {
    return (
      <>
        <PageHeader title="AI keys" />
        <Spinner />
      </>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="min-w-0 flex-1">
        <PageHeader title="AI keys">
          <span className="max-w-[380px] text-[13px] leading-snug text-muted">
            Your key, your bill. Run costs here are estimates; your provider's invoice is the real number.
          </span>
        </PageHeader>

        <PageBody>
          <div className="flex flex-wrap items-start gap-3 rounded-xl border border-line bg-panel px-4 py-3.5" data-coach="routing-note">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-text">
              <Icon name="sparkle" size={17} />
            </span>
            <div className="min-w-0 flex-1 text-[13.5px] leading-normal">
              <div className="font-medium">
                {aiConnected > 1
                  ? `Automatic picks from your ${aiConnected} AIs for every task`
                  : "Connect more than one AI and Automatic picks the right one for each task"}
              </div>
              <div className="text-muted">
                Hard work goes to your strongest AI, quick questions to the fastest and cheapest, and if one is busy the next
                takes over.
              </div>
            </div>
          </div>

          <Section title="AI models" hint="Start with a free one. You can add more later.">
            {ais.map((p) => (
              <ProviderCard
                key={p.key}
                option={p}
                conn={find.get(p.key)}
                spent={spent[p.key]}
                suggest={aiConnected === 0 && p.recommended_rank === 1}
                active={open === p.key}
                onOpen={() => setOpen(p.key)}
              />
            ))}
          </Section>

          <Section title="Web search" hint="Lets agents look things up on the web. Optional, but the Researcher needs it.">
            {searches.map((p) => (
              <ProviderCard
                key={p.key}
                option={p}
                conn={find.get(p.key)}
                suggest={false}
                active={open === p.key}
                onOpen={() => setOpen(p.key)}
              />
            ))}
          </Section>

          <p className="text-[13px] text-dim">Keys are encrypted and cannot be read back, by you or by us.</p>
        </PageBody>
      </div>

      {panel && (
        <ProviderPanel
          key={panel.key}
          option={panel}
          conn={find.get(panel.key)}
          onClose={() => setOpen(null)}
          onChanged={() => void load()}
        />
      )}
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-display text-[17px] font-semibold">{title}</h2>
        <p className="text-[13px] text-muted">{hint}</p>
      </div>
      <div className="stagger grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr))]">{children}</div>
    </section>
  );
}

function ProviderCard({
  option,
  conn,
  spent,
  suggest,
  active,
  onOpen,
}: {
  option: ProviderOption;
  conn: ConnectedProvider | undefined;
  /** Estimated cost to date, when this AI has been used. */
  spent?: number;
  suggest: boolean;
  active: boolean;
  onOpen: () => void;
}) {
  const failed = conn?.status === "failed";
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={active}
      className={`card lift flex flex-col gap-3 p-4 text-left ${active ? "card-on" : ""}`}
      style={failed ? { borderColor: "var(--bad)" } : undefined}
    >
      <div className="flex items-center gap-3">
        <ProviderMark provider={option.key} size={36} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-display text-[16px] font-semibold">{conn?.display_name ?? option.display_name}</div>
          <div className="truncate text-[12px] text-dim">
            {conn ? (conn.key_last4 === "none" ? "no key" : `key ••••${conn.key_last4}`) : "Not connected"}
          </div>
        </div>
        {conn && <Chip tone={statusTone(conn.status)}>{conn.status}</Chip>}
      </div>
      <div className="flex flex-wrap gap-1.5 text-[11.5px]">
        {suggest && <Pill tone="accent">Recommended first</Pill>}
        {option.is_local ? <Pill>Local</Pill> : option.free_tier ? <Pill tone="ok">Free tier</Pill> : <Pill>Paid</Pill>}
        {conn?.default_model && <Pill mono>{conn.default_model}</Pill>}
      </div>
      {conn && spent !== undefined && (
        <div className="text-[12.5px] text-muted">
          Cost to date <b className="font-mono font-medium text-ink">{spent > 0 ? fmtCost(spent) : "$0"}</b>
          <span className="text-dim"> (estimate)</span>
        </div>
      )}
      <span className="mt-auto flex items-center gap-1 text-[13px] font-medium text-accent-text">
        {conn ? "Manage" : "Connect"}
        <Icon name="chevron" size={14} />
      </span>
    </button>
  );
}

function Pill({ children, tone, mono }: { children: React.ReactNode; tone?: "ok" | "accent"; mono?: boolean }) {
  const look =
    tone === "ok" ? "bg-ok-soft text-ok-text" : tone === "accent" ? "bg-accent-soft text-accent-text" : "bg-raised text-muted";
  return <span className={`max-w-full truncate rounded-full px-2 py-0.5 font-medium ${look} ${mono ? "font-mono" : ""}`}>{children}</span>;
}

function ProviderPanel({
  option,
  conn,
  onClose,
  onChanged,
}: {
  option: ProviderOption;
  conn: ConnectedProvider | undefined;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const { state, markGuideStep } = useSetup();
  const search = option.kind === "search";
  const custom = option.key === CUSTOM;

  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState(custom ? "http://localhost:11434/v1" : "");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [showGuide, setShowGuide] = useState(true);
  const [skipped, setSkipped] = useState(false);
  const [justWorked, setJustWorked] = useState(false);

  const doneSteps = state?.guide[option.key] ?? [];
  const working = conn?.status === "working";
  const showForm = !conn || replacing;
  const firstUndone = option.guide.find((s) => !doneSteps.includes(s.id))?.id;
  const guideVisible = option.guide.length > 0 && (!working || showGuide) && !skipped;

  async function tick(step: string) {
    if (!doneSteps.includes(step)) {
      await markGuideStep(option.key, step);
      notifySetup();
    }
  }

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("save");
    try {
      const typedModel = model.trim();
      await api.post(`/me/providers`, {
        provider_key: option.key,
        api_key: apiKey,
        model: typedModel || null,
        ...(custom ? { base_url: baseUrl, label: label || null } : {}),
      });
      setApiKey("");
      await tick("create");
      await tick("paste");
      setBusy("test");
      let ok = false;
      if (search || typedModel) {
        const res = await api.post<ConnectedProvider>(`/me/providers/${option.key}/test`);
        ok = res.status === "working";
        if (!ok) setError(res.last_error ?? "The key did not work.");
      } else {
        // No model named: ask the provider what this key can use and
        // switch to one that really answers.
        const found = await api.post<AutoModelResult>(`/me/providers/${option.key}/auto-model`).catch(() => null);
        ok = found?.provider.status === "working";
        if (!ok) setError(found?.provider.last_error ?? autoModelMessage(found));
      }
      if (ok) {
        await tick("test");
        setJustWorked(true);
        setReplacing(false);
      }
      notifySetup();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect that.");
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    try {
      const res = await api.post<ConnectedProvider>(`/me/providers/${option.key}/test`);
      if (res.status === "working") {
        await tick("test");
        setJustWorked(true);
      }
      notifySetup();
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The test could not run.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    try {
      await api.del(`/me/providers/${option.key}`);
      toast(`${option.display_name} key removed. Paste it again to reconnect.`, "info");
      setJustWorked(false);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not remove that key.", "bad");
    }
    notifySetup();
    onChanged();
  }

  const ready = custom ? Boolean(baseUrl) : Boolean(apiKey);

  return (
    <aside className="side-panel w-full shrink-0 overflow-y-auto p-5 lg:sticky lg:top-0 lg:h-screen lg:w-[400px]" aria-label={`${option.display_name} setup`}>
      <div className="flex items-start gap-3">
        <ProviderMark provider={option.key} size={40} />
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-xl font-semibold">{option.display_name}</h2>
          <div className="text-[12.5px] text-dim">
            {search ? "Web search" : option.is_local ? "Runs on your machine" : option.free_tier ? "Has a free tier" : "Paid"}
          </div>
        </div>
        <button type="button" onClick={onClose} className="icon-btn" aria-label="Close panel">
          <Icon name="x" size={18} />
        </button>
      </div>

      {justWorked && working && (
        <div className="mt-4 flex flex-col gap-3 rounded-xl bg-ok-soft p-4 text-ok-text">
          <div className="flex items-center gap-3 font-medium">
            <svg className="check-draw" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12l4 4 10-10" />
            </svg>
            {search ? "Search is connected" : "Connected and working"}
          </div>
          {!search && (
            <Button size="sm" icon="chat" onClick={() => navigate("/chat")}>
              Next: say hello in chat
            </Button>
          )}
        </div>
      )}

      {conn && (
        <dl className="mt-4 grid grid-cols-2 gap-3 text-[13px]">
          <div>
            <dt className="text-dim">Status</dt>
            <dd>
              <Chip tone={statusTone(conn.status)}>{conn.status}</Chip>
            </dd>
          </div>
          <div>
            <dt className="text-dim">Last tested</dt>
            <dd className="font-mono" title={conn.last_tested_at ? formatDateTime(conn.last_tested_at) : undefined}>
              {conn.last_tested_at ? relativeTime(conn.last_tested_at) : "never"}
            </dd>
          </div>
          <div>
            <dt className="text-dim">Key</dt>
            <dd className="font-mono">{conn.key_last4 === "none" ? "none" : `••••${conn.key_last4}`}</dd>
          </div>
          {!search && <ModelChoice provider={conn} onSaved={onChanged} />}
          {conn.base_url && (
            <div className="col-span-2">
              <dt className="text-dim">Server</dt>
              <dd className="truncate font-mono" title={conn.base_url}>{conn.base_url}</dd>
            </div>
          )}
        </dl>
      )}

      {conn?.last_error && (
        <div className="mt-3">
          <ErrorNote message={conn.last_error} />
        </div>
      )}

      {conn && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant={conn.status === "working" ? "ghost" : "brand"} disabled={busy !== null} onClick={() => void test()}>
            {busy === "test" ? "Testing…" : conn.status === "working" ? "Test again" : "Test connection"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setReplacing((v) => !v)}>
            {replacing ? "Keep current key" : "Change key"}
          </Button>
          {/* Removing deletes the stored key for good, so it takes a hold. */}
          <HoldButton variant="danger-ghost" className="btn-sm" onConfirm={() => void remove()}>
            Hold to remove
          </HoldButton>
        </div>
      )}

      {guideVisible && (
        <Guide
          steps={option.guide}
          done={doneSteps}
          current={firstUndone}
          onOpenLink={() => void tick("signup")}
          onSkip={() => setSkipped(true)}
        />
      )}
      {working && guideVisible && showGuide && (
        <button type="button" className="mt-2 text-[13px] text-dim hover:underline" onClick={() => setShowGuide(false)}>
          Hide the guide
        </button>
      )}
      {!guideVisible && option.guide.length > 0 && (
        <button
          type="button"
          className="mt-4 text-[13px] text-accent-text hover:underline"
          onClick={() => {
            setShowGuide(true);
            setSkipped(false);
          }}
        >
          <Icon name="book" size={14} className="mr-1 inline" /> Show the setup guide again
        </button>
      )}

      {showForm && (
        <form onSubmit={connect} className="mt-5 flex flex-col gap-3">
          {custom && (
            <>
              <Input label="Name" value={label} onChange={setLabel} placeholder="My local model" />
              <Input label="Server address" value={baseUrl} onChange={setBaseUrl} required mono placeholder="http://localhost:11434/v1" />
              <Input label="Model (leave empty to find one)" value={model} onChange={setModel} mono placeholder="llama3.2" />
            </>
          )}
          <Input
            label={custom ? "API key (only if it needs one)" : "API key"}
            type="password"
            value={apiKey}
            onChange={setApiKey}
            required={!custom}
            mono
            autoComplete="off"
            placeholder="Paste key"
          />
          {option.trains_on_data && (
            <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px] leading-normal">
              <Icon name="warn" className="text-ask-text" />
              <span>This provider may train on what you send it. Check their terms before using it with private data.</span>
            </div>
          )}
          <ErrorNote message={error} />
          <Button type="submit" disabled={!ready || busy !== null}>
            {busy === "save" ? "Saving…" : busy === "test" ? "Testing…" : conn ? "Replace key" : "Connect and test"}
          </Button>
        </form>
      )}
    </aside>
  );
}

/**
 * The steps, one action each. Steps already done collapse to a single
 * line and the first undone one is open, so reopening the guide never
 * walks someone through something they have finished.
 */
function Guide({
  steps,
  done,
  current,
  onOpenLink,
  onSkip,
}: {
  steps: GuideStep[];
  done: string[];
  current: string | undefined;
  onOpenLink: () => void;
  onSkip: () => void;
}) {
  const finished = steps.filter((s) => done.includes(s.id)).length;
  return (
    <div className="mt-5 rounded-xl border border-line bg-panel p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-display text-[15px] font-semibold">Setup guide</h3>
        <button type="button" onClick={onSkip} className="text-[12.5px] text-dim hover:underline">
          I already have a key
        </button>
      </div>
      <div className="meter mb-3" aria-hidden="true">
        <i style={{ ["--fill" as string]: steps.length ? finished / steps.length : 0, background: "var(--accent)" }} />
      </div>
      <ol className="flex flex-col gap-2">
        {steps.map((s, i) => {
          const isDone = done.includes(s.id);
          const isCurrent = s.id === current;
          return (
            <li key={s.id} className={`rounded-lg px-3 py-2 ${isCurrent ? "card-on" : ""}`}>
              <div className={`flex items-center gap-2 text-[13.5px] ${isDone ? "text-ok-text" : "font-medium"}`}>
                <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] ${isDone ? "bg-ok-soft" : "bg-raised"}`}>
                  {isDone ? <Icon name="check" size={12} strokeWidth={3} /> : i + 1}
                </span>
                {s.title}
              </div>
              {isCurrent && (
                <div className="mt-1.5 pl-7 text-[13px] leading-normal text-muted">
                  <p>{s.detail}</p>
                  <p className="mt-1 text-dim">You should see: {s.expect}</p>
                  {s.url && (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={onOpenLink}
                      className="mt-2 inline-flex items-center gap-1 font-medium text-accent-text hover:underline"
                    >
                      Open the page <Icon name="external" size={13} />
                    </a>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * Which model this provider runs. "Load models" asks the provider what
 * the key can use, so nobody has to know model ids by heart; typing a
 * name still works for a provider that cannot list.
 */
function ModelChoice({
  provider,
  onSaved,
}: {
  provider: ConnectedProvider;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(provider.default_model ?? "");
  const [options, setOptions] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  async function loadOptions() {
    setLoading(true);
    try {
      setOptions(await api.get<string[]>(`/me/providers/${provider.provider_key}/models`));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not load the model list.", "bad");
    } finally {
      setLoading(false);
    }
  }

  async function pickBest() {
    setSaving(true);
    try {
      const found = await api.post<AutoModelResult>(`/me/providers/${provider.provider_key}/auto-model`);
      toast(autoModelMessage(found), found.selected ? "ok" : "bad");
      if (found.selected) setValue(found.selected);
      setEditing(false);
      onSaved();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not check the models.", "bad");
    } finally {
      setSaving(false);
    }
  }

  async function save(model: string | null) {
    setSaving(true);
    try {
      await api.put(`/me/providers/${provider.provider_key}/model`, { model });
      toast("Model saved. Test the connection to check it works.");
      setEditing(false);
      onSaved();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not save that model.", "bad");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="min-w-0">
        <div className="text-dim">Model{provider.model_chosen ? "" : " (default)"}</div>
        <button
          type="button"
          className="flex max-w-full items-center gap-1 truncate font-mono text-accent-text hover:underline"
          onClick={() => setEditing(true)}
          title="Change model"
        >
          <span className="truncate">{provider.default_model ?? "—"}</span>
        </button>
      </div>
    );
  }

  return (
    <div className="col-span-2 flex flex-col gap-2 rounded-xl border border-line bg-raised p-3">
      {options && options.length > 0 ? (
        <Select
          label="Model"
          value={value}
          onChange={setValue}
          options={[...new Set([value, ...options])].filter(Boolean).map((m) => ({ value: m, label: m }))}
        />
      ) : (
        <Input label="Model" value={value} onChange={setValue} mono placeholder="model name" />
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!value || saving} onClick={() => void save(value)}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" icon="sparkle" disabled={saving} onClick={() => void pickBest()}>
          Pick the best for my key
        </Button>
        {!options && (
          <Button size="sm" variant="ghost" disabled={loading} onClick={() => void loadOptions()}>
            {loading ? "Loading…" : "Load models"}
          </Button>
        )}
        {provider.model_chosen && provider.provider_key !== CUSTOM && (
          <Button size="sm" variant="ghost" disabled={saving} onClick={() => void save(null)}>
            Use default
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

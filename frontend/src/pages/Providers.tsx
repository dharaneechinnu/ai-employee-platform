import { useEffect, useState } from "react";
import { Icon } from "../components/icons";
import {
  Button,
  Chip,
  Empty,
  ErrorNote,
  Input,
  PageBody,
  PageHeader,
  Select,
  Spinner,
  relativeTime,
  statusTone,
  useToast,
} from "../components/ui";
import { ApiError, api, type AutoModelResult, type ConnectedProvider, type ProviderOption } from "../lib/api";
import { formatDateTime } from "../lib/labels";

/** What auto-select found, in a sentence a person can act on. */
function autoModelMessage(found: AutoModelResult | null): string {
  if (!found) return "Key saved. Test it to make sure it works.";
  if (found.selected) return `Key saved. Using ${found.selected}, which your key can reach.`;
  const first = found.tried[0]?.reason;
  return first
    ? `Key saved, but no model answered: ${first} Pick one yourself, or check the key.`
    : "Key saved. Test it to make sure it works.";
}

/**
 * Phase 3. Bring your own key: each company pays its own model costs.
 *
 * A saved key is never shown again, to anyone, so this form only ever
 * writes. The last four characters are all the UI gets back.
 */
const FREE_TIER = ["gemini", "groq"];
const ORDER = ["gemini", "groq", "openai", "anthropic", "deepseek", "mistral", "sarvam", "openrouter", "custom"];
// Any open-source model, on the company's own server: vLLM, Ollama,
// LM Studio and LiteLLM all speak the OpenAI format.
const CUSTOM = "custom";
const rank = (key: string) => (ORDER.includes(key) ? ORDER.indexOf(key) : ORDER.length);

export default function Providers() {
  const toast = useToast();
  const [available, setAvailable] = useState<ProviderOption[] | null>(null);
  const [connected, setConnected] = useState<ConnectedProvider[]>([]);
  const [selected, setSelected] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    // Free tiers first, so a new company's first choice costs nothing.
    const options = (await api.get<ProviderOption[]>(`/me/providers/available`)).sort(
      (a, b) => rank(a.key) - rank(b.key),
    );
    setAvailable(options);
    setConnected(await api.get<ConnectedProvider[]>(`/me/providers`));
    setSelected((current) => current || options[0]?.key || "");
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, ["me"]);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const typedModel = model.trim();
      await api.post(`/me/providers`, {
        provider_key: selected,
        api_key: apiKey,
        model: typedModel || null,
        ...(selected === CUSTOM ? { base_url: baseUrl, label: label || null } : {}),
      });
      setApiKey("");
      setModel("");
      setBaseUrl("");
      setLabel("");
      if (typedModel) {
        toast("Key saved. Test it to make sure it works.");
      } else {
        // No model named: ask the provider what this key can use and
        // switch to one that really answers, so a free key does not
        // start on a model it cannot reach.
        const found = await api
          .post<AutoModelResult>(`/me/providers/${selected}/auto-model`)
          .catch(() => null);
        toast(autoModelMessage(found));
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect that.");
    } finally {
      setSaving(false);
    }
  }

  async function test(provider: ConnectedProvider) {
    setTesting(provider.provider_key);
    try {
      await api.post(`/me/providers/${provider.provider_key}/test`);
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The test could not run.", "bad");
    } finally {
      setTesting(null);
    }
  }

  async function disconnect(provider: ConnectedProvider) {
    await api.del(`/me/providers/${provider.provider_key}`);
    toast(`${provider.display_name} removed.`, "info");
    await load();
  }

  if (!available) {
    return (
      <>
        <PageHeader crumb="Settings" title="AI Providers" />
        <Spinner />
      </>
    );
  }

  const chosen = available.find((p) => p.key === selected);
  const custom = selected === CUSTOM;
  const ready = custom ? Boolean(baseUrl) : Boolean(apiKey);

  return (
    <>
      <PageHeader crumb="Settings" title="AI Providers">
        <span className="max-w-[380px] text-[13px] leading-snug text-muted">
          Your key, your bill. Run costs here are estimates; your provider's invoice is the real number.
        </span>
      </PageHeader>

      <PageBody>
        {/* Several AIs are better than one: Automatic gives each task to
            the one that suits it, and falls back if one is busy. */}
        <div className="flex flex-wrap items-start gap-3 rounded-xl border border-line bg-panel px-4 py-3.5" data-coach="routing-note">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-text">
            <Icon name="sparkle" size={17} />
          </span>
          <div className="min-w-0 flex-1 text-[13.5px] leading-normal">
            <div className="font-medium">
              {connected.length > 1
                ? `Automatic picks from your ${connected.length} AIs for every task`
                : "Connect more than one AI and Automatic picks the right one for each task"}
            </div>
            <div className="text-muted">
              Hard work like coding and analysis goes to your strongest AI, quick questions to the fastest and cheapest, and if
              one is busy the next takes over. Choose Automatic, or pin one AI, in a chat.
            </div>
          </div>
        </div>

        {connected.length === 0 ? (
          <Empty message="No provider connected" hint="Your assistant cannot answer until you connect at least one key below." />
        ) : (
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(360px,100%),1fr))]">
            {connected.map((provider, i) => {
              const isTesting = testing === provider.provider_key;
              const working = provider.status === "working";
              return (
                <article
                  key={provider.provider_key}
                  className="card lift rise flex flex-col gap-4 p-5"
                  style={{
                    animationDelay: `${i * 0.08}s`,
                    ...(provider.status === "failed" ? { borderColor: "var(--bad)" } : {}),
                  }}
                >
                  <div className="flex items-center gap-3.5">
                    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] border border-line2 bg-raised font-display text-lg font-bold text-accent-text">
                      {provider.display_name.charAt(0)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-display text-lg font-semibold">{provider.display_name}</div>
                      <div className="font-mono text-[13px] text-muted">
                        {provider.key_last4 === "none" ? "no key" : `key ••••••••${provider.key_last4}`}
                      </div>
                    </div>
                    {isTesting ? (
                      <Chip tone="run" dot={false}>
                        <Icon name="spinner" size={12} strokeWidth={3} className="spin" />
                        testing
                      </Chip>
                    ) : (
                      <Chip tone={statusTone(provider.status)}>{provider.status}</Chip>
                    )}
                  </div>

                  {working && (
                    <div className="flex items-center gap-3" aria-hidden="true">
                      <span className="text-xs text-dim">You</span>
                      <span className="relative h-0.5 flex-1 rounded" style={{ background: "linear-gradient(90deg,var(--line2),var(--ok),var(--line2))" }}>
                        {[0, 0.8].map((delay) => (
                          <span
                            key={delay}
                            className="absolute -top-[3px] h-2 w-2 rounded-full bg-ok"
                            style={{ boxShadow: "0 0 10px var(--ok)", animation: `beam 1.6s ease-in-out ${delay}s infinite` }}
                          />
                        ))}
                      </span>
                      <span className="text-xs text-dim">{provider.display_name}</span>
                    </div>
                  )}

                  {provider.strengths && provider.strengths.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                      <span className="text-dim">Automatic sends it</span>
                      {provider.strengths.map((s) => (
                        <span key={s} className="rounded-full bg-raised px-2 py-0.5 text-muted">
                          {s}
                        </span>
                      ))}
                    </div>
                  )}

                  {provider.trains_on_data && (
                    <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px] leading-normal">
                      <Icon name="warn" className="text-ask-text" />
                      <span>This provider may train on what you send it. Check their terms before using it with customer data.</span>
                    </div>
                  )}

                  {provider.last_error && <ErrorNote message={provider.last_error} />}

                  {provider.base_url && (
                    <div className="text-[13px]">
                      <div className="text-dim">Server</div>
                      <div className="truncate font-mono" title={provider.base_url}>{provider.base_url}</div>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-2.5 text-[13px]">
                    <ModelChoice provider={provider} onSaved={() => void load()} />
                    <div>
                      <div className="text-dim">Last tested</div>
                      <div className="font-mono" title={provider.last_tested_at ? formatDateTime(provider.last_tested_at) : undefined}>
                        {provider.last_tested_at ? relativeTime(provider.last_tested_at) : "never"}
                      </div>
                    </div>
                  </div>

                  <div className="mt-auto flex gap-2">
                    <Button size="sm" variant={provider.status === "untested" ? "brand" : "ghost"} disabled={isTesting} onClick={() => void test(provider)}>
                      {provider.status === "untested" ? "Test connection" : "Test again"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void disconnect(provider)}>
                      Remove
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <form onSubmit={connect} className="card rise flex flex-col gap-4 border-dashed border-line2 p-5" data-coach="provider-form">
          <h2 className="font-display text-[17px] font-semibold">Connect a provider</h2>
          <div className="grid items-end gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))]">
            <Select
              label="Provider"
              value={selected}
              onChange={setSelected}
              options={available.map((option) => ({
                value: option.key,
                label: FREE_TIER.includes(option.key) ? `${option.display_name} (free tier)` : option.display_name,
              }))}
            />
            {custom && (
              <>
                <Input label="Name" value={label} onChange={setLabel} placeholder="Our Llama server" />
                <Input label="Server address" value={baseUrl} onChange={setBaseUrl} required mono placeholder="https://llm.example.com/v1" />
              </>
            )}
            <Input
              label={custom ? "Model" : "Model (optional)"}
              value={model}
              onChange={setModel}
              required={custom}
              mono
              placeholder={custom ? "llama-3.3-70b" : chosen?.default_model ?? ""}
            />
            <Input
              label={custom ? "API key (if it needs one)" : "API key"}
              type="password"
              value={apiKey}
              onChange={setApiKey}
              required={!custom}
              mono
              autoComplete="off"
              placeholder="Paste key"
            />
            <Button type="submit" variant={connected.length ? "ghost" : "brand"} disabled={!ready || saving}>
              {saving ? "Saving…" : "Connect"}
            </Button>
          </div>
          {custom && (
            <p className="text-[13px] leading-snug text-muted">
              Run any open-source model (Llama, Qwen, DeepSeek, Mistral, Gemma) on your own server with vLLM, Ollama, LM Studio
              or LiteLLM, and paste the address of its OpenAI-compatible API, usually ending in <span className="font-mono">/v1</span>.
              It must be reachable over https.
            </p>
          )}
          {chosen?.trains_on_data && (
            <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px]">
              <Icon name="warn" className="text-ask-text" />
              This provider may use what you send to train its models. Fine for testing; think carefully before real customer data.
            </div>
          )}
          <ErrorNote message={error} />
          <p className="flex flex-wrap gap-x-3 text-[13px] text-dim">
            Keys are encrypted and cannot be read back, by you or by us. Only the last four characters are shown.
            {chosen?.docs_url && (
              <a href={chosen.docs_url} target="_blank" rel="noreferrer" className="hover:underline">
                Where do I find this key?
              </a>
            )}
          </p>
        </form>
      </PageBody>
    </>
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

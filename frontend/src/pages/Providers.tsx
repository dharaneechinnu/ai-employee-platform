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
import { ApiError, api, type ConnectedProvider, type ProviderOption } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Phase 3. Bring your own key: each company pays its own model costs.
 *
 * A saved key is never shown again, to anyone, so this form only ever
 * writes. The last four characters are all the UI gets back.
 */
export default function Providers() {
  const { org } = useAuth();
  const toast = useToast();
  const [available, setAvailable] = useState<ProviderOption[] | null>(null);
  const [connected, setConnected] = useState<ConnectedProvider[]>([]);
  const [selected, setSelected] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    if (!org) return;
    const options = await api.get<ProviderOption[]>(`/orgs/${org.id}/providers/available`);
    setAvailable(options);
    setConnected(await api.get<ConnectedProvider[]>(`/orgs/${org.id}/providers`));
    setSelected((current) => current || options[0]?.key || "");
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setError(null);
    setSaving(true);
    try {
      await api.post(`/orgs/${org.id}/providers`, { provider_key: selected, api_key: apiKey });
      setApiKey("");
      toast("Key saved. Test it to make sure it works.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect that.");
    } finally {
      setSaving(false);
    }
  }

  async function test(provider: ConnectedProvider) {
    if (!org) return;
    setTesting(provider.provider_key);
    try {
      await api.post(`/orgs/${org.id}/providers/${provider.provider_key}/test`);
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The test could not run.", "bad");
    } finally {
      setTesting(null);
    }
  }

  async function disconnect(provider: ConnectedProvider) {
    if (!org) return;
    await api.del(`/orgs/${org.id}/providers/${provider.provider_key}`);
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

  return (
    <>
      <PageHeader crumb="Settings" title="AI Providers">
        <span className="max-w-[380px] text-[13px] leading-snug text-muted">
          Your key, your bill. Run costs here are estimates; your provider's invoice is the real number.
        </span>
      </PageHeader>

      <PageBody>
        {connected.length === 0 ? (
          <Empty message="No provider connected" hint="AI Employees cannot run until you connect at least one key below." />
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
                      <div className="font-mono text-[13px] text-muted">key ••••••••{provider.key_last4}</div>
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

                  {provider.trains_on_data && (
                    <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px] leading-normal">
                      <Icon name="warn" className="text-ask-text" />
                      <span>This provider may train on what you send it. Check their terms before using it with customer data.</span>
                    </div>
                  )}

                  {provider.last_error && <ErrorNote message={provider.last_error} />}

                  <div className="grid grid-cols-2 gap-2.5 text-[13px]">
                    <div>
                      <div className="text-dim">Default model</div>
                      <div className="truncate font-mono">{provider.default_model ?? "—"}</div>
                    </div>
                    <div>
                      <div className="text-dim">Last tested</div>
                      <div className="font-mono" title={provider.last_tested_at ? new Date(provider.last_tested_at).toLocaleString() : undefined}>
                        {provider.last_tested_at ? relativeTime(provider.last_tested_at) : "never"}
                      </div>
                    </div>
                  </div>

                  <div className="mt-auto flex gap-2">
                    <Button size="sm" variant={provider.status === "untested" ? "gold" : "ghost"} disabled={isTesting} onClick={() => void test(provider)}>
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

        <form onSubmit={connect} className="card rise flex flex-col gap-4 border-dashed border-line2 p-5">
          <h2 className="font-display text-[17px] font-semibold">Connect a provider</h2>
          <div className="grid items-end gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))]">
            <Select
              label="Provider"
              value={selected}
              onChange={setSelected}
              options={available.map((option) => ({ value: option.key, label: option.display_name }))}
            />
            <Input label="API key" type="password" value={apiKey} onChange={setApiKey} required mono autoComplete="off" placeholder="Paste key" />
            <Button type="submit" variant={connected.length ? "ghost" : "gold"} disabled={!apiKey || saving}>
              {saving ? "Saving…" : "Connect"}
            </Button>
          </div>
          {chosen?.trains_on_data && (
            <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px]">
              <Icon name="warn" className="text-ask-text" />
              This provider may use what you send to train its models. Fine for testing; think carefully before real customer data.
            </div>
          )}
          <ErrorNote message={error} />
          <p className="flex flex-wrap gap-x-3 text-[13px] text-dim">
            The key is encrypted and cannot be read back, by you or by us. Only its last four characters are shown.
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

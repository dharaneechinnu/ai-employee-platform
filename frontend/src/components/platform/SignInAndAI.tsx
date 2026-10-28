import { useState } from "react";
import { ApiError } from "../../lib/api";
import Modal from "../Modal";
import { Icon } from "../icons";
import { Switch, useToast } from "../ui";
import { Pill, ScreenTitle, useCopy } from "./bits";
import { call, type OAuthApp, type Provider } from "./api";
import { shortDate, staffName } from "./format";

/**
 * Settings: the Google and Microsoft apps behind one-click sign-in, and
 * the AI provider catalog.
 *
 * Both sign-in apps are one per *application*, not per customer: every
 * person signs in through the same app and grants it access to their own
 * mailbox. The secret is write-only; staff only ever see its last four
 * characters.
 */

const SUBTITLE: Record<string, string> = {
  google: "Sign-in, Gmail, Calendar, Drive, Sheets",
  microsoft: "Sign-in, Outlook mail and calendar, OneDrive",
};

const CONSOLE: Record<string, string> = {
  google: "How to create the app in Google Cloud",
  microsoft: "How to create the app in Azure",
};

const ghost = "h-[38px] rounded-[10px] border border-line bg-panel px-3.5 font-medium text-ink transition-colors hover:bg-raised disabled:opacity-60";

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a1 1 0 0 1 1-1h10" />
    </svg>
  );
}

function AppCard({ app, onChanged }: { app: OAuthApp; onChanged: (apps: OAuthApp[]) => void }) {
  const toast = useToast();
  const copy = useCopy();
  const [editing, setEditing] = useState(!app.client_id);
  const [clientId, setClientId] = useState(app.client_id ?? "");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = !!app.client_id;

  async function reload() {
    onChanged(await call<OAuthApp[]>("/oauth-apps"));
  }

  async function act(run: () => Promise<unknown>, done: string, tone: "ok" | "info" = "ok") {
    setBusy(true);
    setError(null);
    try {
      await run();
      toast(done, tone);
      await reload();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const ok = await act(() => call(`/oauth-apps/${app.provider}`, { client_id: clientId.trim(), client_secret: secret }, "PUT"), `${app.display_name} sign-in is on.`);
    if (ok) {
      setSecret("");
      setEditing(false);
    }
  }

  const statusPill = app.configured ? (
    <Pill tone="ok" strong>
      <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-ok" />
      On
    </Pill>
  ) : set ? (
    <Pill tone="ask" strong>
      Paused
    </Pill>
  ) : (
    <Pill tone="ask" strong>
      Not set up
    </Pill>
  );

  return (
    <article className="flex flex-col gap-4 rounded-2xl border border-line bg-panel p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span aria-hidden="true" className="inline-flex h-10 w-10 items-center justify-center rounded-[10px] border border-line bg-bg text-[17px] font-bold">
            {app.display_name.charAt(0)}
          </span>
          <div>
            <h3 className="text-base font-semibold">{app.display_name}</h3>
            <div className="text-[12.5px] text-muted">{SUBTITLE[app.provider] ?? "Sign-in"}</div>
          </div>
        </div>
        {statusPill}
      </div>

      {set && !editing ? (
        <>
          <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-[13px] sm:grid-cols-[120px_minmax(0,1fr)]">
            <dt className="text-muted">Client ID</dt>
            <dd className="truncate font-mono text-[12.5px]" title={app.client_id ?? ""}>
              {app.client_id}
            </dd>
            <dt className="text-muted">Client secret</dt>
            <dd>{app.secret_last4 ? <>Ends in <span className="font-mono">{app.secret_last4}</span></> : "From the server's settings"}</dd>
            <dt className="text-muted">Redirect URL</dt>
            <dd className="flex min-w-0 items-center gap-2">
              <span className="truncate font-mono text-[12.5px]">{app.redirect_uri}</span>
              <button type="button" aria-label="Copy redirect URL" onClick={() => void copy(app.redirect_uri, "Redirect URL copied.")} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-muted hover:bg-raised">
                <CopyIcon />
              </button>
            </dd>
            {app.updated_at && (
              <>
                <dt className="text-muted">Set up</dt>
                <dd>
                  {shortDate(app.updated_at)}
                  {app.updated_by_email ? ` by ${staffName(app.updated_by_email)}` : ""}
                </dd>
              </>
            )}
          </dl>
          {app.from_environment && (
            <p className="rounded-[10px] bg-bg px-3 py-2.5 text-[12.5px] text-muted">
              This comes from the server's settings. Saving it here takes over, and you can change it again without a redeploy.
            </p>
          )}
          {error && <p className="text-[13px] text-bad-text">{error}</p>}
          <div className="flex flex-wrap gap-2 border-t border-raised pt-3.5">
            <button type="button" className={ghost} onClick={() => setEditing(true)}>
              {app.from_environment ? "Set up here" : "Replace secret"}
            </button>
            {!app.from_environment && (
              <>
                <button
                  type="button"
                  className={ghost}
                  disabled={busy}
                  onClick={() =>
                    void act(
                      () => call(`/oauth-apps/${app.provider}`, { enabled: !app.enabled }, "PATCH"),
                      app.enabled ? `${app.display_name} sign-in turned off. People already connected keep working.` : `${app.display_name} sign-in is on again.`,
                      app.enabled ? "info" : "ok",
                    )
                  }
                >
                  {app.enabled ? "Turn off" : "Turn on"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  className="ml-auto h-[38px] rounded-[10px] px-3.5 font-medium text-bad-text hover:bg-bad-soft"
                  onClick={() => {
                    if (window.confirm(`Remove the ${app.display_name} sign-in app? The one-click button goes away for everyone until it is set up again.`)) {
                      void act(() => call(`/oauth-apps/${app.provider}`, undefined, "DELETE"), `${app.display_name} sign-in removed.`, "info");
                    }
                  }}
                >
                  Remove
                </button>
              </>
            )}
          </div>
        </>
      ) : (
        <form onSubmit={(e) => void save(e)} className="flex flex-col gap-3.5">
          {!set && (
            <p className="text-[13px] text-muted">
              Until this is set up, the {app.display_name.split(" ")[0]} button is hidden and nobody can connect it.{" "}
              <a href={app.docs_url} target="_blank" rel="noreferrer">
                {CONSOLE[app.provider] ?? "Where to get these"}
              </a>
            </p>
          )}
          <div className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">1. Paste this redirect URL into the app</span>
            <div className="flex h-10 items-center gap-2 rounded-[10px] bg-bg pl-3 pr-1.5">
              <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{app.redirect_uri}</span>
              <button type="button" onClick={() => void copy(app.redirect_uri, "Redirect URL copied.")} className="h-[30px] rounded-lg border border-line bg-panel px-2.5 text-[12.5px] font-medium">
                Copy
              </button>
            </div>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">2. {app.provider === "microsoft" ? "Application (client) ID" : "Client ID"}</span>
              <input className="field !h-10 font-mono !text-[13px]" value={clientId} onChange={(e) => setClientId(e.target.value)} required minLength={5} autoComplete="off" placeholder={app.provider === "microsoft" ? "e.g. 3f2a…-…-9c1d" : "….apps.googleusercontent.com"} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">3. Client secret</span>
              <input className="field !h-10 !text-[13px]" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} required minLength={5} autoComplete="off" placeholder={app.secret_last4 ? `Replaces the one ending ${app.secret_last4}` : "Paste the secret value"} />
            </label>
          </div>
          {error && <p className="text-[13px] text-bad-text">{error}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <button type="submit" disabled={busy || !clientId || !secret} className="h-10 rounded-[10px] bg-accent px-4 font-semibold text-accent-on disabled:opacity-60">
              {busy ? "Saving…" : "Save and turn on"}
            </button>
            {set && (
              <button type="button" className={ghost} onClick={() => setEditing(false)}>
                Cancel
              </button>
            )}
            <span className="text-[12.5px] text-muted">The secret is stored encrypted. You won't see it again.</span>
          </div>
        </form>
      )}
    </article>
  );
}

const EMPTY_PROVIDER = { key: "", display_name: "", base_url: "", api_format: "openai", default_model: "", docs_url: "", trains_on_data: false };

/** Add a provider that speaks a known format, without a release. */
function AddProvider({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY_PROVIDER);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const field = (key: keyof typeof EMPTY_PROVIDER) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [key]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { key, ...rest } = form;
      await call(`/providers/${encodeURIComponent(key.trim().toLowerCase())}`, { ...rest, default_model: rest.default_model || null, docs_url: rest.docs_url || null }, "PUT");
      toast(`${form.display_name} added. People can connect a key for it now.`);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add it.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Add a provider" onClose={onClose} width={560}>
      <form onSubmit={(e) => void save(e)} className="flex flex-col gap-3.5 p-6">
        <h3 className="text-lg font-semibold">Add a provider</h3>
        <p className="text-[13.5px] text-muted">For a service that speaks the OpenAI, Anthropic or Gemini format. People then add their own key for it.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Name</span>
            <input className="field" value={form.display_name} onChange={field("display_name")} required />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Short key</span>
            <input className="field font-mono" value={form.key} onChange={field("key")} required pattern="[a-z0-9_-]{2,50}" placeholder="e.g. together" />
          </label>
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="text-[13px] font-medium">Address of its API</span>
            <input className="field font-mono" type="url" value={form.base_url} onChange={field("base_url")} required placeholder="https://api.example.com/v1" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Format</span>
            <select className="field" value={form.api_format} onChange={field("api_format")}>
              <option value="openai">OpenAI format</option>
              <option value="anthropic">Anthropic format</option>
              <option value="gemini">Gemini format</option>
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Default model</span>
            <input className="field font-mono" value={form.default_model} onChange={field("default_model")} />
          </label>
        </div>
        <label className="flex items-center gap-2.5 text-[13.5px]">
          <input type="checkbox" checked={form.trains_on_data} onChange={(e) => setForm({ ...form, trains_on_data: e.target.checked })} className="h-4 w-4" />
          It trains on what is sent to it (people are warned before they add a key)
        </label>
        {error && <p className="rounded-[10px] bg-bad-soft px-3 py-2 text-[13px] text-bad-text">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="h-[42px] rounded-[10px] border border-line px-4 font-medium">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="h-[42px] rounded-[10px] bg-accent px-4 font-semibold text-accent-on">
            {busy ? "Adding…" : "Add provider"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function KindPill({ p }: { p: Provider }) {
  if (p.kind === "search") return <Pill tone="brand">Web search</Pill>;
  if (p.is_local) return <Pill>Local</Pill>;
  if (p.free_tier) return <Pill tone="ok" strong>Free tier</Pill>;
  return (
    <Pill tone="run" strong>
      Paid
    </Pill>
  );
}

const PROVIDER_GRID = "grid grid-cols-[minmax(0,1.6fr)_minmax(0,0.8fr)_minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_120px] gap-3";

export function SignInAndAI({
  apps,
  providers,
  onApps,
  onProviders,
}: {
  apps: OAuthApp[] | null;
  providers: Provider[] | null;
  onApps: (apps: OAuthApp[]) => void;
  onProviders: () => Promise<void>;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const ordered = [...(providers ?? [])].sort((a, b) => Number(a.kind === "search") - Number(b.kind === "search"));

  async function toggle(p: Provider) {
    setBusy(p.key);
    try {
      await call(`/providers/${p.key}`, { enabled: !p.enabled }, "PATCH");
      await onProviders();
      toast(p.enabled ? `${p.display_name} paused for everyone. Saved keys are kept.` : `${p.display_name} is on again.`, p.enabled ? "info" : "ok");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <ScreenTitle title="Sign-in and AI">The apps people use to sign in and connect, and the AI services Baton can send work to.</ScreenTitle>

      <section aria-labelledby="oauth-h" className="flex flex-col gap-3.5">
        <div>
          <h2 id="oauth-h" className="text-[19px] font-semibold">
            One-click sign-in apps
          </h2>
          <p className="mt-1 text-[13.5px] text-muted">
            Let people sign in, and connect their mail and calendar, with one click. Baton keeps the secret; you only ever see its last four characters.
          </p>
        </div>
        <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr))]">
          {apps ? apps.map((app) => <AppCard key={`${app.provider}:${app.client_id ?? ""}`} app={app} onChanged={onApps} />) : <div className="skeleton h-64 rounded-2xl" />}
        </div>
      </section>

      <section aria-labelledby="prov-h" className="flex flex-col gap-3.5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="prov-h" className="text-[19px] font-semibold">
              AI providers
            </h2>
            <p className="mt-1 max-w-[720px] text-[13.5px] text-muted">
              The AI services people can connect a key for. Pausing one stops Baton sending work to it, for everyone. People's saved keys are kept.
            </p>
          </div>
          <button type="button" onClick={() => setAdding(true)} className="inline-flex h-10 items-center gap-1.5 rounded-[10px] border border-accent-line bg-accent-soft px-3.5 font-semibold text-accent-text">
            <Icon name="plus" size={15} strokeWidth={2.2} />
            Add a provider
          </button>
        </div>

        <div className="overflow-hidden rounded-2xl border border-line bg-panel">
          <div className="overflow-x-auto">
            <div role="table" aria-label="AI providers" className="min-w-[900px]">
              <div role="row" className={`${PROVIDER_GRID} border-b border-line px-5 py-2.5 text-xs font-semibold text-muted`} style={{ background: "var(--staff-head)" }}>
                <div role="columnheader">Provider</div>
                <div role="columnheader">Kind</div>
                <div role="columnheader">Default model</div>
                <div role="columnheader">Trains on data</div>
                <div role="columnheader">People connected</div>
                <div role="columnheader" className="text-right">
                  Available
                </div>
              </div>
              {!providers && <div className="skeleton m-5 h-40" />}
              {ordered.map((p) => (
                <div key={p.key} role="row" className={`${PROVIDER_GRID} items-center border-b border-raised px-5 py-3 last:border-b-0`} style={p.enabled ? undefined : { background: "color-mix(in srgb, var(--ask-soft) 30%, var(--panel))" }}>
                  <div role="cell" className="flex min-w-0 items-center gap-2.5">
                    <span aria-hidden="true" className="inline-flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg border border-line bg-bg text-[13px] font-semibold">
                      {p.is_local ? "L" : p.display_name.charAt(0)}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-semibold">{p.display_name}</div>
                      {!p.enabled && (
                        <div className="text-xs text-ask-text">
                          Paused{p.paused_at ? ` ${new Date(p.paused_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}
                          {p.paused_by_email ? ` by ${staffName(p.paused_by_email)}` : ""}
                        </div>
                      )}
                    </div>
                  </div>
                  <div role="cell">
                    <KindPill p={p} />
                  </div>
                  <div role="cell" className="truncate font-mono text-[12.5px]">
                    {p.is_local ? "set by each person" : (p.default_model ?? "—")}
                  </div>
                  <div role="cell" className="text-[13px]">
                    {p.trains_on_data ? <span className="font-semibold text-ask-text">Yes</span> : <span className="text-muted">No</span>}
                  </div>
                  <div role="cell" className="text-[13px] tabular-nums">
                    {p.people_connected.toLocaleString("en-GB")}
                  </div>
                  <div role="cell" className="flex items-center justify-end gap-2">
                    <span className="text-[12.5px] text-muted">{p.enabled ? "On" : "Paused"}</span>
                    <Switch checked={p.enabled} label={`${p.display_name} available`} disabled={busy === p.key} onChange={() => void toggle(p)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="px-5 py-3 text-[12.5px] text-muted">"Trains on data" is what the provider says about its own service. People see the same label when they add a key.</div>
        </div>
      </section>

      {adding && (
        <AddProvider
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            void onProviders();
          }}
        />
      )}
    </div>
  );
}

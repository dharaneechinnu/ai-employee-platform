import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Icon, type IconName } from "../components/icons";
import Modal from "../components/Modal";
import PermissionChoice, { PERMISSION_LABEL, type Setting } from "../components/PermissionChoice";
import {
  Button,
  Chip,
  Empty,
  ErrorNote,
  Input,
  PageBody,
  PageHeader,
  Spinner,
  StatusChip,
  Switch,
  relativeTime,
  useToast,
} from "../components/ui";
import {
  ApiError,
  api,
  type AvailableConnection,
  type ConnectionItem,
  type ServiceInfo,
  type ToolEntry,
} from "../lib/api";
import { effectLabel, toolLabel } from "../lib/labels";

/**
 * The outside apps your assistant works in.
 *
 * Google and Microsoft connect with one click: you sign in with
 * the provider and approves the listed permissions. Nothing secret is
 * ever shown here, only which account is connected and whether it works.
 */

const APP_ICONS: Record<string, IconName> = {
  Gmail: "mail",
  Outlook: "mail",
  Email: "mail",
  Calendar: "calendar",
  Drive: "folder",
  OneDrive: "folder",
  Database: "database",
  Code: "terminal",
  Issues: "tasks",
  "Pull requests": "tree",
  Actions: "check",
};

const BRAND: Record<string, { mark: string; gradient: string }> = {
  google: { mark: "G", gradient: "linear-gradient(135deg,#4285F4,#34A853 55%,#FBBC05 80%,#EA4335)" },
  microsoft: { mark: "M", gradient: "linear-gradient(135deg,#F25022,#7FBA00 40%,#00A4EF 70%,#FFB900)" },
  email: { mark: "@", gradient: "linear-gradient(135deg,var(--accent),var(--spark))" },
  database: { mark: "DB", gradient: "linear-gradient(135deg,#336791,#5B8FC7)" },
  github: { mark: "GH", gradient: "linear-gradient(135deg,#24292f,#57606a)" },
};

function BrandTile({ kind, size = 48 }: { kind: string; size?: number }) {
  const brand = BRAND[kind] ?? { mark: kind.charAt(0).toUpperCase(), gradient: "var(--accent)" };
  return (
    <span
      aria-hidden="true"
      className="flex shrink-0 items-center justify-center rounded-[14px] p-[2px]"
      style={{ width: size, height: size, background: brand.gradient }}
    >
      <span className="flex h-full w-full items-center justify-center rounded-[12px] bg-panel font-display text-lg font-bold">
        {brand.mark}
      </span>
    </span>
  );
}

/**
 * Register your own Google or Microsoft app.
 *
 * The platform can register one app for everyone, but that puts the
 * operator in the critical path of everyone's setup. This is the
 * other route: your own Google Cloud project, your own name on the
 * consent screen, and nobody else to wait for.
 */
function OwnAppForm({
  option,
  onDone,
  onClose,
}: {
  option: AvailableConnection;
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [redirect, setRedirect] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // Shown before anything is saved: it has to go into Google's
    // console first, and a mismatch here is the usual reason a
    // sign-in fails.
    setRedirect(`${window.location.origin.replace(":5173", ":8000")}/api/v1/oauth/${option.kind}/callback`);
  }, [option.kind]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await api.put(`/me/connections/oauth-apps/${option.kind}`, {
        client_id: clientId,
        client_secret: secret,
      });
      toast(`${option.display_name} sign-in is on for your account.`);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Use your own app" onClose={onClose}>
      <form onSubmit={save} className="flex flex-col gap-4 overflow-y-auto p-5">
      <div className="flex items-center gap-3">
        <h2 className="font-display text-[17px] font-semibold">
          Use your own {option.display_name} app
        </h2>
        <button type="button" className="icon-btn ml-auto h-9 w-9" aria-label="Close" onClick={onClose}>
          <Icon name="x" size={16} />
        </button>
      </div>

      <p className="text-[13px] leading-normal text-muted">
        Create an OAuth client in your own {option.kind === "google" ? "Google Cloud" : "Microsoft Entra"}{" "}
        project, then paste its ID and secret here. Your own app name appears on the sign-in
        screen, and nobody else has to set anything up first.
      </p>

      <div className="flex flex-col gap-1.5">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
          Add this as the redirect URI first
        </span>
        <div className="flex items-center gap-2 rounded-xl border border-line bg-sunken px-3 py-2">
          <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{redirect}</code>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              void navigator.clipboard.writeText(redirect).then(
                () => toast("Copied."),
                () => toast("Copy failed. Select it and copy by hand.", "bad"),
              );
            }}
          >
            <Icon name="copy" size={15} />
            Copy
          </Button>
        </div>
        <span className="text-[13px] text-dim">
          It must match to the character, including http vs https.
        </span>
      </div>

      <Input label="Client ID" value={clientId} onChange={setClientId} required mono autoComplete="off" />
      <Input
        label="Client secret"
        type="password"
        value={secret}
        onChange={setSecret}
        required
        mono
        autoComplete="off"
      />
      <ErrorNote message={error} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!clientId || !secret || saving}>
          {saving ? "Saving…" : "Save and switch on"}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
      <p className="text-[13px] text-dim">
        The secret is encrypted and never shown again. If your consent screen is still in
        &ldquo;Testing&rdquo;, Google expires these connections after seven days — set it to
        production once you are past trying it out.
      </p>
    </form>
    </Modal>
  );
}

export default function Connections() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [available, setAvailable] = useState<AvailableConnection[] | null>(null);
  const [connected, setConnected] = useState<ConnectionItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [manual, setManual] = useState<AvailableConnection | null>(null);
  const [ownApp, setOwnApp] = useState<AvailableConnection | null>(null);
  const [sharing, setSharing] = useState<AvailableConnection | null>(null);
  const [tools, setTools] = useState<Record<string, ToolEntry>>({});

  async function load() {
    const [options, items] = await Promise.all([
      api.get<AvailableConnection[]>(`/me/connections/available`),
      api.get<ConnectionItem[]>(`/me/connections`),
    ]);
    setAvailable(options);
    setConnected(items);
    const catalogue = await api.get<ToolEntry[]>(`/me/tools`).catch(() => [] as ToolEntry[]);
    setTools(Object.fromEntries(catalogue.map((t) => [t.name, t])));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, ["me"]);

  // Coming back from Google or Microsoft: say what happened, once.
  useEffect(() => {
    const done = params.get("connected");
    const failed = params.get("error");
    if (!done && !failed) return;
    if (done) toast(`Connected ${params.get("account") ?? done}. Your assistant can use it now.`);
    if (failed) toast(failed, "bad");
    setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Sends the person to the provider, asking only for what they chose. */
  async function startOAuth(option: AvailableConnection, services: Record<string, "read" | "edit">) {
    setBusy(option.kind);
    try {
      const { authorize_url } = await api.post<{ authorize_url: string }>(
        `/me/connections/oauth/${option.kind}/start`,
        { services },
      );
      window.location.assign(authorize_url);
    } catch (err) {
      setBusy(null);
      // Rethrown so the share step can show it where the person is looking.
      throw err;
    }
  }

  async function test(item: ConnectionItem) {
    setBusy(item.id);
    try {
      const result = await api.post<ConnectionItem>(`/me/connections/${item.id}/test`);
      toast(result.status === "connected" ? `${item.label} works.` : `${item.label}: ${result.last_error ?? "test failed"}`, result.status === "connected" ? "ok" : "bad");
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function toggle(item: ConnectionItem, enabled: boolean) {
    await api.patch(`/me/connections/${item.id}`, { enabled });
    toast(enabled ? `${item.label} resumed.` : `${item.label} paused. Tools that need it will say so.`, "info");
    await load();
  }

  async function remove(item: ConnectionItem) {
    if (!window.confirm(`Disconnect ${item.label}? Your assistant will lose access to it straight away.`)) return;
    await api.del(`/me/connections/${item.id}`);
    toast(`${item.label} disconnected.`, "info");
    await load();
  }

  if (!available) {
    return (
      <>
        <PageHeader crumb="Settings" title="Connections" />
        <Spinner />
      </>
    );
  }

  const byKind = (kind: string) => connected.filter((c) => c.kind === kind);

  return (
    <>
      <PageHeader crumb="Settings" title="Connections">
        <span className="max-w-[400px] text-[13px] leading-snug text-muted">
          Let your assistant work in your email, calendar and files. Every send still follows your Permissions.
        </span>
      </PageHeader>

      <PageBody>
        <section className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(380px,100%),1fr))]">
          {available.map((option, i) => {
            const items = byKind(option.kind);
            const oauth = option.auth === "oauth";
            return (
              <article
                key={option.kind}
                className="card lift rise flex flex-col gap-4 p-5"
                style={{ animationDelay: `${i * 0.07}s` }}
                data-coach="connection-card"
              >
                <div className="flex items-start gap-3.5">
                  <BrandTile kind={option.kind} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-display text-lg font-semibold">{option.display_name}</h2>
                      {oauth && <Chip tone="brand" dot={false}>one click</Chip>}
                    </div>
                    <p className="text-[13px] leading-snug text-muted">{option.description}</p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {option.apps.map((app) => (
                    <span key={app} className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-xs text-muted">
                      <Icon name={APP_ICONS[app] ?? "sparkle"} size={13} />
                      {app}
                    </span>
                  ))}
                  <span className="ml-auto self-center font-mono text-xs text-dim">{option.tools.length} tools</span>
                </div>

                {items.map((item) => (
                  <ConnectedRow
                    key={item.id}
                    item={item}
                    busy={busy === item.id}
                    onTest={() => void test(item)}
                    onToggle={(on) => void toggle(item, on)}
                    onRemove={() => void remove(item)}
                    onReconnect={oauth ? () => setSharing(option) : undefined}
                  />
                ))}

                {option.tools.some((name) => tools[name]) && (
                  <ToolPermissions
                    names={option.tools}
                    tools={tools}
                    open={items.length > 0}
                    onSaved={(name, setting) =>
                      setTools((current) => ({ ...current, [name]: { ...current[name], effective_setting: setting } }))
                    }
                  />
                )}

                {(
                  <div className="mt-auto flex flex-wrap items-center gap-2">
                    {oauth ? (
                      <Button
                        size="sm"
                        variant={items.length ? "ghost" : "brand"}
                        icon="link"
                        disabled={!option.configured || !option.allowed || busy === option.kind}
                        onClick={() => setSharing(option)}
                      >
                        {busy === option.kind ? "Opening sign-in…" : items.length ? "Change what is shared" : `Connect ${option.display_name}`}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant={items.length ? "ghost" : "brand"}
                        icon="plus"
                        disabled={!option.allowed}
                        onClick={() => setManual(option)}
                      >
                        {items.length ? "Add another" : "Connect"}
                      </Button>
                    )}
                    {!option.allowed ? (
                      <span className="flex items-start gap-2 text-xs text-ask-text">
                        <Icon name="lock" size={14} className="mt-px shrink-0" />
                        {option.blocked_note ??
                          `${option.display_name} is not available on your plan.`}
                      </span>
                    ) : null}
                    {option.allowed && oauth && !option.configured && (
                      <button
                        type="button"
                        className="text-xs text-accent-text hover:underline"
                        onClick={() => setOwnApp(option)}
                      >
                        {/* Not a dead end. Either the platform registers
                            one app for everybody, or you do it
                            for yourself — and nobody has to wait for the
                            other. */}
                        One-click sign-in isn't set up yet. Use your own {option.display_name} app →
                      </button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </section>

        {connected.length === 0 && (
          <Empty
            message="Nothing connected yet"
            hint="Connect Google or Microsoft above, then ask your assistant to work in them."
          />
        )}

        {sharing && (
          <ShareStep
            option={sharing}
            onClose={() => setSharing(null)}
            onStart={(services) => startOAuth(sharing, services)}
          />
        )}
        {manual && <ManualForm option={manual} onClose={() => setManual(null)} onSaved={() => { setManual(null); void load(); }} />}
        {ownApp && (
          <OwnAppForm
            option={ownApp}
            onDone={() => void load()}
            onClose={() => setOwnApp(null)}
          />
        )}
      </PageBody>
    </>
  );
}

/**
 * Each tool this app gives your assistant, with its permission right
 * here: the place people connect an app is where they decide what may
 * be done with it.
 */
function ToolPermissions({
  names,
  tools,
  open,
  onSaved,
}: {
  names: string[];
  tools: Record<string, ToolEntry>;
  open: boolean;
  onSaved: (name: string, setting: Setting) => void;
}) {
  const rows = names.map((n) => tools[n]).filter((t): t is ToolEntry => !!t);
  const asking = rows.filter((t) => t.effective_setting === "ask").length;
  const allowed = rows.filter((t) => t.effective_setting === "auto").length;
  return (
    <details className="group rounded-xl border border-line bg-raised" open={open} data-coach="connection-permissions">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2.5 px-3.5 py-2.5 text-sm font-medium">
        <Icon name="lock" size={15} className="text-accent-text" />
        <span className="flex-1">What can your assistant do here?</span>
        <span className="text-xs font-normal text-dim">
          {allowed} always · {asking} ask
        </span>
        <Icon name="chevrons" size={14} className="text-dim" />
      </summary>
      <ul className="flex flex-col border-t border-line">
        {rows.map((tool) => (
          <li key={tool.name} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-3.5 py-3 last:border-0">
            <span className="flex min-w-[170px] flex-1 flex-col">
              <span className="text-sm font-medium" title={tool.name}>{toolLabel(tool.name)}</span>
              {/* Reading is the normal case, so only changes are labelled. */}
              {tool.side_effect !== "read" && (
                <span className={`text-xs ${tool.side_effect === "destructive" ? "text-bad-text" : "text-dim"}`}>
                  {effectLabel(tool.side_effect)}
                </span>
              )}
            </span>
            {true ? (
              <PermissionChoice
                tool={tool}
                size="sm"
                onSaved={(setting) => onSaved(tool.name, setting)}
              />
            ) : (
              <Chip tone={tool.effective_setting === "auto" ? "ok" : tool.effective_setting === "ask" ? "ask" : "bad"} dot={false}>
                {PERMISSION_LABEL[tool.effective_setting as Setting]}
              </Chip>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

function ConnectedRow({
  item,
  busy,
  onTest,
  onToggle,
  onRemove,
  onReconnect,
}: {
  item: ConnectionItem;
  busy: boolean;
  onTest: () => void;
  onToggle: (on: boolean) => void;
  onRemove: () => void;
  onReconnect?: () => void;
}) {
  const live = item.enabled && item.status === "connected";
  return (
    <div
      className="flex flex-col gap-2.5 rounded-xl border bg-raised p-3.5"
      style={{ borderColor: item.status === "needs_reconnect" || item.status === "failed" ? "var(--bad)" : "var(--line)" }}
    >
      <div className="flex items-center gap-3">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          {live && <span className="absolute inset-0 rounded-full bg-ok" style={{ animation: "pulse-run 2s ease-out infinite" }} />}
          <span className={`relative h-2.5 w-2.5 rounded-full ${live ? "bg-ok" : "bg-line2"}`} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{item.account ?? item.label}</div>
          <div className="text-xs text-dim">
            {item.last_tested_at ? `checked ${relativeTime(item.last_tested_at)}` : "not checked yet"}
            {!item.enabled && " · paused"}
          </div>
        </div>
        <StatusChip status={item.status} />
        {<Switch checked={item.enabled} onChange={onToggle} label={item.enabled ? `Pause ${item.label}` : `Resume ${item.label}`} />}
      </div>
      {item.last_error && <ErrorNote message={item.last_error} />}
      {(
        <div className="flex flex-wrap gap-2">
          {item.status === "needs_reconnect" && onReconnect ? (
            <Button size="sm" onClick={onReconnect} icon="link">
              Reconnect
            </Button>
          ) : (
            <Button size="sm" variant="ghost" disabled={busy} onClick={onTest}>
              {busy ? "Checking…" : "Check it works"}
            </Button>
          )}
          <Button size="sm" variant="danger-ghost" onClick={onRemove}>
            Disconnect
          </Button>
        </div>
      )}
    </div>
  );
}

/** What a new connection asks for when the person has not chosen. */
const SHARE_DEFAULTS: Record<string, Record<string, "read" | "edit">> = {
  google: { "google.gmail": "edit", "google.calendar": "edit", "google.drive": "read" },
  microsoft: { "microsoft.mail": "edit", "microsoft.calendar": "edit", "microsoft.files": "read" },
};

type Level = "read" | "edit";

/** What each choice lets your assistant and agents do, in plain words. */
const SHARE_WORDS: Record<string, { read: string; edit?: string; tip?: string }> = {
  "google.gmail": { read: "Search and read your email.", edit: "Also save drafts and send email." },
  "google.calendar": { read: "See your events.", edit: "Also add events." },
  "google.drive": { read: "Find and read your files." },
  "google.sheets": {
    read: "Read your spreadsheets.",
    edit: "Also create sheets and add rows.",
    tip: "Turn this on for agents that fill in a spreadsheet.",
  },
  "microsoft.mail": { read: "Search and read your email.", edit: "Also save drafts and send email." },
  "microsoft.calendar": { read: "See your events.", edit: "Also add events." },
  "microsoft.files": { read: "Find and read your files." },
};

const LEVEL_LABEL = { off: "Off", read: "Look", edit: "Change" } as const;

/**
 * "What do you want to share?" A popup shown before the sign-in. For
 * each part of the app, one choice: Off, Look (read only) or Change
 * (read and edit). Only what is chosen is asked of the provider.
 */
function ShareStep({
  option,
  onClose,
  onStart,
}: {
  option: AvailableConnection;
  onClose: () => void;
  onStart: (services: Record<string, Level>) => Promise<void>;
}) {
  const [services, setServices] = useState<ServiceInfo[] | null>(null);
  const [picked, setPicked] = useState<Record<string, Level>>({});
  const [error, setError] = useState<string | null>(null);
  const [going, setGoing] = useState(false);

  useEffect(() => {
    void api
      .get<ServiceInfo[]>(`/me/connections/services`)
      .then((all) => {
        const mine = all.filter((s) => s.app === option.kind);
        setServices(mine);
        // Start from what is held now when reconnecting, else from the defaults.
        const start: Record<string, Level> = {};
        const connected = mine.some((s) => s.granted);
        for (const s of mine) {
          const level = connected
            ? s.granted?.edit
              ? "edit"
              : s.granted?.read
                ? "read"
                : undefined
            : SHARE_DEFAULTS[option.kind]?.[s.id];
          if (!level) continue;
          if (level === "edit" && !s.allowed.edit) {
            if (s.allowed.read) start[s.id] = "read";
          } else if (s.allowed[level]) start[s.id] = level;
        }
        setPicked(start);
      })
      .catch(() => setError("Could not load what can be shared."));
  }, [option.kind]);

  function set(id: string, level: Level | null) {
    setPicked((current) => {
      const next = { ...current };
      if (level === null) delete next[id];
      else next[id] = level;
      return next;
    });
  }

  async function go() {
    setError(null);
    setGoing(true);
    try {
      await onStart(picked);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the sign-in.");
      setGoing(false);
    }
  }

  const chosen = Object.keys(picked).length;
  const changing = Object.values(picked).filter((l) => l === "edit").length;
  const reconnecting = services?.some((s) => s.granted) ?? false;

  return (
    <Modal title={`Connect ${option.display_name}`} onClose={onClose}>
      <div className="flex items-start gap-3 border-b border-line px-5 py-4" data-coach="share-step">
        <BrandTile kind={option.kind} size={40} />
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-[18px] font-semibold">
            {reconnecting ? `Update what ${option.display_name} shares` : `Connect ${option.display_name}`}
          </h3>
          <p className="text-[13.5px] text-muted">
            Choose what your assistant and agents may do. You can change this any time.
          </p>
        </div>
        <button type="button" className="icon-btn h-10 w-10" aria-label="Close" onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {!services ? (
          error ? <ErrorNote message={error} /> : <Spinner rows={3} />
        ) : (
          <ul className="flex flex-col gap-2.5">
            {services.map((s) => {
              const level = picked[s.id] as Level | undefined;
              const closed = !s.allowed.read;
              const words = SHARE_WORDS[s.id];
              const current: "off" | Level = level ?? "off";
              const was: "off" | Level = s.granted?.edit ? "edit" : s.granted?.read ? "read" : "off";
              const changed = reconnecting && current !== was;
              const choices: ("off" | Level)[] = ["off", "read", ...(s.can_edit ? (["edit"] as const) : [])];
              return (
                <li
                  key={s.id}
                  className={`rounded-xl border px-3.5 py-3 ${level ? "border-accent-line bg-accent-soft/40" : "border-line"}`}
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <div className="min-w-[170px] flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[14.5px] font-medium">{s.name}</span>
                        {changed && (
                          <Chip tone="brand" dot={false}>
                            will change
                          </Chip>
                        )}
                      </div>
                      <p className="text-[13px] text-muted">
                        {closed
                          ? (s.note ?? "Turned off for you by the platform.")
                          : current === "edit" && words?.edit
                            ? words.edit
                            : current === "off" && words?.tip
                              ? words.tip
                              : (words?.read ?? "Look at it.")}
                      </p>
                    </div>
                    <div
                      role="radiogroup"
                      aria-label={`${s.name}: how much to share`}
                      className="inline-flex rounded-lg border border-line bg-raised p-0.5"
                    >
                      {choices.map((o) => {
                        const disabled = closed ? o !== "off" : o === "edit" && !s.allowed.edit;
                        const active = current === o;
                        return (
                          <button
                            key={o}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            disabled={disabled}
                            className={`rounded-md px-3 py-1.5 text-[13px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                              active
                                ? o === "edit"
                                  ? "bg-accent font-medium text-accent-on"
                                  : "bg-panel font-medium text-ink shadow-sm"
                                : "text-muted hover:text-ink"
                            }`}
                            onClick={() => set(s.id, o === "off" ? null : o)}
                          >
                            {LEVEL_LABEL[o]}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-3">
          <ErrorNote message={services ? error : null} />
        </div>
      </div>

      <div className="flex flex-col gap-2.5 border-t border-line px-5 py-4">
        <p className="text-[13px] text-muted" aria-live="polite">
          {chosen === 0
            ? "Choose at least one to continue."
            : `Sharing ${chosen} ${chosen === 1 ? "part" : "parts"}${changing > 0 ? `, ${changing} that can make changes` : ", all look-only"}. ${option.display_name} will show you these before you agree.`}
        </p>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button icon="link" disabled={going || !services || chosen === 0} onClick={() => void go()}>
            {going ? "Opening sign-in…" : `Continue to ${option.display_name}`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ManualForm({
  option,
  onClose,
  onSaved,
}: {
  option: AvailableConnection;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    const config: Record<string, string | number> = {};
    for (const field of option.fields) {
      const value = values[field.key]?.trim();
      if (!value) continue;
      config[field.key] = field.key.endsWith("port") ? Number(value) : value;
    }
    try {
      await api.post(`/me/connections`, {
        kind: option.kind,
        label: label || String(config.username ?? config.database ?? option.display_name),
        secret,
        config,
      });
      toast(`${option.display_name} saved. Check it works from its card.`);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Connect an account" onClose={onClose}>
      <form onSubmit={save} className="flex flex-col gap-4 overflow-y-auto p-5">
      <div className="flex items-center gap-3">
        <BrandTile kind={option.kind} size={40} />
        <h2 className="flex-1 font-display text-[17px] font-semibold">Connect {option.display_name}</h2>
        <button type="button" className="icon-btn h-10 w-10" aria-label="Close" onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))]">
        <Input label="Name for this connection" value={label} onChange={setLabel} placeholder="Support inbox" />
        {option.fields.map((field) => (
          <Input
            key={field.key}
            label={field.label}
            value={values[field.key] ?? ""}
            onChange={(v) => setValues((current) => ({ ...current, [field.key]: v }))}
            placeholder={field.placeholder}
          />
        ))}
        <Input label={option.secret_label ?? "Password"} type="password" value={secret} onChange={setSecret} required mono autoComplete="off" />
      </div>
      <ErrorNote message={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!secret || saving}>
          {saving ? "Saving…" : "Save connection"}
        </Button>
        <span className="text-[13px] text-dim">Encrypted, and never shown again. Use an app password or a read-only user.</span>
      </div>
    </form>
    </Modal>
  );
}

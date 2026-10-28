import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Icon, type IconName } from "../components/icons";
import Modal from "../components/Modal";
import PermissionChoice, { type Setting } from "../components/PermissionChoice";
import { ServiceMark, type ServiceKey } from "../components/ServiceMark";
import {
  Button,
  ErrorNote,
  HoldButton,
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
import { notifySetup } from "../lib/setup";

/**
 * The outside apps your assistant works in, one card each.
 *
 * Google and Microsoft connect with one click: you sign in with the
 * provider and approve the listed permissions. Nothing secret is ever
 * shown here, only which account is connected and whether it works.
 */

type Level = "read" | "edit";

/** Real logos where we have them; a plain icon where we do not. */
const MARKS: Record<string, ServiceKey[]> = {
  google: ["gmail", "gdrive", "gcalendar"],
  microsoft: ["outlook", "onedrive"],
  database: ["postgres"],
};

const PLAIN_ICON: Record<string, IconName> = {
  email: "mail",
  github: "code",
  slack: "chat",
  teams: "chat",
};

function KindMark({ kind, size = 40 }: { kind: string; size?: number }) {
  const marks = MARKS[kind];
  const many = marks && marks.length > 1;
  return (
    <span
      aria-hidden="true"
      className="grid shrink-0 place-items-center rounded-xl border border-line bg-raised"
      style={{ width: size, height: size }}
    >
      {marks ? (
        <span className={many ? "grid grid-cols-2 place-items-center gap-0.5" : ""}>
          {marks.map((m) => (
            <ServiceMark key={m} service={m} size={many ? size * 0.34 : size * 0.58} />
          ))}
        </span>
      ) : (
        <Icon name={PLAIN_ICON[kind] ?? "link"} size={size * 0.5} className="text-muted" />
      )}
    </span>
  );
}

function Pill({ children, tone }: { children: React.ReactNode; tone?: "ok" | "accent" | "bad" }) {
  const look =
    tone === "ok"
      ? "bg-ok-soft text-ok-text"
      : tone === "accent"
        ? "bg-accent-soft text-accent-text"
        : tone === "bad"
          ? "bg-bad-soft text-bad-text"
          : "bg-raised text-muted";
  return <span className={`max-w-full truncate rounded-full px-2 py-0.5 font-medium ${look}`}>{children}</span>;
}

/** What a new connection asks for when the person has not chosen. */
const SHARE_DEFAULTS: Record<string, Record<string, Level>> = {
  google: { "google.gmail": "edit", "google.calendar": "edit", "google.drive": "read" },
  microsoft: { "microsoft.mail": "edit", "microsoft.calendar": "edit", "microsoft.files": "read" },
};

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

/** Start from what is held now when reconnecting, else from the defaults. */
function initialPicks(kind: string, services: ServiceInfo[]): Record<string, Level> {
  const start: Record<string, Level> = {};
  const connected = services.some((s) => s.granted);
  for (const s of services) {
    const level: Level | undefined = connected
      ? s.granted?.edit
        ? "edit"
        : s.granted?.read
          ? "read"
          : undefined
      : SHARE_DEFAULTS[kind]?.[s.id];
    if (!level) continue;
    if (level === "edit" && !s.allowed.edit) {
      if (s.allowed.read) start[s.id] = "read";
    } else if (s.allowed[level]) start[s.id] = level;
  }
  return start;
}

/** The levels already held, to send again when someone reconnects in one click. */
function heldLevels(services: ServiceInfo[]): Record<string, Level> {
  const held: Record<string, Level> = {};
  for (const s of services) {
    if (s.granted?.edit) held[s.id] = "edit";
    else if (s.granted?.read) held[s.id] = "read";
  }
  return held;
}

function broken(item: ConnectionItem): boolean {
  return item.status === "needs_reconnect" || item.status === "failed";
}

/** Plain list of what agents can do, from the labels of the tools this app brings. */
function abilities(option: AvailableConnection): string[] {
  return option.tools.map((name) => toolLabel(name));
}

export default function Connections() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [available, setAvailable] = useState<AvailableConnection[] | null>(null);
  const [connected, setConnected] = useState<ConnectionItem[]>([]);
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [tools, setTools] = useState<Record<string, ToolEntry>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [ownApp, setOwnApp] = useState<AvailableConnection | null>(null);

  const load = useCallback(async () => {
    const [options, items] = await Promise.all([
      api.get<AvailableConnection[]>(`/me/connections/available`),
      api.get<ConnectionItem[]>(`/me/connections`),
    ]);
    setAvailable(options);
    setConnected(items);
    const [svc, catalogue] = await Promise.all([
      api.get<ServiceInfo[]>(`/me/connections/services`).catch(() => [] as ServiceInfo[]),
      api.get<ToolEntry[]>(`/me/tools`).catch(() => [] as ToolEntry[]),
    ]);
    setServices(svc);
    setTools(Object.fromEntries(catalogue.map((t) => [t.name, t])));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Coming back from Google or Microsoft: say what happened, once.
  useEffect(() => {
    const done = params.get("connected");
    const failed = params.get("error");
    if (!done && !failed) return;
    if (done) {
      toast(`Connected ${params.get("account") ?? done}. Your assistant can use it now.`);
      setOpen(done);
      setFresh(done);
      notifySetup();
    }
    if (failed) toast(failed, "bad");
    setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Sends the person to the provider, asking only for what they chose. */
  async function startOAuth(option: AvailableConnection, picked: Record<string, Level>) {
    setBusy(option.kind);
    try {
      const { authorize_url } = await api.post<{ authorize_url: string }>(
        `/me/connections/oauth/${option.kind}/start`,
        { services: picked },
      );
      window.location.assign(authorize_url);
    } catch (err) {
      setBusy(null);
      // Rethrown so the panel can show it where the person is looking.
      throw err;
    }
  }

  /** One click from the card: sign in again with what was shared before. */
  async function reconnect(option: AvailableConnection) {
    const held = heldLevels(services.filter((s) => s.app === option.kind));
    if (Object.keys(held).length === 0) {
      setOpen(option.kind);
      return;
    }
    try {
      await startOAuth(option, held);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start the sign-in.", "bad");
    }
  }

  async function test(item: ConnectionItem) {
    setBusy(item.id);
    try {
      const result = await api.post<ConnectionItem>(`/me/connections/${item.id}/test`);
      toast(
        result.status === "connected" ? `${item.label} works.` : `${item.label}: ${result.last_error ?? "test failed"}`,
        result.status === "connected" ? "ok" : "bad",
      );
      notifySetup();
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
    await api.del(`/me/connections/${item.id}`);
    toast(`${item.label} disconnected.`, "info");
    setFresh(null);
    notifySetup();
    await load();
  }

  const byKind = useMemo(() => {
    const map = new Map<string, ConnectionItem[]>();
    for (const c of connected) map.set(c.kind, [...(map.get(c.kind) ?? []), c]);
    return map;
  }, [connected]);

  if (!available) {
    return (
      <>
        <PageHeader crumb="Settings" title="Connections" />
        <Spinner />
      </>
    );
  }

  const panel = open ? available.find((o) => o.kind === open) : undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="min-w-0 flex-1">
        <PageHeader crumb="Settings" title="Connections">
          <span className="max-w-[400px] text-[13px] leading-snug text-muted">
            Let your assistant work in your email, calendar and files. Every send still follows your Permissions.
          </span>
        </PageHeader>

        <PageBody>
          <section className="stagger grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr))]">
            {available.map((option) => (
              <ConnectionCard
                key={option.kind}
                option={option}
                items={byKind.get(option.kind) ?? []}
                active={open === option.kind}
                busy={busy === option.kind}
                onOpen={() => setOpen(option.kind)}
                onReconnect={() => void (option.auth === "oauth" ? reconnect(option) : setOpen(option.kind))}
              />
            ))}
          </section>

          <p className="text-[13px] text-dim">
            Sign-in details are encrypted and never shown again. Disconnecting takes access away straight away.
          </p>
        </PageBody>
      </div>

      {panel && (
        <ConnectionPanel
          key={panel.kind}
          option={panel}
          items={byKind.get(panel.kind) ?? []}
          services={services.filter((s) => s.app === panel.kind)}
          tools={tools}
          busy={busy}
          fresh={fresh === panel.kind}
          onClose={() => setOpen(null)}
          onStart={(picked) => startOAuth(panel, picked)}
          onOwnApp={() => setOwnApp(panel)}
          onTest={(item) => void test(item)}
          onToggle={(item, on) => void toggle(item, on)}
          onRemove={(item) => void remove(item)}
          onSavedTool={(name, setting) =>
            setTools((current) => ({ ...current, [name]: { ...current[name], effective_setting: setting } }))
          }
          onSaved={() => {
            setFresh(panel.kind);
            notifySetup();
            void load();
          }}
        />
      )}

      {ownApp && <OwnAppForm option={ownApp} onDone={() => void load()} onClose={() => setOwnApp(null)} />}
    </div>
  );
}

function ConnectionCard({
  option,
  items,
  active,
  busy,
  onOpen,
  onReconnect,
}: {
  option: AvailableConnection;
  items: ConnectionItem[];
  active: boolean;
  busy: boolean;
  onOpen: () => void;
  onReconnect: () => void;
}) {
  const broke = items.find(broken);
  const first = items[0];
  const can = abilities(option);
  return (
    <article
      className={`card lift flex flex-col ${active ? "card-on" : ""}`}
      style={broke ? { borderColor: "var(--bad)" } : undefined}
      data-coach="connection-card"
    >
      <button
        type="button"
        onClick={onOpen}
        aria-pressed={active}
        className="flex flex-1 flex-col gap-3 rounded-[inherit] p-4 text-left"
      >
        <div className="flex items-center gap-3">
          <KindMark kind={option.kind} />
          <div className="min-w-0 flex-1">
            <div className="truncate font-display text-[16px] font-semibold">{option.display_name}</div>
            <div className="truncate text-[12px] text-dim">
              {first
                ? `${first.account ?? first.label}${items.length > 1 ? ` and ${items.length - 1} more` : ""}`
                : "Not connected"}
            </div>
          </div>
          {first && (broke ? <StatusChip status={broke.status} /> : <StatusChip status={first.enabled ? first.status : "paused"} />)}
        </div>
        <p className="line-clamp-3 text-[13px] leading-normal text-muted">
          {first ? "Agents can now: " : "Lets agents: "}
          {can.slice(0, 4).join(", ").toLowerCase().replace(/^./, (c) => c.toUpperCase())}
          {can.length > 4 ? " and more." : "."}
        </p>
        <div className="flex flex-wrap gap-1.5 text-[11.5px]">
          {option.auth === "oauth" && <Pill tone="accent">One click</Pill>}
          {!option.allowed && <Pill>Not on your plan</Pill>}
          {option.allowed && option.auth === "oauth" && !option.configured && <Pill>Needs setup</Pill>}
        </div>
        <span className="mt-auto flex items-center gap-1 text-[13px] font-medium text-accent-text">
          {first ? "Manage" : "Connect"}
          <Icon name="chevron" size={14} />
        </span>
      </button>
      {broke && (
        <div className="border-t border-line px-4 py-3">
          <Button size="sm" icon="link" disabled={busy} onClick={onReconnect}>
            {busy ? "Opening sign-in…" : "Reconnect"}
          </Button>
        </div>
      )}
    </article>
  );
}

function ConnectionPanel({
  option,
  items,
  services,
  tools,
  busy,
  fresh,
  onClose,
  onStart,
  onOwnApp,
  onTest,
  onToggle,
  onRemove,
  onSavedTool,
  onSaved,
}: {
  option: AvailableConnection;
  items: ConnectionItem[];
  services: ServiceInfo[];
  tools: Record<string, ToolEntry>;
  busy: string | null;
  fresh: boolean;
  onClose: () => void;
  onStart: (picked: Record<string, Level>) => Promise<void>;
  onOwnApp: () => void;
  onTest: (item: ConnectionItem) => void;
  onToggle: (item: ConnectionItem, on: boolean) => void;
  onRemove: (item: ConnectionItem) => void;
  onSavedTool: (name: string, setting: Setting) => void;
  onSaved: () => void;
}) {
  const navigate = useNavigate();
  const oauth = option.auth === "oauth";
  const [adding, setAdding] = useState(false);
  const can = abilities(option);
  const working = items.some((i) => i.enabled && i.status === "connected");

  return (
    <aside
      className="side-panel w-full shrink-0 overflow-y-auto p-5 lg:sticky lg:top-0 lg:h-screen lg:w-[400px]"
      aria-label={`${option.display_name} setup`}
    >
      <div className="flex items-start gap-3">
        <KindMark kind={option.kind} />
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-xl font-semibold">{option.display_name}</h2>
          <div className="text-[12.5px] text-dim">{oauth ? "Sign in with one click" : "Add with a password or token"}</div>
        </div>
        <button type="button" onClick={onClose} className="icon-btn" aria-label="Close panel">
          <Icon name="x" size={18} />
        </button>
      </div>

      {fresh && working && (
        <div className="mt-4 flex flex-col gap-3 rounded-xl bg-ok-soft p-4 text-ok-text">
          <div className="flex items-center gap-3 font-medium">
            <svg className="check-draw" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12l4 4 10-10" />
            </svg>
            {option.display_name} is connected
          </div>
          <Button size="sm" icon="employees" onClick={() => navigate("/agents")}>
            Make an agent that uses this
          </Button>
        </div>
      )}

      <div className="mt-4 rounded-xl border border-line bg-panel p-4">
        <h3 className="font-display text-[15px] font-semibold">What agents can do</h3>
        <p className="mt-1 text-[13px] leading-normal text-muted">{option.description}</p>
        <ul className="mt-2 flex flex-col gap-1 text-[13px]">
          {can.map((label) => (
            <li key={label} className="flex items-start gap-2">
              <Icon name="check" size={13} strokeWidth={3} className="mt-1 shrink-0 text-accent-text" />
              {label}
            </li>
          ))}
        </ul>
      </div>

      {items.length > 0 && (
        <div className="mt-4 flex flex-col gap-2.5">
          {items.map((item) => (
            <ConnectedRow
              key={item.id}
              item={item}
              busy={busy === item.id}
              onTest={() => onTest(item)}
              onToggle={(on) => onToggle(item, on)}
              onRemove={() => onRemove(item)}
              onReconnect={oauth ? () => void onStart(heldLevels(services)).catch(() => undefined) : undefined}
            />
          ))}
        </div>
      )}

      {!option.allowed && (
        <div className="mt-4 flex items-start gap-2 text-[13px] text-ask-text">
          <Icon name="lock" size={14} className="mt-0.5 shrink-0" />
          {option.blocked_note ?? `${option.display_name} is not available on your plan.`}
        </div>
      )}

      {option.allowed && oauth && (
        <ShareChoices
          key={services.map((s) => `${s.id}${s.granted?.edit ? "e" : s.granted?.read ? "r" : ""}`).join()}
          option={option}
          services={services}
          busy={busy === option.kind}
          onStart={onStart}
          onOwnApp={onOwnApp}
        />
      )}

      {option.allowed && !oauth && (items.length === 0 || adding) && (
        <ManualForm
          option={option}
          onCancel={items.length > 0 ? () => setAdding(false) : undefined}
          onSaved={() => {
            setAdding(false);
            onSaved();
          }}
        />
      )}
      {option.allowed && !oauth && items.length > 0 && !adding && (
        <Button className="mt-4" size="sm" variant="ghost" icon="plus" onClick={() => setAdding(true)}>
          Add another
        </Button>
      )}

      {option.tools.some((name) => tools[name]) && (
        <ToolPermissions names={option.tools} tools={tools} open={items.length > 0} onSaved={onSavedTool} />
      )}
    </aside>
  );
}

/**
 * Read and edit levels, as two plain switches for each part of the app.
 * Levels are set when you sign in, so changing them signs you in again;
 * only what is switched on is asked of the provider.
 */
function ShareChoices({
  option,
  services,
  busy,
  onStart,
  onOwnApp,
}: {
  option: AvailableConnection;
  services: ServiceInfo[];
  busy: boolean;
  onStart: (picked: Record<string, Level>) => Promise<void>;
  onOwnApp: () => void;
}) {
  const [picked, setPicked] = useState<Record<string, Level>>(() => initialPicks(option.kind, services));
  const [error, setError] = useState<string | null>(null);
  const reconnecting = services.some((s) => s.granted);
  const chosen = Object.keys(picked).length;
  const changing = Object.values(picked).filter((l) => l === "edit").length;

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
    try {
      await onStart(picked);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the sign-in.");
    }
  }

  return (
    <div className="mt-5 flex flex-col gap-3" data-coach="share-step">
      <div>
        <h3 className="font-display text-[15px] font-semibold">What do you want to share?</h3>
        <p className="text-[13px] text-muted">Choose what your assistant and agents may do. You can change this any time.</p>
      </div>

      {services.length === 0 ? (
        <Spinner rows={3} />
      ) : (
        <ul className="flex flex-col gap-2.5">
          {services.map((s) => {
            const level = picked[s.id];
            const closed = !s.allowed.read;
            const words = SHARE_WORDS[s.id];
            return (
              <li key={s.id} className={`rounded-xl border px-3.5 py-3 ${level ? "border-accent-line bg-accent-soft/40" : "border-line"}`}>
                <div className="text-[14.5px] font-medium">{s.name}</div>
                <p className="text-[13px] text-muted">
                  {closed
                    ? (s.note ?? "Turned off for you by the platform.")
                    : level === "edit" && words?.edit
                      ? words.edit
                      : !level && words?.tip
                        ? words.tip
                        : (words?.read ?? "Look at it.")}
                </p>
                <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-2 text-[13px]">
                  <label className="flex items-center gap-2">
                    <Switch
                      checked={Boolean(level)}
                      disabled={closed}
                      label={`${s.name}: look`}
                      onChange={(on) => set(s.id, on ? "read" : null)}
                    />
                    Look
                  </label>
                  {s.can_edit && (
                    <label className="flex items-center gap-2">
                      <Switch
                        checked={level === "edit"}
                        disabled={closed || !s.allowed.edit}
                        label={`${s.name}: change`}
                        onChange={(on) => set(s.id, on ? "edit" : "read")}
                      />
                      Change
                    </label>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-[13px] text-muted" aria-live="polite">
        {chosen === 0
          ? "Switch on at least one to continue."
          : `Sharing ${chosen} ${chosen === 1 ? "part" : "parts"}${changing > 0 ? `, ${changing} that can make changes` : ", all look-only"}. ${option.display_name} will show you these before you agree.`}
      </p>
      <ErrorNote message={error} />
      <Button icon="link" disabled={busy || chosen === 0 || !option.configured} onClick={() => void go()}>
        {busy ? "Opening sign-in…" : reconnecting ? "Update and sign in again" : `Connect ${option.display_name}`}
      </Button>
      {!option.configured && (
        <button type="button" className="text-left text-[13px] text-accent-text hover:underline" onClick={onOwnApp}>
          {/* Not a dead end. Either the platform registers one app for
              everybody, or you do it for yourself, and nobody has to wait
              for the other. */}
          One-click sign-in isn't set up yet. Use your own {option.display_name} app →
        </button>
      )}
    </div>
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
          <h2 className="font-display text-[17px] font-semibold">Use your own {option.display_name} app</h2>
          <button type="button" className="icon-btn ml-auto h-9 w-9" aria-label="Close" onClick={onClose}>
            <Icon name="x" size={16} />
          </button>
        </div>

        <p className="text-[13px] leading-normal text-muted">
          Create an OAuth client in your own {option.kind === "google" ? "Google Cloud" : "Microsoft Entra"} project, then paste
          its ID and secret here. Your own app name appears on the sign-in screen, and nobody else has to set anything up first.
        </p>

        <div className="flex flex-col gap-1.5">
          <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">Add this as the redirect URI first</span>
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
          <span className="text-[13px] text-dim">It must match to the character, including http vs https.</span>
        </div>

        <Input label="Client ID" value={clientId} onChange={setClientId} required mono autoComplete="off" />
        <Input label="Client secret" type="password" value={secret} onChange={setSecret} required mono autoComplete="off" />
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
          The secret is encrypted and never shown again. If your consent screen is still in &ldquo;Testing&rdquo;, Google expires
          these connections after seven days. Set it to production once you are past trying it out.
        </p>
      </form>
    </Modal>
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
    <details className="group mt-5 rounded-xl border border-line bg-raised" open={open} data-coach="connection-permissions">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2.5 px-3.5 py-2.5 text-sm font-medium">
        <Icon name="lock" size={15} className="text-accent-text" />
        <span className="flex-1">When should it ask first?</span>
        <span className="text-xs font-normal text-dim">
          {allowed} always · {asking} ask
        </span>
        <Icon name="chevrons" size={14} className="text-dim" />
      </summary>
      <ul className="flex flex-col border-t border-line">
        {rows.map((tool) => (
          <li key={tool.name} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-3.5 py-3 last:border-0">
            <span className="flex min-w-[150px] flex-1 flex-col">
              <span className="text-sm font-medium">{toolLabel(tool.name)}</span>
              {/* Reading is the normal case, so only changes are labelled. */}
              {tool.side_effect !== "read" && (
                <span className={`text-xs ${tool.side_effect === "destructive" ? "text-bad-text" : "text-dim"}`}>
                  {effectLabel(tool.side_effect)}
                </span>
              )}
            </span>
            <PermissionChoice tool={tool} size="sm" onSaved={(setting) => onSaved(tool.name, setting)} />
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
      style={{ borderColor: broken(item) ? "var(--bad)" : "var(--line)" }}
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
        <Switch checked={item.enabled} onChange={onToggle} label={item.enabled ? `Pause ${item.label}` : `Resume ${item.label}`} />
      </div>
      {item.last_error && <ErrorNote message={item.last_error} />}
      <div className="flex flex-wrap gap-2">
        {broken(item) && onReconnect ? (
          <Button size="sm" onClick={onReconnect} icon="link">
            Reconnect
          </Button>
        ) : (
          <Button size="sm" variant="ghost" disabled={busy} onClick={onTest}>
            {busy ? "Checking…" : "Check it works"}
          </Button>
        )}
        {/* Disconnecting takes access away for good, so it takes a hold. */}
        <HoldButton variant="danger-ghost" className="btn-sm" onConfirm={onRemove}>
          Hold to disconnect
        </HoldButton>
      </div>
    </div>
  );
}

function ManualForm({
  option,
  onCancel,
  onSaved,
}: {
  option: AvailableConnection;
  onCancel?: () => void;
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
    <form onSubmit={save} className="mt-5 flex flex-col gap-3">
      <h3 className="font-display text-[15px] font-semibold">Connect {option.display_name}</h3>
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
      <ErrorNote message={error} />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!secret || saving}>
          {saving ? "Saving…" : "Save connection"}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <span className="text-[13px] text-dim">Encrypted, and never shown again. Use an app password or a read-only user.</span>
    </form>
  );
}

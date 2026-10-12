import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Icon, type IconName } from "../components/icons";
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
import { ApiError, api, type AvailableConnection, type ConnectionItem } from "../lib/api";
import { useAuth, useIsAdmin } from "../lib/auth";

/**
 * The outside apps AI Employees work in.
 *
 * Google and Microsoft connect with one click: the admin signs in with
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
};

const BRAND: Record<string, { mark: string; gradient: string }> = {
  google: { mark: "G", gradient: "linear-gradient(135deg,#4285F4,#34A853 55%,#FBBC05 80%,#EA4335)" },
  microsoft: { mark: "M", gradient: "linear-gradient(135deg,#F25022,#7FBA00 40%,#00A4EF 70%,#FFB900)" },
  email: { mark: "@", gradient: "linear-gradient(135deg,var(--accent),var(--spark))" },
  database: { mark: "DB", gradient: "linear-gradient(135deg,#336791,#5B8FC7)" },
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

export default function Connections() {
  const { org } = useAuth();
  const isAdmin = useIsAdmin();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [available, setAvailable] = useState<AvailableConnection[] | null>(null);
  const [connected, setConnected] = useState<ConnectionItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [manual, setManual] = useState<AvailableConnection | null>(null);

  async function load() {
    if (!org) return;
    const [options, items] = await Promise.all([
      api.get<AvailableConnection[]>(`/orgs/${org.id}/connections/available`),
      api.get<ConnectionItem[]>(`/orgs/${org.id}/connections`),
    ]);
    setAvailable(options);
    setConnected(items);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  // Coming back from Google or Microsoft: say what happened, once.
  useEffect(() => {
    const done = params.get("connected");
    const failed = params.get("error");
    if (!done && !failed) return;
    if (done) toast(`Connected ${params.get("account") ?? done}. Your AI Employees can use it now.`);
    if (failed) toast(failed, "bad");
    setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startOAuth(option: AvailableConnection) {
    if (!org) return;
    setBusy(option.kind);
    try {
      const { authorize_url } = await api.post<{ authorize_url: string }>(
        `/orgs/${org.id}/connections/oauth/${option.kind}/start`,
      );
      window.location.assign(authorize_url);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not start the sign-in.", "bad");
      setBusy(null);
    }
  }

  async function test(item: ConnectionItem) {
    if (!org) return;
    setBusy(item.id);
    try {
      const result = await api.post<ConnectionItem>(`/orgs/${org.id}/connections/${item.id}/test`);
      toast(result.status === "connected" ? `${item.label} works.` : `${item.label}: ${result.last_error ?? "test failed"}`, result.status === "connected" ? "ok" : "bad");
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function toggle(item: ConnectionItem, enabled: boolean) {
    if (!org) return;
    await api.patch(`/orgs/${org.id}/connections/${item.id}`, { enabled });
    toast(enabled ? `${item.label} resumed.` : `${item.label} paused. Tools that need it will say so.`, "info");
    await load();
  }

  async function remove(item: ConnectionItem) {
    if (!org) return;
    if (!window.confirm(`Disconnect ${item.label}? AI Employees will lose access to it straight away.`)) return;
    await api.del(`/orgs/${org.id}/connections/${item.id}`);
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
          Let AI Employees work in your email, calendar and files. Every send still follows your Permissions.
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
                    isAdmin={isAdmin}
                    busy={busy === item.id}
                    onTest={() => void test(item)}
                    onToggle={(on) => void toggle(item, on)}
                    onRemove={() => void remove(item)}
                    onReconnect={oauth ? () => void startOAuth(option) : undefined}
                  />
                ))}

                {isAdmin && (
                  <div className="mt-auto flex flex-wrap items-center gap-2">
                    {oauth ? (
                      <Button
                        size="sm"
                        variant={items.length ? "ghost" : "brand"}
                        icon="link"
                        disabled={!option.configured || busy === option.kind}
                        onClick={() => void startOAuth(option)}
                      >
                        {busy === option.kind ? "Opening sign-in…" : items.length ? "Connect another account" : `Connect ${option.display_name}`}
                      </Button>
                    ) : (
                      <Button size="sm" variant={items.length ? "ghost" : "brand"} icon="plus" onClick={() => setManual(option)}>
                        {items.length ? "Add another" : "Connect"}
                      </Button>
                    )}
                    {oauth && !option.configured && (
                      <span className="text-xs text-dim">Not set up on this platform yet. Ask your platform operator.</span>
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
            hint="Connect Google or Microsoft above, then give an AI Employee the matching tools on the AI Employees page."
          />
        )}

        {manual && <ManualForm option={manual} onClose={() => setManual(null)} onSaved={() => { setManual(null); void load(); }} />}
      </PageBody>
    </>
  );
}

function ConnectedRow({
  item,
  isAdmin,
  busy,
  onTest,
  onToggle,
  onRemove,
  onReconnect,
}: {
  item: ConnectionItem;
  isAdmin: boolean;
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
        {isAdmin && <Switch checked={item.enabled} onChange={onToggle} label={item.enabled ? `Pause ${item.label}` : `Resume ${item.label}`} />}
      </div>
      {item.last_error && <ErrorNote message={item.last_error} />}
      {isAdmin && (
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

function ManualForm({
  option,
  onClose,
  onSaved,
}: {
  option: AvailableConnection;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { org } = useAuth();
  const toast = useToast();
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setError(null);
    setSaving(true);
    const config: Record<string, string | number> = {};
    for (const field of option.fields) {
      const value = values[field.key]?.trim();
      if (!value) continue;
      config[field.key] = field.key.endsWith("port") ? Number(value) : value;
    }
    try {
      await api.post(`/orgs/${org.id}/connections`, {
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
    <form onSubmit={save} className="card rise flex flex-col gap-4 border-dashed border-line2 p-5">
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
  );
}

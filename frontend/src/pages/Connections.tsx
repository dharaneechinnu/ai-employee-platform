import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Icon, type IconName } from "../components/icons";
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
  type McpServer,
  type ToolEntry,
} from "../lib/api";
import { effectLabel, learnToolLabels, toolLabel } from "../lib/labels";
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
  const [tools, setTools] = useState<Record<string, ToolEntry>>({});
  const [servers, setServers] = useState<McpServer[]>([]);

  async function load() {
    if (!org) return;
    const [options, items, mcp] = await Promise.all([
      api.get<AvailableConnection[]>(`/orgs/${org.id}/connections/available`),
      api.get<ConnectionItem[]>(`/orgs/${org.id}/connections`),
      api.get<McpServer[]>(`/orgs/${org.id}/mcp-servers`).catch(() => [] as McpServer[]),
    ]);
    setAvailable(options);
    setConnected(items);
    setServers(mcp);
    const catalogue = await api.get<ToolEntry[]>(`/orgs/${org.id}/tools`).catch(() => [] as ToolEntry[]);
    learnToolLabels(catalogue);
    setTools(Object.fromEntries(catalogue.map((t) => [t.name, t])));
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
                    isAdmin={isAdmin}
                    busy={busy === item.id}
                    onTest={() => void test(item)}
                    onToggle={(on) => void toggle(item, on)}
                    onRemove={() => void remove(item)}
                    onReconnect={oauth ? () => void startOAuth(option) : undefined}
                  />
                ))}

                {org && option.tools.some((name) => tools[name]) && (
                  <ToolPermissions
                    orgId={org.id}
                    names={option.tools}
                    tools={tools}
                    isAdmin={isAdmin}
                    open={items.length > 0}
                    onSaved={(name, setting) =>
                      setTools((current) => ({ ...current, [name]: { ...current[name], effective_setting: setting } }))
                    }
                  />
                )}

                {isAdmin && (
                  <div className="mt-auto flex flex-wrap items-center gap-2">
                    {oauth ? (
                      <Button
                        size="sm"
                        variant={items.length ? "ghost" : "brand"}
                        icon="link"
                        disabled={!option.configured || !option.allowed || busy === option.kind}
                        onClick={() => void startOAuth(option)}
                      >
                        {busy === option.kind ? "Opening sign-in…" : items.length ? "Connect another account" : `Connect ${option.display_name}`}
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
                      <span className="text-xs text-dim">
                        {/* It is the platform operator who registers the
                            app, not anyone inside this company. The old
                            wording sent admins looking through their own
                            settings for a switch that was never there. */}
                        One-click sign-in isn't switched on for this platform yet. Ask whoever runs
                        AI Employees to register its {option.display_name} app — or use a method
                        below in the meantime.
                      </span>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </section>

        {connected.length === 0 && servers.length === 0 && (
          <Empty
            message="Nothing connected yet"
            hint="Connect Google or Microsoft above, then give an AI Employee the matching tools on the AI Employees page."
          />
        )}

        {org && (
          <McpSection
            orgId={org.id}
            servers={servers}
            tools={tools}
            isAdmin={isAdmin}
            onChanged={() => void load()}
            onSaved={(name, setting) =>
              setTools((current) => ({ ...current, [name]: { ...current[name], effective_setting: setting } }))
            }
          />
        )}

        {manual && <ManualForm option={manual} onClose={() => setManual(null)} onSaved={() => { setManual(null); void load(); }} />}
      </PageBody>
    </>
  );
}

/**
 * Each tool this app gives AI Employees, with its permission right
 * here: the place people connect an app is where they decide what may
 * be done with it.
 */
function ToolPermissions({
  orgId,
  names,
  tools,
  isAdmin,
  open,
  onSaved,
}: {
  orgId: string;
  names: string[];
  tools: Record<string, ToolEntry>;
  isAdmin: boolean;
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
        <span className="flex-1">What can AI Employees do here?</span>
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
            {isAdmin ? (
              <PermissionChoice
                orgId={orgId}
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

/**
 * MCP tool servers. MCP is the open standard many apps now ship: a
 * server that lists its own tools. Connect one by its address and
 * those tools join the built-in ones, under the same Permissions.
 */
function McpSection({
  orgId,
  servers,
  tools,
  isAdmin,
  onChanged,
  onSaved,
}: {
  orgId: string;
  servers: McpServer[];
  tools: Record<string, ToolEntry>;
  isAdmin: boolean;
  onChanged: () => void;
  onSaved: (name: string, setting: Setting) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function sync(server: McpServer) {
    setBusy(server.id);
    try {
      const fresh = await api.post<McpServer>(`/orgs/${orgId}/mcp-servers/${server.id}/sync`);
      if (fresh.status === "connected") toast(`${server.name}: ${fresh.tools.length} tools.`);
      else toast(fresh.last_error ?? `${server.name} did not answer.`, "bad");
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  async function remove(server: McpServer) {
    await api.del(`/orgs/${orgId}/mcp-servers/${server.id}`);
    toast(`${server.name} removed. Its tools are gone from every AI Employee.`, "info");
    onChanged();
  }

  return (
    <section className="flex flex-col gap-4" data-coach="mcp-servers">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-xl font-semibold">Tool servers (MCP)</h2>
          <p className="max-w-[640px] text-[13px] leading-snug text-muted">
            Many apps now offer an MCP server: a web address that lists the actions an AI can take there. Add one, and its
            tools appear for your AI Employees, with the same Always allow, Ask me first and Blocked choices.
          </p>
        </div>
        {isAdmin && !adding && (
          <Button size="sm" variant={servers.length ? "ghost" : "brand"} icon="plus" onClick={() => setAdding(true)}>
            Add a tool server
          </Button>
        )}
      </div>

      {adding && (
        <McpForm
          orgId={orgId}
          onClose={() => setAdding(false)}
          onSaved={(server) => {
            setAdding(false);
            toast(`${server.name} connected: ${server.tools.length} tools found.`);
            onChanged();
          }}
        />
      )}

      {servers.length > 0 && (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(380px,100%),1fr))]">
          {servers.map((server) => (
            <article key={server.id} className="card flex flex-col gap-4 p-5">
              <div className="flex items-start gap-3.5">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-[14px] border border-line2 bg-raised text-accent-text">
                  <Icon name="link" size={20} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-display text-lg font-semibold">{server.name}</h3>
                    <StatusChip status={server.status} />
                  </div>
                  <div className="truncate font-mono text-xs text-muted" title={server.url}>{server.url}</div>
                  <div className="text-xs text-dim">
                    {server.tools.length} tools
                    {server.token_last4 ? ` · token ••••${server.token_last4}` : " · no token"}
                    {server.last_synced_at ? ` · checked ${relativeTime(server.last_synced_at)}` : ""}
                  </div>
                </div>
              </div>

              <ErrorNote message={server.last_error} />

              <ToolPermissions
                orgId={orgId}
                names={server.tools.map((t) => t.name)}
                tools={tools}
                isAdmin={isAdmin}
                open
                onSaved={onSaved}
              />

              {isAdmin && (
                <div className="mt-auto flex gap-2">
                  <Button size="sm" variant="ghost" disabled={busy === server.id} onClick={() => void sync(server)}>
                    {busy === server.id ? "Checking…" : "Check for new tools"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void remove(server)}>
                    Remove
                  </Button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function McpForm({
  orgId,
  onClose,
  onSaved,
}: {
  orgId: string;
  onClose: () => void;
  onSaved: (server: McpServer) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      onSaved(await api.post<McpServer>(`/orgs/${orgId}/mcp-servers`, { name, url, token: token || null }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect to that server.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="card rise flex flex-col gap-4 border-dashed border-line2 p-5" data-coach="mcp-form">
      <div className="flex items-center gap-3">
        <h3 className="flex-1 font-display text-[17px] font-semibold">Add a tool server</h3>
        <button type="button" className="icon-btn h-10 w-10" aria-label="Close" onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))]">
        <Input label="Name" value={name} onChange={setName} required placeholder="CRM" />
        <Input label="MCP address" value={url} onChange={setUrl} required mono placeholder="https://mcp.example.com/mcp" />
        <Input label="Access token (if it needs one)" type="password" value={token} onChange={setToken} mono autoComplete="off" />
      </div>
      <ErrorNote message={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!name || !url || saving}>
          {saving ? "Connecting…" : "Connect and list tools"}
        </Button>
        <span className="text-[13px] text-dim">
          Tools that only read run on their own. Anything else asks first; tools the server marks as permanent start Blocked.
        </span>
      </div>
    </form>
  );
}

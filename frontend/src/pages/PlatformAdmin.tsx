import { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/icons";
import {
  Avatar,
  Button,
  Chip,
  Empty,
  ErrorNote,
  Input,
  SearchBox,
  Spinner,
  Tabs,
  ThemeToggle,
  relativeTime,
  statusTone,
  useToast,
} from "../components/ui";
import { ApiError, type Person } from "../lib/api";
import { AuthStage } from "./Login";

/**
 * The Platform Admin control room.
 *
 * Kept entirely separate from the customer app: a different token
 * type, its own sign-in, and no shared session. A Person Admin's
 * token is rejected here even though its holder is an admin of their
 * own person. It also looks different on purpose: the .staff class
 * turns the blue-violet accent jade, so staff always know where they are.
 *
 * Note what is absent. There is no way to read a customer's tasks,
 * memory, credentials or API keys, because no endpoint returns them.
 * This screen can only ever show counts and health.
 */

const BASE = "/api/v1/platform";

/** One line of the diary: who did what to which person, never content. */
interface AuditEntry {
  id: string;
  admin_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: string | null;
  created_at: string;
}

/** Whether a provider is connected. Never the key, not even masked. */
interface ProviderStatus {
  provider_key: string;
  connected: boolean;
  status: string;
  last_tested_at: string | null;
}

/** One one-click provider, as the control room sees it. */
interface OAuthApp {
  provider: string;
  display_name: string;
  client_id: string | null;
  secret_last4: string | null;
  enabled: boolean;
  configured: boolean;
  redirect_uri: string;
  docs_url: string;
  from_environment: boolean;
}

/** One connection, as it stands for one person. */
interface ConnectionAccess {
  kind: string;
  display_name: string;
  platform_ready: boolean;
  allowed: boolean;
  overridden: boolean;
  note: string | null;
}

interface PersonDetail extends Person {
  created_at: string;
  task_count: number;
  providers: ProviderStatus[];
}

let platformToken: string | null = null;

async function call<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: method ?? (body ? "POST" : "GET"),
    headers: {
      "Content-Type": "application/json",
      ...(platformToken ? { Authorization: `Bearer ${platformToken}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new ApiError(response.status, problem.detail ?? response.statusText);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export default function PlatformAdmin() {
  const [signedIn, setSignedIn] = useState(false);

  return (
    <div className="staff min-h-screen bg-bg text-ink">
      <div aria-hidden="true" className="h-1.5" style={{ background: "repeating-linear-gradient(-45deg,var(--accent) 0 14px,var(--bg) 14px 28px)", backgroundSize: "40px 40px" }} />
      {signedIn ? (
        <People
          onSignOut={() => {
            platformToken = null;
            setSignedIn(false);
          }}
        />
      ) : (
        <SignIn onSignedIn={() => setSignedIn(true)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- sign in

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = await call<{ access_token: string }>("/auth/login", { email, password });
      platformToken = body.access_token;
      onSignedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-6px)] flex-wrap">
      <AuthStage
        badge="STAFF ONLY"
        headline="Platform control room."
        ticker="Create, limit and suspend accounts. Counts and health only."
        points={[
          "Create accounts and send the setup link",
          "Set how many AI Employees each may run",
          "Suspend an account; customer data stays private",
        ]}
      />
      <section className="flex flex-[1_1_440px] items-center justify-center px-6 py-12">
        <div className="rise w-full max-w-[400px]">
          <form onSubmit={submit} className="flex flex-col gap-[18px]">
            <h2 className="font-display text-2xl font-semibold">Platform sign in</h2>
            <Input label="Email" type="email" value={email} onChange={setEmail} required autoComplete="username" />
            <Input label="Password" type="password" value={password} onChange={setPassword} required autoComplete="current-password" />
            <ErrorNote message={error} />
            <button type="submit" disabled={busy} className="btn btn-primary h-[50px] rounded-[14px] text-[15px]">
              {busy ? "Checking…" : "Enter control room"}
            </button>
            <p className="border-t border-line pt-3.5 text-[13px] leading-normal text-dim">
              This account can create and suspend every person. There is no second factor,
              so the password is the whole key — keep it in a password manager and never reuse it.
            </p>
          </form>
        </div>
      </section>
    </div>
  );
}

// ----------------------------------------------------------------- people

type Filter = "all" | "active" | "suspended";

function People({ onSignOut }: { onSignOut: () => void }) {
  const toast = useToast();
  const [people, setPeople] = useState<Person[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setupLink, setSetupLink] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [view, setView] = useState<"people" | "connections" | "audit">("people");
  const [apps, setApps] = useState<OAuthApp[] | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [access, setAccess] = useState<ConnectionAccess[] | null>(null);

  const [name, setName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [limit, setLimit] = useState("5");

  async function load() {
    setPeople(await call<Person[]>("/people"));
  }

  useEffect(() => {
    void load().catch(() => setError("Could not load people."));
  }, []);

  // The diary is fetched the first time it is opened, not on sign in:
  // most visits never look at it.
  useEffect(() => {
    if (view !== "connections") return;
    void call<OAuthApp[]>("/oauth-apps")
      .then(setApps)
      .catch(() => toast("Could not load the sign-in apps.", "bad"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  useEffect(() => {
    if (view !== "audit" || audit) return;
    void call<AuditEntry[]>("/audit")
      .then(setAudit)
      .catch(() => toast("Could not load the audit log.", "bad"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, audit]);

  /** Opens one person's counts. A second click closes it again. */
  async function openDetail(person: Person) {
    if (openId === person.id) {
      setOpenId(null);
      return;
    }
    setOpenId(person.id);
    setDetail(null);
    setAccess(null);
    try {
      setDetail(await call<PersonDetail>(`/people/${person.id}`));
      setAccess(await call<ConnectionAccess[]>(`/people/${person.id}/connections`));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not load that person.", "bad");
      setOpenId(null);
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("create");
    try {
      const created = await call<{ setup_token: string }>("/people", {
        name,
        first_admin_email: adminEmail,
        max_employees: Number(limit),
      });
      // Shown once. Only the hash is stored, so a lost link means a
      // new invite rather than a lookup.
      setSetupLink(`${window.location.origin}/login?token=${created.setup_token}`);
      toast(`${name} created.`);
      setName("");
      setAdminEmail("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create it.");
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(person: Person, action: "suspend" | "restore") {
    setBusy(person.id);
    try {
      await call(`/people/${person.id}/${action}`, {});
      setConfirming(null);
      toast(action === "suspend" ? `${(person.full_name || person.email)} suspended.` : `${(person.full_name || person.email)} restored.`, action === "suspend" ? "info" : "ok");
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function setLimitFor(person: Person, value: number) {
    const next = Math.max(person.employees_used, value);
    if (next === person.max_employees) return;
    // Optimistic: the stepper should feel instant; a failure reloads.
    setPeople((current) => current?.map((c) => (c.id === person.id ? { ...c, max_employees: next } : c)) ?? null);
    try {
      await call(`/people/${person.id}/limits`, { max_employees: next }, "PATCH");
      toast(`${(person.full_name || person.email)} limit set to ${next}.`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change the limit.", "bad");
      await load();
    }
  }

  const stats = useMemo(() => {
    const list = people ?? [];
    return {
      total: list.length,
      active: list.filter((c) => c.active).length,
      suspended: list.filter((c) => !c.active).length,
      used: list.reduce((n, c) => n + c.employees_used, 0),
      seats: list.reduce((n, c) => n + c.max_employees, 0),
    };
  }, [people]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (people ?? []).filter(
      (c) =>
        (filter === "all" || (filter === "active") === c.active) &&
        (!term ||
          c.email.toLowerCase().includes(term) ||
          (c.full_name ?? "").toLowerCase().includes(term)),
    );
  }, [people, filter, search]);

  async function copyLink() {
    if (!setupLink) return;
    try {
      await navigator.clipboard.writeText(setupLink);
      toast("Invite link copied.");
    } catch {
      toast("Copy failed. Select the link and copy it by hand.", "bad");
    }
  }

  return (
    <>
      <header className="border-b border-line bg-panel transition-colors duration-500">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-3.5 px-4 py-3 sm:px-6 lg:px-10">
          <span className="flex h-[34px] w-[34px] items-center justify-center rounded-[10px]" style={{ background: "linear-gradient(135deg,var(--accent),var(--accent2))", color: "var(--on-accent)" }} aria-hidden="true">
            <Icon name="shield" size={18} strokeWidth={2.2} />
          </span>
          <span className="font-display text-base font-semibold">Platform admin</span>
          <span className="rounded-full bg-accent-soft px-2.5 py-0.5 font-mono text-xs tracking-[0.12em] text-accent-text">STAFF</span>
          <span className="ml-auto" />
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      </header>

      <main className="mx-auto flex max-w-[1280px] flex-col gap-5 px-4 pb-16 pt-7 sm:px-6 lg:px-10" style={{ background: "var(--hero)" }}>
        <div className="rise flex flex-wrap items-center gap-4">
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.025em]">
            {view === "audit" ? "Audit log" : view === "connections" ? "One-click sign-in" : "People"}
          </h1>
          <Tabs
            label="View"
            value={view}
            onChange={setView}
            items={[
              { key: "people", label: "People" },
              { key: "connections", label: "One-click sign-in" },
              { key: "audit", label: "Audit log" },
            ]}
          />
          <span className="flex items-center gap-2 text-[13px] text-muted">
            <Icon name="lock" size={16} className="text-accent-text" />
            Counts and health only. Customer content is not readable here, by design.
          </span>
          {view === "people" && (
            <Button icon={creating ? "x" : "plus"} className="ml-auto" onClick={() => setCreating((v) => !v)} aria-expanded={creating}>
              {creating ? "Close" : "New account"}
            </Button>
          )}
        </div>

        {view === "audit" ? (
          <AuditLog entries={audit} />
        ) : view === "connections" ? (
          <OAuthApps apps={apps} onSaved={setApps} />
        ) : !people ? (
          error ? <ErrorNote message={error} /> : <Spinner />
        ) : (
          <>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr))]">
              <Stat label="People" value={stats.total} delay={0.04} />
              <Stat label="Active" value={stats.active} tone="text-ok-text" delay={0.08} />
              <Stat label="Suspended" value={stats.suspended} tone="text-bad-text" delay={0.12} />
              <Stat label="AI Employee seats used" value={stats.used} suffix={` / ${stats.seats}`} delay={0.16} />
            </div>

            {creating && (
              <form onSubmit={create} className="card rise flex flex-col gap-4 border-accent-line p-5">
                <h2 className="font-display text-lg font-semibold">New account</h2>
                <div className="grid items-end gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr))]">
                  <Input label="Person name" value={name} onChange={setName} required />
                  <Input label="Email" type="email" value={adminEmail} onChange={setAdminEmail} required />
                  <Input label="AI Employee limit" type="number" value={limit} onChange={setLimit} mono />
                  <Button type="submit" disabled={busy === "create"}>
                    {busy === "create" ? "Creating…" : "Create and get invite"}
                  </Button>
                </div>
                <ErrorNote message={error} />
                <p className="text-[13px] text-dim">The first admin's invite link is shown once, right after creation. Only its hash is stored.</p>
              </form>
            )}

            {setupLink && (
              <div role="status" className="card rise flex flex-col gap-2 border-accent-line bg-accent-soft p-4">
                <span className="text-xs text-accent-text">Send this to the first admin. It is shown only once.</span>
                <div className="flex items-center gap-2.5">
                  <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{setupLink}</code>
                  <Button size="sm" variant="ghost" onClick={() => void copyLink()}>
                    <Icon name="copy" size={15} />
                    Copy
                  </Button>
                  <button type="button" className="icon-btn h-9 w-9" aria-label="Dismiss" onClick={() => setSetupLink(null)}>
                    <Icon name="x" size={16} />
                  </button>
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2.5">
              <Tabs
                label="Status"
                value={filter}
                onChange={setFilter}
                items={[
                  { key: "all", label: "All", count: stats.total },
                  { key: "active", label: "Active", count: stats.active },
                  { key: "suspended", label: "Suspended", count: stats.suspended },
                ]}
              />
              <SearchBox value={search} onChange={setSearch} placeholder="Search by name or email" label="Search people" />
            </div>

            <section className="card rise overflow-hidden">
              <div className="overflow-x-auto">
                <div className="min-w-[940px]">
                  <div className="grid grid-cols-[minmax(240px,1.6fr)_120px_minmax(170px,1fr)_150px_220px] items-center gap-3 border-b border-line px-5 py-3 font-mono text-xs uppercase tracking-[0.1em] text-dim">
                    <span>Account</span>
                    <span>Status</span>
                    <span>AI Employees</span>
                    <span>Limit</span>
                    <span className="text-right">Actions</span>
                  </div>
                  {visible.length === 0 ? (
                    <div className="p-6">
                      <Empty message="No people match" hint="Try another filter or search term." />
                    </div>
                  ) : (
                    visible.map((person, i) => {
                      const active = person.active;
                      const pct = person.max_employees ? Math.round((person.employees_used / person.max_employees) * 100) : 0;
                      return (
                        <div
                          key={person.id}
                          className="slide-in grid grid-cols-[minmax(240px,1.6fr)_120px_minmax(170px,1fr)_150px_220px] items-center gap-3 border-b border-line px-5 py-3.5 text-sm transition-colors last:border-0 hover:bg-raised"
                          style={{ animationDelay: `${Math.min(i, 10) * 0.04}s` }}
                        >
                          <button
                            type="button"
                            onClick={() => void openDetail(person)}
                            aria-expanded={openId === person.id}
                            className="flex min-w-0 items-center gap-3 rounded-[10px] text-left transition-opacity hover:opacity-80"
                          >
                            <Avatar name={(person.full_name || person.email)} size={34} rounded="rounded-[10px]" muted={!active} />
                            <span className="flex min-w-0 flex-col">
                              <span className="truncate font-medium">{(person.full_name || person.email)}</span>
                              <span className="truncate font-mono text-xs text-dim">{person.email}</span>
                            </span>
                            <Icon
                              name="arrow"
                              size={15}
                              className={`shrink-0 text-dim transition-transform ${openId === person.id ? "rotate-90" : ""}`}
                            />
                          </button>
                          <span>
                            <Chip tone={statusTone((person.active ? "active" : "suspended"))}>{(person.active ? "active" : "suspended")}</Chip>
                          </span>
                          <span className="flex items-center gap-2.5">
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                              <span
                                className="grow-x block h-full rounded-full"
                                style={{ width: `${pct}%`, background: "linear-gradient(90deg,var(--accent),var(--accent2) 65%,var(--spark))", opacity: active ? 1 : 0.5 }}
                              />
                            </span>
                            <span className="font-mono text-[13px] text-muted">
                              {person.employees_used}/{person.max_employees}
                            </span>
                          </span>
                          <span className="inline-flex w-fit items-center overflow-hidden rounded-[10px] border border-line2">
                            <button
                              type="button"
                              aria-label={`Lower limit for ${(person.full_name || person.email)}`}
                              disabled={person.max_employees <= person.employees_used}
                              onClick={() => void setLimitFor(person, person.max_employees - 1)}
                              className="h-9 w-9 bg-sunken text-base font-semibold text-muted transition-colors hover:bg-raised hover:text-accent-text disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              −
                            </button>
                            <span className="min-w-[40px] text-center font-mono">{person.max_employees}</span>
                            <button
                              type="button"
                              aria-label={`Raise limit for ${(person.full_name || person.email)}`}
                              onClick={() => void setLimitFor(person, person.max_employees + 1)}
                              className="h-9 w-9 bg-sunken text-base font-semibold text-muted transition-colors hover:bg-raised hover:text-accent-text"
                            >
                              +
                            </button>
                          </span>
                          <span className="flex justify-end">
                            {active ? (
                              <Button size="sm" variant="danger-ghost" onClick={() => setConfirming(person.id)}>
                                Suspend
                              </Button>
                            ) : (person.active ? "active" : "suspended") === "suspended" ? (
                              <Button size="sm" variant="ok" disabled={busy === person.id} onClick={() => void setStatus(person, "restore")}>
                                Restore
                              </Button>
                            ) : null}
                          </span>
                          {confirming === person.id && (
                            <div role="alertdialog" aria-label={`Confirm suspending ${(person.full_name || person.email)}`} className="rise col-span-full flex flex-wrap items-center gap-3 rounded-xl bg-bad-soft px-3.5 py-3">
                              <Icon name="warn" size={20} className="text-bad-text" />
                              <span className="min-w-[240px] flex-1">
                                Suspend <b>{person.full_name || person.email}</b>? They cannot sign
                                in, and their {person.employees_used} AI Employees stop running.
                                Nothing of theirs is read or deleted, and you can restore the
                                account later.
                              </span>
                              <Button size="sm" variant="danger" disabled={busy === person.id} onClick={() => void setStatus(person, "suspend")}>
                                Suspend now
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                                Keep active
                              </Button>
                            </div>
                          )}
                          {openId === person.id && (
                            <div className="rise col-span-full">
                              <PersonPanel
                                detail={detail}
                                access={access}
                                onAccess={setAccess}
                                />
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </section>
          </>
        )}
      </main>
    </>
  );
}

function Stat({
  label,
  value,
  suffix,
  tone = "",
  delay,
}: {
  label: string;
  value: number;
  suffix?: string;
  tone?: string;
  delay: number;
}) {
  return (
    <div className="card lift rise p-[18px]" style={{ animationDelay: `${delay}s` }}>
      <div className="text-[13px] text-dim">{label}</div>
      <div className={`font-display text-[34px] font-semibold ${tone}`}>
        <span className="pop inline-block" style={{ animationDelay: `${delay + 0.2}s` }}>
          {value}
        </span>
        {suffix && <span className="text-lg text-dim">{suffix}</span>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------ detail panel

/**
 * Everything a Platform Admin may see about one person: how many, and
 * how healthy. There is no tab here for tasks, memory or keys, because
 * there is no endpoint that would fill one.
 */
function PersonPanel({
  detail,
  access,
  onAccess,
}: {
  detail: PersonDetail | null;
  access: ConnectionAccess[] | null;
  onAccess: (rows: ConnectionAccess[]) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function setAllowed(row: ConnectionAccess, allowed: boolean | null) {
    setBusy(row.kind);
    try {
      onAccess(
        await call<ConnectionAccess[]>(
          `/people/${"me"}/connections/${row.kind}`,
          {
            allowed,
            note:
              allowed === false
                ? `${row.display_name} is not available on your plan.`
                : null,
          },
          "PUT",
        ),
      );
      toast(
        allowed === null
          ? `${row.display_name} follows the platform default again.`
          : allowed
            ? `${row.display_name} opened for this person.`
            : `${row.display_name} closed for this person.`,
        allowed === false ? "info" : "ok",
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  if (!detail) return <Spinner rows={1} />;

  return (
    <div className="flex flex-col gap-4 rounded-xl bg-sunken p-4">
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(140px,100%),1fr))]">
        <Fact label="AI Employees" value={`${detail.employees_used} / ${detail.max_employees}`} />
        <Fact label="Tasks ever run" value={String(detail.task_count)} />
        <Fact label="Customer since" value={new Date(detail.created_at).toLocaleDateString()} />
      </div>

      <div className="flex flex-col gap-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">AI providers</span>
        {detail.providers.length === 0 ? (
          <span className="text-[13px] text-muted">None connected. Their AI Employees cannot run yet.</span>
        ) : (
          <div className="flex flex-wrap gap-2">
            {detail.providers.map((provider) => (
              <Chip key={provider.provider_key} tone={statusTone(provider.status)}>
                {provider.provider_key}
                {provider.last_tested_at ? ` \u00b7 tested ${relativeTime(provider.last_tested_at)}` : ""}
              </Chip>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 border-t border-line pt-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
          Connections this person may use
        </span>
        {!access ? (
          <Spinner rows={1} />
        ) : (
          <div className="flex flex-col gap-1.5">
            {access.map((row) => (
              <div key={row.kind} className="flex flex-wrap items-center gap-2.5 text-[13px]">
                <span className="min-w-[150px] font-medium">{row.display_name}</span>

                {!row.platform_ready && (
                  <Chip tone="mute" dot={false}>
                    not set up on the platform
                  </Chip>
                )}

                <Chip tone={row.allowed ? "ok" : "bad"}>{row.allowed ? "open" : "closed"}</Chip>

                {/* Three states, not two. "Follows the default" is
                    different from "explicitly opened", and an operator
                    who cannot get back to it ends up with rulings they
                    never meant to make permanent. */}
                {row.overridden ? (
                  <span className="text-xs text-dim">set for this person</span>
                ) : (
                  <span className="text-xs text-dim">follows the platform default</span>
                )}

                <span className="ml-auto flex gap-1.5">
                  <Button
                    size="sm"
                    variant={row.allowed ? "ghost" : "ok"}
                    disabled={busy === row.kind || (row.allowed && !row.overridden)}
                    onClick={() => void setAllowed(row, true)}
                  >
                    Open
                  </Button>
                  <Button
                    size="sm"
                    variant="danger-ghost"
                    disabled={busy === row.kind || !row.allowed}
                    onClick={() => void setAllowed(row, false)}
                  >
                    Close
                  </Button>
                  {row.overridden && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === row.kind}
                      onClick={() => void setAllowed(row, null)}
                    >
                      Use default
                    </Button>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <p className="flex items-center gap-2 border-t border-line pt-3 text-[13px] text-dim">
        <Icon name="lock" size={14} className="text-accent-text" />
        Counts, health and settings only. Their tasks, memory and API keys are not readable from
        here.
      </p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[13px] text-dim">{label}</div>
      <div className="font-mono text-[17px]">{value}</div>
    </div>
  );
}

// --------------------------------------------------------------- audit log

/**
 * The diary. Append-only in the database, so a Platform Admin cannot
 * delete the record of their own actions - which is the only reason an
 * audit log is worth having.
 */
function AuditLog({ entries }: { entries: AuditEntry[] | null }) {
  if (!entries) return <Spinner />;
  if (entries.length === 0) {
    return <Empty message="Nothing recorded yet" hint="Every sign in, person created, limit changed and suspension lands here." />;
  }

  return (
    <section className="card rise overflow-hidden">
      <div className="overflow-x-auto">
        <div className="min-w-[760px]">
          <div className="grid grid-cols-[170px_minmax(200px,1fr)_180px_minmax(200px,1.2fr)] items-center gap-3 border-b border-line px-5 py-3 font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
            <span>When</span>
            <span>Who</span>
            <span>Did what</span>
            <span>To what</span>
          </div>
          {entries.map((entry, i) => (
            <div
              key={entry.id}
              className="slide-in grid grid-cols-[170px_minmax(200px,1fr)_180px_minmax(200px,1.2fr)] items-center gap-3 border-b border-line px-5 py-3 text-sm last:border-0 hover:bg-raised"
              style={{ animationDelay: `${Math.min(i, 12) * 0.03}s` }}
            >
              <span className="font-mono text-[13px] text-muted" title={new Date(entry.created_at).toLocaleString()}>
                {relativeTime(entry.created_at)}
              </span>
              <span className="truncate">{entry.admin_email ?? "\u2014"}</span>
              <span>
                <Chip tone={entry.action.includes("suspend") ? "bad" : "mute"} dot={false}>
                  {entry.action.replace(/_/g, " ")}
                </Chip>
              </span>
              <span className="truncate text-muted" title={entry.detail ?? undefined}>
                {entry.detail ?? entry.target_id ?? "\u2014"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ----------------------------------------------------- one-click sign-in

/**
 * Where the Google and Microsoft apps are registered.
 *
 * Both issue one app per *application*, not per customer, so this is
 * a platform setting: every person signs in through the same app and
 * grants it access to their own mailbox. Until it is set here, the
 * one-click buttons on every person's Connections page are disabled —
 * and before this screen existed, the only way to set it was an
 * environment variable and a redeploy, which no Platform Admin can do.
 */
function OAuthApps({
  apps,
  onSaved,
}: {
  apps: OAuthApp[] | null;
  onSaved: (apps: OAuthApp[]) => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!apps) return <Spinner />;

  async function reload() {
    onSaved(await call<OAuthApp[]>("/oauth-apps"));
  }

  function open(app: OAuthApp) {
    setEditing(app.provider);
    setClientId(app.client_id ?? "");
    setSecret("");
    setError(null);
  }

  async function save(e: React.FormEvent, app: OAuthApp) {
    e.preventDefault();
    setError(null);
    setBusy(app.provider);
    try {
      await call(`/oauth-apps/${app.provider}`, { client_id: clientId, client_secret: secret }, "PUT");
      setEditing(null);
      setSecret("");
      toast(`${app.display_name} sign-in is on. Every person can connect it now.`);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    } finally {
      setBusy(null);
    }
  }

  async function toggle(app: OAuthApp) {
    setBusy(app.provider);
    try {
      await call(`/oauth-apps/${app.provider}`, { enabled: !app.enabled }, "PATCH");
      toast(
        app.enabled
          ? `${app.display_name} paused. People already connected keep working.`
          : `${app.display_name} is on again.`,
        app.enabled ? "info" : "ok",
      );
      await reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function remove(app: OAuthApp) {
    setBusy(app.provider);
    try {
      await call(`/oauth-apps/${app.provider}`, undefined, "DELETE");
      toast(`${app.display_name} removed.`, "info");
      await reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not remove that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied.");
    } catch {
      toast("Copy failed. Select the address and copy it by hand.", "bad");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2.5 text-[13px] leading-normal text-muted">
        <Icon name="info" size={16} className="mt-0.5 shrink-0 text-accent-text" />
        <span>
          One app per provider covers the whole platform. Each person then signs in with their own
          account and grants it access to their own mailbox — you never see their mail, only that
          they connected.
        </span>
      </p>

      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))]">
        {apps.map((app, i) => (
          <article key={app.provider} className="card rise flex flex-col gap-4 p-5" style={{ animationDelay: `${i * 0.06}s` }}>
            <div className="flex items-center gap-3.5">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] border border-line2 bg-raised font-display text-lg font-bold text-accent-text">
                {app.display_name.charAt(0)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-display text-lg font-semibold">{app.display_name}</div>
                <div className="font-mono text-[13px] text-muted">
                  {app.client_id ? `${app.client_id.slice(0, 22)}…` : "not registered"}
                </div>
              </div>
              <Chip tone={app.configured ? "ok" : "mute"}>{app.configured ? "on" : "off"}</Chip>
            </div>

            {!app.configured && (
              <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px] leading-normal">
                <Icon name="warn" className="shrink-0 text-ask-text" />
                <span>
                  The <b>Connect {app.display_name}</b> button is greyed out on every person's
                  Connections page until this is set.
                </span>
              </div>
            )}

            {app.from_environment && (
              <div className="flex gap-2.5 rounded-xl bg-raised px-3.5 py-3 text-[13px] leading-normal text-muted">
                <Icon name="terminal" className="shrink-0" />
                <span>
                  Currently coming from this server's environment variables. Saving here replaces
                  that and can be changed again without a redeploy.
                </span>
              </div>
            )}

            {/* The single most common reason a one-click sign-in fails
                is a redirect address that does not match to the
                character, so it is shown rather than documented. */}
            <div className="flex flex-col gap-1.5">
              <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
                Paste this as the redirect URI
              </span>
              <div className="flex items-center gap-2 rounded-xl border border-line bg-sunken px-3 py-2">
                <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{app.redirect_uri}</code>
                <Button size="sm" variant="ghost" onClick={() => void copy(app.redirect_uri)}>
                  <Icon name="copy" size={15} />
                  Copy
                </Button>
              </div>
              <span className="text-[13px] text-dim">
                It must match to the character, including http vs https.
              </span>
            </div>

            {editing === app.provider ? (
              <form onSubmit={(e) => void save(e, app)} className="flex flex-col gap-3">
                <Input label="Client ID" value={clientId} onChange={setClientId} required mono autoComplete="off" />
                <Input
                  label="Client secret"
                  type="password"
                  value={secret}
                  onChange={setSecret}
                  required
                  mono
                  autoComplete="off"
                  placeholder={app.secret_last4 ? `replaces ••••${app.secret_last4}` : "Paste secret"}
                />
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={!clientId || !secret || busy === app.provider}>
                    {busy === app.provider ? "Saving…" : "Save and switch on"}
                  </Button>
                  <Button variant="ghost" onClick={() => setEditing(null)}>
                    Cancel
                  </Button>
                </div>
                <ErrorNote message={error} />
                <p className="text-[13px] text-dim">
                  The secret is encrypted and never shown again, to you or anyone else. Only its last
                  four characters come back.
                </p>
              </form>
            ) : (
              <div className="mt-auto flex flex-wrap items-center gap-2">
                <Button size="sm" variant={app.configured ? "ghost" : "brand"} onClick={() => open(app)}>
                  {app.client_id ? "Replace credentials" : "Register app"}
                </Button>
                {app.client_id && !app.from_environment && (
                  <>
                    <Button size="sm" variant="ghost" disabled={busy === app.provider} onClick={() => void toggle(app)}>
                      {app.enabled ? "Pause" : "Switch on"}
                    </Button>
                    <Button size="sm" variant="danger-ghost" disabled={busy === app.provider} onClick={() => void remove(app)}>
                      Remove
                    </Button>
                  </>
                )}
                <a
                  href={app.docs_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto text-[13px] text-accent-text hover:underline"
                >
                  Where do I get these?
                </a>
              </div>
            )}

            {app.secret_last4 && editing !== app.provider && (
              <div className="font-mono text-[13px] text-dim">secret ••••••••{app.secret_last4}</div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

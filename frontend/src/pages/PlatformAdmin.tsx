import { useEffect, useMemo, useRef, useState } from "react";
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
  statusTone,
  useToast,
} from "../components/ui";
import { ApiError, type Company } from "../lib/api";
import { AuthStage } from "./Login";

/**
 * The Platform Admin control room.
 *
 * Kept entirely separate from the customer app: a different token
 * type, its own sign-in, and no shared session. A Company Admin's
 * token is rejected here even though its holder is an admin of their
 * own company. It also looks different on purpose: the .staff class
 * turns the blue-violet accent jade, so staff always know where they are.
 *
 * Note what is absent. There is no way to read a customer's tasks,
 * memory, credentials or API keys, because no endpoint returns them.
 * This screen can only ever show counts and health.
 */

const BASE = "/api/v1/platform";

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
        <Companies
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

function CodeInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length: 6 }, (_, i) => value[i] ?? "");

  function setAt(index: number, raw: string) {
    const clean = raw.replace(/\D/g, "");
    if (clean.length > 1) {
      // A pasted or autofilled code fills every box at once.
      const next = clean.slice(0, 6);
      onChange(next);
      refs.current[Math.min(next.length, 5)]?.focus();
      return;
    }
    const next = (value.slice(0, index) + clean + value.slice(index + 1)).slice(0, 6);
    onChange(next);
    if (clean && index < 5) refs.current[index + 1]?.focus();
  }

  return (
    <div className="grid grid-cols-6 gap-2">
      {digits.map((digit, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          value={digit}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          aria-label={`Digit ${i + 1}`}
          maxLength={6}
          onChange={(e) => setAt(i, e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Backspace" && !digit && i > 0) refs.current[i - 1]?.focus();
          }}
          className={`field h-14 min-w-0 px-0 text-center font-mono text-[22px] font-semibold ${digit ? "border-accent-line bg-accent-soft" : ""}`}
        />
      ))}
    </div>
  );
}

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = await call<{ access_token: string }>("/auth/login", { email, password, totp_code: code });
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
        ticker="Create, limit and suspend companies. Counts and health only."
        orbit={[
          { label: "Companies", tone: "var(--accent)", live: true },
          { label: "Limits", tone: "var(--ok)" },
          { label: "Suspensions", tone: "var(--bad)" },
        ]}
      />
      <section className="flex flex-[1_1_440px] items-center justify-center px-6 py-12">
        <div className="halo rise w-full max-w-[420px] rounded-3xl p-[1.5px]" style={{ boxShadow: "0 40px 120px -50px var(--glow)", animationDelay: ".15s" }}>
          <form onSubmit={submit} className="flex flex-col gap-[18px] rounded-[23px] bg-panel p-8 transition-colors duration-500">
            <h2 className="font-display text-2xl font-semibold">Platform sign in</h2>
            <Input label="Email" type="email" value={email} onChange={setEmail} required autoComplete="username" />
            <Input label="Password" type="password" value={password} onChange={setPassword} required autoComplete="current-password" />
            <fieldset>
              <legend className="label mb-2">Authenticator code</legend>
              <CodeInput value={code} onChange={setCode} />
              <p className="mt-2 text-xs text-dim">Paste the whole code into any box; it fills them all.</p>
            </fieldset>
            <ErrorNote message={error} />
            <button type="submit" disabled={busy || code.length !== 6} className="btn btn-primary h-[50px] rounded-[14px] text-[15px]">
              {busy ? "Checking…" : "Enter control room"}
            </button>
            <p className="border-t border-line pt-3.5 text-[13px] leading-normal text-dim">
              Two-factor is required. This account can create and suspend every company, so a password alone is not enough.
            </p>
          </form>
        </div>
      </section>
    </div>
  );
}

// -------------------------------------------------------------- companies

type Filter = "all" | "active" | "suspended";

function Companies({ onSignOut }: { onSignOut: () => void }) {
  const toast = useToast();
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [limit, setLimit] = useState("5");

  async function load() {
    setCompanies(await call<Company[]>("/companies"));
  }

  useEffect(() => {
    void load().catch(() => setError("Could not load companies."));
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("create");
    try {
      const created = await call<{ invite_token: string }>("/companies", {
        name,
        slug,
        first_admin_email: adminEmail,
        max_employees: Number(limit),
      });
      // Shown once. Only the hash is stored, so a lost link means a
      // new invite rather than a lookup.
      setInviteLink(`${window.location.origin}/login?token=${created.invite_token}`);
      toast(`${name} created.`);
      setName("");
      setSlug("");
      setAdminEmail("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create it.");
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(company: Company, action: "suspend" | "reactivate") {
    setBusy(company.id);
    try {
      await call(`/companies/${company.id}/${action}`, {});
      setConfirming(null);
      toast(action === "suspend" ? `${company.name} suspended.` : `${company.name} reactivated.`, action === "suspend" ? "info" : "ok");
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function setLimitFor(company: Company, value: number) {
    const next = Math.max(company.employees_used, value);
    if (next === company.max_employees) return;
    // Optimistic: the stepper should feel instant; a failure reloads.
    setCompanies((current) => current?.map((c) => (c.id === company.id ? { ...c, max_employees: next } : c)) ?? null);
    try {
      await call(`/companies/${company.id}/limits`, { max_employees: next }, "PATCH");
      toast(`${company.name} limit set to ${next}.`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change the limit.", "bad");
      await load();
    }
  }

  const stats = useMemo(() => {
    const list = companies ?? [];
    return {
      total: list.length,
      active: list.filter((c) => c.status === "active").length,
      suspended: list.filter((c) => c.status === "suspended").length,
      used: list.reduce((n, c) => n + c.employees_used, 0),
      seats: list.reduce((n, c) => n + c.max_employees, 0),
    };
  }, [companies]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (companies ?? []).filter(
      (c) =>
        (filter === "all" || c.status === filter) &&
        (!term || c.name.toLowerCase().includes(term) || c.slug.toLowerCase().includes(term)),
    );
  }, [companies, filter, search]);

  async function copyLink() {
    if (!inviteLink) return;
    try {
      await navigator.clipboard.writeText(inviteLink);
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
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.025em]">Companies</h1>
          <span className="flex items-center gap-2 text-[13px] text-muted">
            <Icon name="lock" size={16} className="text-accent-text" />
            Counts and health only. Customer content is not readable here, by design.
          </span>
          <Button icon={creating ? "x" : "plus"} className="ml-auto" onClick={() => setCreating((v) => !v)} aria-expanded={creating}>
            {creating ? "Close" : "New company"}
          </Button>
        </div>

        {!companies ? (
          error ? <ErrorNote message={error} /> : <Spinner />
        ) : (
          <>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr))]">
              <Stat label="Companies" value={stats.total} delay={0.04} />
              <Stat label="Active" value={stats.active} tone="text-ok-text" delay={0.08} />
              <Stat label="Suspended" value={stats.suspended} tone="text-bad-text" delay={0.12} />
              <Stat label="AI Employee seats used" value={stats.used} suffix={` / ${stats.seats}`} delay={0.16} />
            </div>

            {creating && (
              <form onSubmit={create} className="card rise flex flex-col gap-4 border-accent-line p-5">
                <h2 className="font-display text-lg font-semibold">New company</h2>
                <div className="grid items-end gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr))]">
                  <Input label="Company name" value={name} onChange={setName} required />
                  <Input label="Slug" value={slug} onChange={setSlug} placeholder="acme" required mono />
                  <Input label="First admin email" type="email" value={adminEmail} onChange={setAdminEmail} required />
                  <Input label="AI Employee limit" type="number" value={limit} onChange={setLimit} mono />
                  <Button type="submit" disabled={busy === "create"}>
                    {busy === "create" ? "Creating…" : "Create and get invite"}
                  </Button>
                </div>
                <ErrorNote message={error} />
                <p className="text-[13px] text-dim">The first admin's invite link is shown once, right after creation. Only its hash is stored.</p>
              </form>
            )}

            {inviteLink && (
              <div role="status" className="card rise flex flex-col gap-2 border-accent-line bg-accent-soft p-4">
                <span className="text-xs text-accent-text">Send this to the first admin. It is shown only once.</span>
                <div className="flex items-center gap-2.5">
                  <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{inviteLink}</code>
                  <Button size="sm" variant="ghost" onClick={() => void copyLink()}>
                    <Icon name="copy" size={15} />
                    Copy
                  </Button>
                  <button type="button" className="icon-btn h-9 w-9" aria-label="Dismiss" onClick={() => setInviteLink(null)}>
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
              <SearchBox value={search} onChange={setSearch} placeholder="Search by name or slug" label="Search companies" />
            </div>

            <section className="card rise overflow-hidden">
              <div className="overflow-x-auto">
                <div className="min-w-[940px]">
                  <div className="grid grid-cols-[minmax(220px,1.4fr)_120px_90px_minmax(170px,1fr)_150px_220px] items-center gap-3 border-b border-line px-5 py-3 font-mono text-xs uppercase tracking-[0.1em] text-dim">
                    <span>Company</span>
                    <span>Status</span>
                    <span>Members</span>
                    <span>AI Employees</span>
                    <span>Limit</span>
                    <span className="text-right">Actions</span>
                  </div>
                  {visible.length === 0 ? (
                    <div className="p-6">
                      <Empty message="No companies match" hint="Try another filter or search term." />
                    </div>
                  ) : (
                    visible.map((company, i) => {
                      const active = company.status === "active";
                      const pct = company.max_employees ? Math.round((company.employees_used / company.max_employees) * 100) : 0;
                      return (
                        <div
                          key={company.id}
                          className="slide-in grid grid-cols-[minmax(220px,1.4fr)_120px_90px_minmax(170px,1fr)_150px_220px] items-center gap-3 border-b border-line px-5 py-3.5 text-sm transition-colors last:border-0 hover:bg-raised"
                          style={{ animationDelay: `${Math.min(i, 10) * 0.04}s` }}
                        >
                          <span className="flex min-w-0 items-center gap-3">
                            <Avatar name={company.name} size={34} rounded="rounded-[10px]" muted={!active} />
                            <span className="flex min-w-0 flex-col">
                              <span className="truncate font-medium">{company.name}</span>
                              <span className="truncate font-mono text-xs text-dim">{company.slug}</span>
                            </span>
                          </span>
                          <span>
                            <Chip tone={statusTone(company.status)}>{company.status}</Chip>
                          </span>
                          <span className="font-mono">{company.member_count}</span>
                          <span className="flex items-center gap-2.5">
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                              <span
                                className="grow-x block h-full rounded-full"
                                style={{ width: `${pct}%`, background: "linear-gradient(90deg,var(--accent),var(--accent2) 65%,var(--spark))", opacity: active ? 1 : 0.5 }}
                              />
                            </span>
                            <span className="font-mono text-[13px] text-muted">
                              {company.employees_used}/{company.max_employees}
                            </span>
                          </span>
                          <span className="inline-flex w-fit items-center overflow-hidden rounded-[10px] border border-line2">
                            <button
                              type="button"
                              aria-label={`Lower limit for ${company.name}`}
                              disabled={company.max_employees <= company.employees_used}
                              onClick={() => void setLimitFor(company, company.max_employees - 1)}
                              className="h-9 w-9 bg-sunken text-base font-semibold text-muted transition-colors hover:bg-raised hover:text-accent-text disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              −
                            </button>
                            <span className="min-w-[40px] text-center font-mono">{company.max_employees}</span>
                            <button
                              type="button"
                              aria-label={`Raise limit for ${company.name}`}
                              onClick={() => void setLimitFor(company, company.max_employees + 1)}
                              className="h-9 w-9 bg-sunken text-base font-semibold text-muted transition-colors hover:bg-raised hover:text-accent-text"
                            >
                              +
                            </button>
                          </span>
                          <span className="flex justify-end">
                            {active ? (
                              <Button size="sm" variant="danger-ghost" onClick={() => setConfirming(company.id)}>
                                Suspend
                              </Button>
                            ) : company.status === "suspended" ? (
                              <Button size="sm" variant="ok" disabled={busy === company.id} onClick={() => void setStatus(company, "reactivate")}>
                                Reactivate
                              </Button>
                            ) : null}
                          </span>
                          {confirming === company.id && (
                            <div role="alertdialog" aria-label={`Confirm suspending ${company.name}`} className="rise col-span-full flex flex-wrap items-center gap-3 rounded-xl bg-bad-soft px-3.5 py-3">
                              <Icon name="warn" size={20} className="text-bad-text" />
                              <span className="min-w-[240px] flex-1">
                                Suspend <b>{company.name}</b>? Its {company.member_count} members lose access and its{" "}
                                {company.employees_used} AI Employees can no longer run. You can reactivate later.
                              </span>
                              <Button size="sm" variant="danger" disabled={busy === company.id} onClick={() => void setStatus(company, "suspend")}>
                                Suspend now
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                                Keep active
                              </Button>
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

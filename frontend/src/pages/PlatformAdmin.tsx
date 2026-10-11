import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Spinner, statusTone } from "../components/ui";
import { ApiError, type Company } from "../lib/api";

/**
 * The Platform Admin control room.
 *
 * Kept entirely separate from the customer app: a different token
 * type, its own sign-in, and no shared session. A Company Admin's
 * token is rejected here even though its holder is an admin of their
 * own company.
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

  return signedIn ? <Companies onSignOut={() => setSignedIn(false)} /> : (
    <SignIn onSignedIn={() => setSignedIn(true)} />
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
      const body = await call<{ access_token: string }>("/auth/login", {
        email,
        password,
        totp_code: code,
      });
      platformToken = body.access_token;
      onSignedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-sm border-amber-900">
        <div className="mb-4 flex items-center gap-2">
          <h1 className="text-lg">Platform Admin</h1>
          <Badge tone="amber">staff</Badge>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <Input label="Email" type="email" value={email} onChange={setEmail} required />
          <Input
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            required
          />
          <Input
            label="Authenticator code"
            value={code}
            onChange={setCode}
            placeholder="6 digits"
            required
          />

          <ErrorNote message={error} />

          <Button type="submit" disabled={busy}>
            {busy ? "Checking…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-4 text-xs text-neutral-600">
          Two-factor is required. This account can create and suspend every company, so a
          password alone is not enough.
        </p>
      </Card>
    </div>
  );
}

function Companies({ onSignOut }: { onSignOut: () => void }) {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);

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
      setName("");
      setSlug("");
      setAdminEmail("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create it.");
    }
  }

  async function setStatus(id: string, action: "suspend" | "reactivate" | "close") {
    await call(`/companies/${id}/${action}`, {});
    await load();
  }

  async function setLimitFor(id: string, value: string) {
    await call(`/companies/${id}/limits`, { max_employees: Number(value) }, "PATCH");
    await load();
  }

  if (!companies) return <Spinner />;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <h1 className="text-lg">Companies</h1>
        <Badge tone="amber">platform admin</Badge>
        <div className="ml-auto">
          <Button variant="ghost" onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      </div>

      <p className="text-xs text-neutral-500">
        Counts and health only. Customer tasks, memory and credentials are not readable from
        here, by design.
      </p>

      <Card>
        <form onSubmit={create} className="grid gap-3 sm:grid-cols-4">
          <Input label="Company name" value={name} onChange={setName} required />
          <Input label="Slug" value={slug} onChange={setSlug} placeholder="acme" required />
          <Input
            label="First admin email"
            type="email"
            value={adminEmail}
            onChange={setAdminEmail}
            required
          />
          <Input label="AI Employee limit" value={limit} onChange={setLimit} />
          <div className="sm:col-span-4">
            <Button type="submit">Create company</Button>
          </div>
        </form>

        <ErrorNote message={error} />

        {inviteLink && (
          <div className="mt-3 rounded border border-neutral-800 bg-neutral-950 p-3">
            <p className="mb-1 text-xs text-neutral-500">
              Send this to the first admin. It is shown only once.
            </p>
            <code className="block break-all text-xs text-sky-400">{inviteLink}</code>
          </div>
        )}
      </Card>

      <Card className="space-y-2">
        {companies.map((company) => (
          <div
            key={company.id}
            className="flex flex-wrap items-center gap-3 border-b border-neutral-800 py-2 text-sm last:border-0"
          >
            <span className="w-40 truncate">{company.name}</span>
            <Badge tone={statusTone(company.status)}>{company.status}</Badge>
            <span className="text-xs text-neutral-500">{company.member_count} members</span>
            <span className="text-xs text-neutral-500">
              {company.employees_used} of {company.max_employees} AI Employees
            </span>

            <div className="ml-auto flex items-center gap-2">
              <input
                type="number"
                defaultValue={company.max_employees}
                onBlur={(e) => void setLimitFor(company.id, e.target.value)}
                className="w-16 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs"
              />
              {company.status === "active" ? (
                <Button variant="ghost" onClick={() => void setStatus(company.id, "suspend")}>
                  Suspend
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => void setStatus(company.id, "reactivate")}>
                  Reactivate
                </Button>
              )}
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

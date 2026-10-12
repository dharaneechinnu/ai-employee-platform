import { useEffect, useState } from "react";
import { Icon } from "../components/icons";
import { Avatar, Button, Chip, ErrorNote, Input, PageBody, PageHeader, Spinner, useToast } from "../components/ui";
import { ApiError, api, type Member } from "../lib/api";
import { useAuth, useIsAdmin } from "../lib/auth";

/** Phase 1. Invites appear as a link to copy: there is no email service. */
export default function Members() {
  const { org, me } = useAuth();
  const isAdmin = useIsAdmin();
  const toast = useToast();

  const [members, setMembers] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");
  const [link, setLink] = useState<{ url: string; email: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!org) return;
    setMembers(await api.get<Member[]>(`/orgs/${org.id}/members`));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setError(null);
    setBusy(true);
    try {
      const created = await api.post<{ invite_token: string }>(`/orgs/${org.id}/invites`, { email, role });
      // Shown exactly once. Only the hash is stored, so it cannot be
      // retrieved later: a lost link means issuing a new invite.
      setLink({ url: `${window.location.origin}/login?token=${created.invite_token}`, email });
      setCopied(false);
      setEmail("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the invite.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
      toast("Invite link copied.");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      toast("Copy failed. Select the link and copy it by hand.", "bad");
    }
  }

  if (!members) {
    return (
      <>
        <PageHeader crumb="Team" title="Members" />
        <Spinner />
      </>
    );
  }

  return (
    <>
      <PageHeader crumb="Team" title="Members">
        <Chip tone="mute" dot={false}>
          {members.length} {members.length === 1 ? "person" : "people"}
        </Chip>
      </PageHeader>

      <PageBody>
        <div className="flex flex-wrap items-start gap-5">
          <section className="flex min-w-0 flex-[999_1_420px] flex-col gap-2.5">
            {members.map((member, i) => (
              <div
                key={member.id}
                className="card lift rise flex items-center gap-3.5 p-4"
                style={{ animationDelay: `${Math.min(i, 8) * 0.05}s` }}
              >
                <Avatar name={member.full_name || member.email} size={44} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">
                    {member.full_name || member.email.split("@")[0]}
                    {member.id === me?.id && <span className="ml-1.5 text-[13px] font-normal text-dim">(you)</span>}
                  </div>
                  <div className="truncate text-[13px] text-muted">{member.email}</div>
                </div>
                <Chip tone={member.role === "admin" ? "brand" : "mute"} dot={false}>
                  {member.role}
                </Chip>
              </div>
            ))}
            <p className="mt-1.5 text-[13px] leading-normal text-dim">
              Admins build AI Employees, connect providers, set permissions and decide approvals. Members assign tasks,
              watch runs and search memory.
            </p>
          </section>

          {isAdmin && (
            <form onSubmit={invite} className="card rise flex w-full max-w-[460px] flex-[1_1_360px] flex-col gap-4 p-5" style={{ animationDelay: ".08s" }}>
              <h2 className="font-display text-lg font-semibold">Invite someone</h2>
              <Input label="Email" type="email" value={email} onChange={setEmail} required autoComplete="off" />
              <fieldset className="flex flex-col gap-2">
                <legend className="label mb-2">Role</legend>
                <div className="flex gap-2">
                  {(["member", "admin"] as const).map((option) => (
                    <label
                      key={option}
                      className={`flex h-[46px] flex-1 cursor-pointer items-center gap-2.5 rounded-xl border px-3.5 text-sm capitalize transition-colors ${
                        role === option ? "border-accent bg-accent-soft text-ink" : "border-line2 text-muted hover:border-accent-line"
                      }`}
                    >
                      <input
                        type="radio"
                        name="role"
                        value={option}
                        checked={role === option}
                        onChange={() => setRole(option)}
                        style={{ accentColor: "var(--accent)" }}
                      />
                      {option}
                    </label>
                  ))}
                </div>
              </fieldset>
              <ErrorNote message={error} />
              <Button type="submit" disabled={busy || !email}>
                {busy ? "Creating…" : "Create invite link"}
              </Button>

              {link && (
                <div
                  role="status"
                  className="flex flex-col gap-2 rounded-[14px] border border-accent-line p-3.5"
                  style={{
                    background:
                      "linear-gradient(90deg,var(--sunken) 0%,var(--sunken) 40%,var(--accent-soft) 50%,var(--sunken) 60%,var(--sunken) 100%)",
                    backgroundSize: "250% 100%",
                    animation: "rise .45s cubic-bezier(.16,1,.3,1) both, shimmer 4s linear .5s infinite",
                  }}
                >
                  <span className="text-xs text-accent-text">
                    Shown once. Send it to {link.email} yourself; there is no email service.
                  </span>
                  <div className="flex items-center gap-2.5">
                    <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{link.url}</code>
                    <Button size="sm" variant="ghost" onClick={() => void copy()}>
                      <Icon name={copied ? "check" : "copy"} size={15} />
                      {copied ? "Copied" : "Copy"}
                    </Button>
                  </div>
                </div>
              )}
            </form>
          )}
        </div>
      </PageBody>
    </>
  );
}

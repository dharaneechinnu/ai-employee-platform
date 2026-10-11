import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Spinner } from "../components/ui";
import { ApiError, api, type Member } from "../lib/api";
import { useAuth, useIsAdmin } from "../lib/auth";

/** Phase 1. Invites appear as a link to copy: there is no email service. */
export default function Members() {
  const { org } = useAuth();
  const isAdmin = useIsAdmin();

  const [members, setMembers] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    try {
      const created = await api.post<{ invite_token: string }>(`/orgs/${org.id}/invites`, {
        email,
        role: "member",
      });
      // Shown exactly once. Only the hash is stored, so it cannot be
      // retrieved later: a lost link means issuing a new invite.
      setLink(`${window.location.origin}/login?token=${created.invite_token}`);
      setEmail("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the invite.");
    }
  }

  if (!members) return <Spinner />;

  return (
    <div className="space-y-4">
      <h1 className="text-lg">Members</h1>

      {isAdmin && (
        <Card className="space-y-3">
          <form onSubmit={invite} className="flex items-end gap-2">
            <div className="flex-1">
              <Input
                label="Invite by email"
                type="email"
                value={email}
                onChange={setEmail}
                required
              />
            </div>
            <Button type="submit">Create link</Button>
          </form>

          <ErrorNote message={error} />

          {link && (
            <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
              <p className="mb-1 text-xs text-neutral-500">
                Copy this and send it yourself. It is shown only once.
              </p>
              <code className="block break-all text-xs text-sky-400">{link}</code>
            </div>
          )}
        </Card>
      )}

      <Card className="space-y-2">
        {members.map((member) => (
          <div
            key={member.id}
            className="flex items-center gap-3 border-b border-neutral-800 py-2 text-sm last:border-0"
          >
            <span>{member.full_name ?? member.email}</span>
            <span className="text-xs text-neutral-600">{member.email}</span>
            <div className="ml-auto">
              <Badge tone={member.role === "admin" ? "blue" : "gray"}>{member.role}</Badge>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

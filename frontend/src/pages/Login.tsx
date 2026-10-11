import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, ErrorNote, Input } from "../components/ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Sign in, or accept an invitation.
 *
 * There is no sign-up form, because the backend has no registration
 * endpoint: an account exists only by accepting an invite. An invite
 * link carries ?token=..., which switches this page into accept mode.
 */
export default function Login() {
  const { login, acceptInvite } = useAuth();
  const [params] = useSearchParams();
  const inviteToken = params.get("token");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (inviteToken) {
        await acceptInvite(inviteToken, password, fullName);
      } else {
        await login(email, password);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-lg">AI Employee Platform</h1>
        <p className="mb-5 text-xs text-neutral-500">
          {inviteToken ? "Set a password to join your company." : "Sign in to continue."}
        </p>

        <form onSubmit={submit} className="space-y-3">
          {!inviteToken && (
            <Input label="Email" type="email" value={email} onChange={setEmail} required />
          )}
          {inviteToken && (
            <Input label="Your name" value={fullName} onChange={setFullName} />
          )}
          <Input
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            required
            placeholder={inviteToken ? "At least 12 characters" : undefined}
          />

          <ErrorNote message={error} />

          <Button type="submit" disabled={busy}>
            {busy ? "Working…" : inviteToken ? "Join" : "Sign in"}
          </Button>
        </form>

        {!inviteToken && (
          <p className="mt-4 text-xs text-neutral-600">
            Accounts are created by invitation only. Ask an admin for a link.
          </p>
        )}
      </Card>
    </div>
  );
}

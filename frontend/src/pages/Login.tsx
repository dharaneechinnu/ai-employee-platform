import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/icons";
import { AuthShell, AuthSwitch, PasswordField } from "../components/AuthLayout";
import { ErrorNote, Input } from "../components/ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Sign in, or finish setting up an account.
 *
 * Sign in takes an email address or a username. A setup link carries
 * ?token=..., which switches this page into setup mode: the account
 * exists but has no password until its owner sets one.
 */
export default function Login() {
  const { login, completeSetup } = useAuth();
  const [params] = useSearchParams();
  const inviteToken = params.get("token");
  const next = params.get("next");
  const registerTo = next ? `/register?next=${encodeURIComponent(next)}` : "/register";

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      if (inviteToken) {
        await completeSetup(inviteToken, password, fullName);
      } else {
        await login(identifier.trim(), password);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 429
            ? "Too many tries. Wait a minute and try again."
            : err.message
          : "Could not reach the server. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      headline="Free AI keys. Many models. One assistant."
      ticker="Build agents on free model keys. For every task, your prompt goes to the model best at it, and agents do real work in your mail, calendar and files."
    >
      <form onSubmit={submit} className="auth-card flex flex-col gap-5" noValidate={false}>
        <div className="flex flex-col gap-1.5">
          <h2 className="font-display text-[26px] font-semibold tracking-[-0.025em]">{inviteToken ? "Set your password" : "Sign in"}</h2>
          <p className="text-[14px] leading-normal text-muted">
            {inviteToken ? "Choose a password to finish setting up your account." : "Welcome back. Use your email or your username."}
          </p>
        </div>

        {inviteToken ? (
          <Input label="Your name" name="name" value={fullName} onChange={setFullName} autoComplete="name" autoFocus />
        ) : (
          <Input
            label="Email or username"
            name="identifier"
            value={identifier}
            onChange={setIdentifier}
            required
            autoComplete="username"
            autoFocus
            spellCheck={false}
          />
        )}

        <PasswordField
          value={password}
          onChange={setPassword}
          autoComplete={inviteToken ? "new-password" : "current-password"}
          placeholder={inviteToken ? "At least 10 characters" : undefined}
        />

        <ErrorNote message={error} />

        <button type="submit" disabled={busy} className="btn btn-primary h-11 text-[15px]">
          {busy ? "Signing in…" : inviteToken ? "Continue" : "Sign in"}
          {!busy && <Icon name="arrow" size={18} strokeWidth={2} />}
        </button>

        {!inviteToken && (
          <>
            <AuthSwitch question="New here?" to={registerTo} action="Create an account" />
            <p className="border-t border-line pt-4 text-center text-[13px] text-dim">
              <Link to="/" className="hover:text-ink hover:underline">
                What is Baton?
              </Link>
            </p>
          </>
        )}
      </form>
    </AuthShell>
  );
}

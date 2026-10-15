import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/icons";
import { BrandMark } from "../components/Layout";
import { ErrorNote, Input, ThemeToggle } from "../components/ui";
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
  const [showPassword, setShowPassword] = useState(false);
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
    <div className="flex min-h-screen flex-wrap">
      <AuthStage
        headline="Your AI team, already at work."
        ticker="AI Employees that do real work in your email, calendar, files and data, while you stay in control."
      />

      <section className="flex flex-[1_1_440px] items-center justify-center px-6 py-12">
        <div className="rise w-full max-w-[400px]">
          <form onSubmit={submit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-1.5">
              <h2 className="font-display text-[26px] font-semibold tracking-[-0.02em]">{inviteToken ? "Join your company" : "Sign in"}</h2>
              <p className="text-sm text-muted">
                {inviteToken ? "Set a password to accept the invitation." : "Welcome back to your workspace."}{" "}
                <Link to="/" className="text-accent-text hover:underline">
                  What is this?
                </Link>
              </p>
            </div>

            {inviteToken ? (
              <Input label="Your name" value={fullName} onChange={setFullName} autoComplete="name" />
            ) : (
              <Input label="Email" type="email" value={email} onChange={setEmail} required autoComplete="email" />
            )}

            <label className="flex flex-col gap-2">
              <span className="label">Password</span>
              <span className="relative block">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  required
                  autoComplete={inviteToken ? "new-password" : "current-password"}
                  placeholder={inviteToken ? "At least 12 characters" : undefined}
                  onChange={(e) => setPassword(e.target.value)}
                  className="field pr-12"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-0.5 top-0.5 flex h-[42px] w-11 items-center justify-center text-muted hover:text-accent-text"
                >
                  <Icon name="eye" />
                </button>
              </span>
            </label>

            <ErrorNote message={error} />

            <button type="submit" disabled={busy} className="btn btn-primary h-11 text-[15px]">
              {busy ? "Working…" : inviteToken ? "Join" : "Sign in"}
              {!busy && <Icon name="arrow" size={18} strokeWidth={2} />}
            </button>

            {!inviteToken && (
              <p className="border-t border-line pt-4 text-[13px] leading-normal text-dim">
                There is no sign-up. Accounts come from an invite link sent by your company admin.
              </p>
            )}
          </form>
        </div>
      </section>
    </div>
  );
}

/**
 * The left half of both sign-in pages: the brand, one clear line about
 * the product and three plain benefits. Calm on purpose; the work is on
 * the right.
 */
export function AuthStage({
  headline,
  ticker,
  points = [
    "Assign work in plain words, or just say it",
    "Anything risky waits for your approval",
    "Every step is on record, with what it cost",
  ],
  badge,
}: {
  headline: string;
  ticker: string;
  points?: string[];
  badge?: string;
}) {
  return (
    <section className="relative flex flex-[1_1_520px] flex-col justify-between gap-12 border-line bg-raised px-6 py-10 sm:px-14 lg:min-h-screen lg:border-r">
      <div className="flex items-center gap-3">
        <BrandMark size={32} />
        <span className="flex-1 font-display text-[17px] font-semibold">AI Employees</span>
        {badge && <span className="rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent-text">{badge}</span>}
        <ThemeToggle />
      </div>

      <div className="rise flex max-w-[520px] flex-col gap-6">
        <h1 className="text-balance font-display text-[36px] font-semibold leading-[1.1] tracking-[-0.025em] sm:text-[46px]">
          {headline}
        </h1>
        <p className="text-[17px] leading-relaxed text-muted">{ticker}</p>
        <ul className="flex flex-col gap-3.5">
          {points.map((point) => (
            <li key={point} className="flex items-center gap-3 text-[15px]">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-text">
                <Icon name="check" size={13} strokeWidth={2.6} />
              </span>
              {point}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[13px] text-dim">For operations, sales, HR and engineering teams.</p>
    </section>
  );
}

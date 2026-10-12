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
        ticker="Assign a task. Watch it run. Approve what matters."
        orbit={[
          { label: "Manager", tone: "var(--run)", live: true },
          { label: "Specialist", tone: "var(--ok)" },
          { label: "Needs you", tone: "var(--ask)" },
        ]}
      />

      <section className="flex flex-[1_1_440px] items-center justify-center px-6 py-12">
        <div className="halo rise w-full max-w-[420px] rounded-3xl p-[1.5px]" style={{ boxShadow: "0 40px 120px -50px var(--glow)", animationDelay: ".15s" }}>
          <form onSubmit={submit} className="flex flex-col gap-5 rounded-[23px] bg-panel p-8 transition-colors duration-500 sm:p-9">
            <div className="flex flex-col gap-1.5">
              <h2 className="font-display text-[28px] font-semibold tracking-[-0.02em]">{inviteToken ? "Join your company" : "Sign in"}</h2>
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

            <button type="submit" disabled={busy} className="btn btn-primary h-[50px] rounded-[14px] text-[15px]">
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
 * The animated left half of both sign-in pages: drifting light, a
 * moving grid, and a few labels orbiting the brand mark.
 */
export function AuthStage({
  headline,
  ticker,
  orbit,
  badge,
}: {
  headline: string;
  ticker: string;
  orbit: { label: string; tone: string; live?: boolean }[];
  badge?: string;
}) {
  const positions = [
    { left: 130, top: -22 },
    { left: -50, top: 230 },
    { left: 250, top: 240 },
  ];

  return (
    <section className="relative flex min-h-[560px] flex-[1_1_560px] flex-col justify-between overflow-hidden border-line px-6 py-10 sm:px-14 lg:border-r">
      <div
        aria-hidden="true"
        className="absolute inset-0"
        style={{
          backgroundImage: "linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px)",
          backgroundSize: "48px 48px",
          maskImage: "radial-gradient(ellipse at center,#000 30%,transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse at center,#000 30%,transparent 75%)",
        }}
      />
      <div aria-hidden="true" className="absolute left-[-120px] top-[10%] h-[520px] w-[520px] rounded-full opacity-40 blur-[70px]" style={{ background: "var(--accent)", animation: "drift 16s ease-in-out infinite" }} />
      <div aria-hidden="true" className="absolute -bottom-16 -right-24 h-[420px] w-[420px] rounded-full opacity-20 blur-[70px]" style={{ background: "var(--spark)", animation: "drift 16s ease-in-out -6s infinite" }} />

      <div className="rise relative flex items-center gap-3">
        <BrandMark size={40} />
        <span className="flex-1 font-display text-lg font-semibold">AI Employees</span>
        {badge && (
          <span className="rounded-full bg-accent-soft px-3 py-1 font-mono text-xs tracking-[0.12em] text-accent-text">{badge}</span>
        )}
        <ThemeToggle />
      </div>

      <div aria-hidden="true" className="relative mx-auto my-6 flex h-[340px] w-[340px] max-w-full items-center justify-center">
        <div className="absolute h-[340px] w-[340px] rounded-full border border-dashed border-line2" />
        <div className="absolute h-[210px] w-[210px] rounded-full border border-line2" />
        <div className="absolute h-[340px] w-[340px]" style={{ animation: "spin 30s linear infinite" }}>
          {orbit.slice(0, 3).map((item, i) => (
            <div
              key={item.label}
              className="absolute flex items-center gap-2 whitespace-nowrap rounded-xl border border-line2 bg-panel px-3 py-2 text-[13px] shadow-lift"
              style={{ ...positions[i], animation: "spin 30s linear infinite reverse" }}
            >
              <i className={`block h-2 w-2 rounded-full ${item.live ? "live-run" : ""}`} style={{ background: item.tone }} />
              {item.label}
            </div>
          ))}
        </div>
        <div className="halo float h-[120px] w-[120px] rounded-[34px] p-0.5" style={{ animation: "ring 5s linear infinite, float 5s ease-in-out infinite" }}>
          <div className="flex h-full w-full items-center justify-center rounded-[32px]" style={{ background: "linear-gradient(135deg,var(--accent),var(--accent2) 60%,var(--spark))" }}>
            <div className="h-[30px] w-[30px] rounded-[9px]" style={{ background: "var(--on-accent)" }} />
          </div>
        </div>
      </div>

      <div className="relative flex max-w-[520px] flex-col gap-3.5">
        <h1 className="rise spectrum-text text-balance font-display text-[40px] font-bold leading-[1.05] tracking-[-0.035em] sm:text-[52px]" style={{ animationDelay: ".1s" }}>
          {headline}
        </h1>
        <p className="rise font-mono text-sm text-accent-text" style={{ animationDelay: ".2s" }}>
          {ticker}
        </p>
      </div>
    </section>
  );
}

import { useState } from "react";
import { ApiError } from "../../lib/api";
import { Icon } from "../icons";
import { StaffBadge, StaffLogo } from "./bits";
import { call, setPlatformToken } from "./api";

/**
 * The staff sign-in. Always dark, so nobody mistakes it for their own
 * Baton, with the white form card on top. It says up front what staff
 * can and cannot see, that customer accounts do not work here, and that
 * the attempt itself is logged.
 */
export function StaffSignIn({ onSignedIn }: { onSignedIn: () => void }) {
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
      setPlatformToken(body.access_token);
      onSignedIn();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That email and password don't match a staff account."
          : err instanceof ApiError
            ? err.message
            : "Sign in failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-theme="dark" className="flex min-h-screen flex-col text-[14px] leading-[1.45]" style={{ background: "#17152a", color: "#efeef6" }}>
      <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-6 gap-y-1 border-b border-line px-4 py-1.5 text-[12.5px] text-muted sm:px-6">
        <span className="flex items-center gap-2">
          <Icon name="shield" size={14} strokeWidth={2} className="text-[#c4b9f4]" />
          <span className="font-semibold text-ink">Restricted area</span> · for Baton staff only
        </span>
        <span>Every sign-in attempt is recorded</span>
      </div>

      <div className="flex flex-1 flex-wrap items-center justify-center gap-10 px-4 py-10 sm:gap-16 sm:px-6 sm:py-12">
        <div className="flex max-w-[460px] flex-[1_1_360px] flex-col gap-6 sm:gap-7">
          <div className="flex items-center gap-3">
            <StaffLogo size={36} />
            <span className="text-[19px] font-semibold">Baton</span>
            <StaffBadge large />
          </div>
          <h1 className="text-[34px] font-semibold leading-[1.08] tracking-[-0.025em] sm:text-[44px]">The staff console.</h1>
          <p className="max-w-[420px] text-base text-muted">
            Look after accounts, sign-in apps, AI providers and service access for everyone on Baton.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-line bg-raised p-4">
              <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-ok-text">
                <Icon name="check" size={15} strokeWidth={2.2} />
                You can see
              </div>
              <div className="text-[13px] leading-relaxed text-muted">
                Names, usernames, emails, status, counts, and which apps and AI providers are connected
              </div>
            </div>
            <div className="rounded-xl border border-line bg-raised p-4">
              <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-bad-text">
                <Icon name="x" size={15} strokeWidth={2.2} />
                You never see
              </div>
              <div className="text-[13px] leading-relaxed text-muted">Chats, memory, tasks, AI keys or sign-in tokens. Not even here.</div>
            </div>
          </div>
        </div>

        <form
          data-theme="light"
          onSubmit={(e) => void submit(e)}
          className="flex w-full max-w-[420px] flex-[0_1_420px] flex-col gap-[18px] rounded-[18px] bg-panel p-6 text-ink shadow-[0_30px_60px_-24px_rgba(0,0,0,.6)] sm:p-8"
        >
          <div>
            <h2 className="text-2xl font-semibold tracking-[-0.01em]">Staff sign-in</h2>
            <p className="mt-1.5 text-muted">Use your staff account. Customer accounts don't work here.</p>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Staff email</span>
            <input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Password</span>
            <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
          </label>
          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-[10px] bg-bad-soft px-3 py-2.5 text-[13px] text-bad-text">
              <Icon name="warn" size={16} className="mt-px" />
              {error}
            </div>
          )}
          <button type="submit" disabled={busy} className="inline-flex h-[46px] items-center justify-center gap-2 rounded-[10px] bg-[#17152a] text-[15px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60">
            <Icon name="shield" size={16} strokeWidth={2} />
            {busy ? "Checking…" : "Open the console"}
          </button>
          <p className="flex items-start gap-2 rounded-[10px] bg-bg px-3 py-2.5 text-[12.5px] text-muted">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent-text)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="mt-px shrink-0">
              <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />
            </svg>
            Your sign-in and every change you make is written to the audit log. Nobody can edit it.
          </p>
          <div className="border-t border-line pt-3.5 text-center text-[13px] text-muted">
            Looking for your own Baton?{" "}
            <a href="/login" className="font-semibold text-accent-text">
              Go to the normal sign-in
            </a>
          </div>
        </form>
      </div>
    </div>
  );
}

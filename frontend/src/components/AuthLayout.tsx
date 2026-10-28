import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { BrandMark } from "./BrandMark";
import { Icon, type IconName } from "./icons";
import { ThemeToggle } from "./ui";

/**
 * The frame shared by Sign in, Create account and the staff sign-in:
 * a quiet brand panel with what the product is for, and the form beside
 * it. On a phone the panel shrinks to a slim brand bar so the form is the
 * first thing on screen.
 */

const DEFAULT_POINTS: { icon: IconName; title: string; body: string }[] = [
  { icon: "key", title: "Start with free AI keys", body: "Use the free tiers from Gemini, Groq, OpenRouter or Mistral. You can add paid ones later." },
  { icon: "cpu", title: "Many models, one assistant", body: "Connect several AIs at once. Each prompt goes to the model that suits it: code, writing, analysis or a quick answer." },
  { icon: "refresh", title: "Never stuck on a limit", body: "If one model is busy or rate-limited, the work moves to the next one on its own." },
  { icon: "approvals", title: "You stay in control", body: "Agents run on a schedule, and anything risky waits for your yes." },
];

export function AuthStage({
  headline,
  ticker,
  points,
  badge,
}: {
  headline: string;
  ticker: string;
  /** Plain one-line points (kept for the staff page). */
  points?: string[];
  badge?: string;
}) {
  const rich = points ? points.map((p) => ({ icon: "check" as IconName, title: p, body: "" })) : DEFAULT_POINTS;
  return (
    <section className="auth-aside flex w-full flex-col justify-between gap-10 border-line px-6 py-5 sm:px-12 lg:min-h-screen lg:w-auto lg:flex-[1_1_520px] lg:border-r lg:px-14 lg:py-12">
      <div className="flex items-center gap-3">
        <BrandMark size={32} />
        <span className="flex-1 font-display text-[17px] font-semibold tracking-[-0.01em]">AI Employees</span>
        {badge && <span className="rounded-full bg-accent-soft px-3 py-1 text-xs font-semibold tracking-wide text-accent-text">{badge}</span>}
        <ThemeToggle />
      </div>

      <div className="rise hidden max-w-[500px] flex-col gap-7 lg:flex">
        <div className="flex flex-col gap-4">
          <h1 className="font-display text-[44px] font-semibold leading-[1.06] tracking-[-0.03em] xl:text-[50px]">{headline}</h1>
          <p className="text-[17px] leading-relaxed text-muted">{ticker}</p>
        </div>
        <ul className="flex flex-col gap-5">
          {rich.map((point) => (
            <li key={point.title} className="flex items-start gap-4">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] border border-accent-line bg-accent-soft text-accent-text">
                <Icon name={point.icon} size={17} strokeWidth={2} />
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="text-[15px] font-semibold">{point.title}</span>
                {point.body && <span className="text-[14px] leading-relaxed text-muted">{point.body}</span>}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="hidden text-[13px] text-dim lg:block">For students, researchers and anyone with work to get done.</p>
    </section>
  );
}

/** The two-column page: brand panel, then the form centred in its half. */
export function AuthShell({ children, badge, headline, ticker }: { children: ReactNode; badge?: string; headline: string; ticker: string }) {
  return (
    <div className="flex min-h-screen flex-col bg-bg lg:flex-row">
      <AuthStage headline={headline} ticker={ticker} badge={badge} />
      <section className="flex w-full flex-1 items-center lg:w-auto lg:flex-[1_1_440px] lg:items-center justify-center px-5 py-10 sm:px-8 sm:py-14">
        <div className="rise w-full max-w-[420px]">{children}</div>
      </section>
    </div>
  );
}

/** A password box with a show/hide button. */
export function PasswordField({
  label = "Password",
  value,
  onChange,
  autoComplete,
  placeholder,
  error,
  hint,
  name,
  action,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  placeholder?: string;
  error?: string | null;
  hint?: ReactNode;
  name?: string;
  /** Something small beside the label, e.g. a "Forgot" link. */
  action?: ReactNode;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={`pw-${name ?? autoComplete}`} className="label">
          {label}
        </label>
        {action}
      </div>
      <span className="relative block">
        <input
          id={`pw-${name ?? autoComplete}`}
          name={name ?? "password"}
          type={show ? "text" : "password"}
          value={value}
          required
          autoComplete={autoComplete}
          placeholder={placeholder}
          aria-invalid={error ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
          className="field pr-12"
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          aria-label={show ? "Hide password" : "Show password"}
          aria-pressed={show}
          className="absolute right-1 top-1 flex h-9 w-10 items-center justify-center rounded-lg text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          <Icon name="eye" size={18} />
          {show && <i className="absolute h-0.5 w-5 rotate-45 rounded bg-current" aria-hidden="true" />}
        </button>
      </span>
      {error ? (
        <span className="field-msg field-msg-bad" role="alert">
          {error}
        </span>
      ) : (
        hint
      )}
    </div>
  );
}

/** "Don't have an account? Create one", in both directions. */
export function AuthSwitch({ question, to, action }: { question: string; to: string; action: string }) {
  return (
    <p className="text-center text-[14px] text-muted">
      {question}{" "}
      <Link to={to} className="font-semibold text-accent-text hover:underline">
        {action}
      </Link>
    </p>
  );
}

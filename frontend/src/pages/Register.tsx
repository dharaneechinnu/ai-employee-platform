import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/icons";
import { AuthShell, AuthSwitch, PasswordField } from "../components/AuthLayout";
import { ErrorNote, Input } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

const USERNAME_RULE = /^[A-Za-z0-9][A-Za-z0-9_.-]{2,29}$/;
const MIN_PASSWORD = 12;

type Field = "username" | "email" | "password";
type Availability = "idle" | "checking" | "free" | "taken";

/** 0 to 4. Length is the only thing the server asks for; the rest is a nudge. */
function passwordLevel(password: string): number {
  if (password.length === 0) return 0;
  if (password.length < MIN_PASSWORD) return 1;
  let level = 2;
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  if (password.length >= 14 || kinds >= 3) level = 3;
  if (password.length >= 14 && kinds >= 3) level = 4;
  return level;
}

const LEVEL_WORD = ["", "Too short", "Good enough", "Strong", "Very strong"];

/** Create an account. The person is signed in the moment it succeeds. */
export default function Register() {
  const { register } = useAuth();
  const [params] = useSearchParams();
  const next = params.get("next");
  const loginTo = next ? `/login?next=${encodeURIComponent(next)}` : "/login";

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const [serverErrors, setServerErrors] = useState<Partial<Record<Field, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [availability, setAvailability] = useState<Availability>("idle");

  const usernameValid = USERNAME_RULE.test(username);

  // Ask whether the name is free once typing pauses. A failed check says
  // nothing: the server still decides when the form is sent.
  useEffect(() => {
    if (!usernameValid) {
      setAvailability("idle");
      return;
    }
    setAvailability("checking");
    let current = true;
    const timer = window.setTimeout(() => {
      api
        .get<{ available: boolean }>(`/auth/username-available?username=${encodeURIComponent(username)}`)
        .then((body) => {
          if (current) setAvailability(body.available ? "free" : "taken");
        })
        .catch(() => {
          if (current) setAvailability("idle");
        });
    }, 450);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [username, usernameValid]);

  const localErrors = useMemo(() => {
    const errors: Partial<Record<Field, string>> = {};
    if (username && !usernameValid) {
      errors.username =
        username.length < 3
          ? "Use at least 3 characters."
          : username.length > 30
            ? "Use 30 characters or fewer."
            : "Use letters, digits, underscore, dot or hyphen, starting with a letter or digit.";
    }
    if (touched && !/^\S+@\S+\.\S+$/.test(email.trim())) errors.email = "Enter a valid email address.";
    if (touched && password.length < MIN_PASSWORD) errors.password = `Use at least ${MIN_PASSWORD} characters.`;
    return errors;
  }, [username, usernameValid, email, password, touched]);

  const usernameError = serverErrors.username || localErrors.username || (availability === "taken" ? "That username is taken." : null);
  const level = passwordLevel(password);

  function edit<T>(setter: (v: T) => void, field: Field) {
    return (value: T) => {
      setter(value);
      setServerErrors((current) => ({ ...current, [field]: undefined }));
      setError(null);
    };
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setTouched(true);
    setError(null);
    if (!usernameValid || !/^\S+@\S+\.\S+$/.test(email.trim()) || password.length < MIN_PASSWORD || availability === "taken") return;

    setBusy(true);
    try {
      await register({ username, email: email.trim(), password });
    } catch (err) {
      if (err instanceof ApiError) {
        const found: Partial<Record<Field, string>> = {};
        for (const item of err.fields ?? []) {
          const field = item.field.split(".").pop() as Field;
          if (field === "username" || field === "email" || field === "password") found[field] = item.message;
        }
        if (Object.keys(found).length === 0 && err.status === 409) {
          // A plain conflict message names which of the two is taken.
          if (/username/i.test(err.message)) found.username = err.message;
          else if (/email/i.test(err.message)) found.email = err.message;
        }
        setServerErrors(found);
        if (Object.keys(found).length === 0) setError(err.status === 429 ? "Too many tries. Wait a minute and try again." : err.message);
      } else {
        setError("Could not reach the server. Check your connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  const usernameHint =
    availability === "checking" ? (
      <span className="field-msg">Checking…</span>
    ) : availability === "free" ? (
      <span className="field-msg field-msg-ok">
        <Icon name="check" size={13} strokeWidth={2.6} className="mr-1 inline" />
        {username} is available.
      </span>
    ) : (
      <span className="field-msg">3 to 30 characters: letters, digits, underscore, dot or hyphen.</span>
    );

  return (
    <AuthShell
      headline="Set up your assistant in a minute."
      ticker="Create your account, connect the tools you already use, and hand off the first task today."
    >
      <form onSubmit={submit} className="auth-card flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <h2 className="font-display text-[26px] font-semibold tracking-[-0.025em]">Create your account</h2>
          <p className="text-[14px] leading-normal text-muted">Free to start. You will be signed in straight away.</p>
        </div>

        <Input
          label="Username"
          name="username"
          value={username}
          onChange={edit(setUsername, "username")}
          required
          autoComplete="username"
          autoFocus
          spellCheck={false}
          maxLength={40}
          error={usernameError}
          hint={usernameHint}
        />

        <Input
          label="Email"
          name="email"
          type="email"
          inputMode="email"
          value={email}
          onChange={edit(setEmail, "email")}
          required
          autoComplete="email"
          spellCheck={false}
          error={serverErrors.email || localErrors.email}
        />

        <PasswordField
          name="new-password"
          value={password}
          onChange={edit(setPassword, "password")}
          autoComplete="new-password"
          error={serverErrors.password || localErrors.password}
          hint={
            <div className="flex flex-col gap-1.5" aria-live="polite">
              <div className="strength" data-level={level} aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </div>
              <span className="field-msg">
                {password ? `${LEVEL_WORD[level]}. ` : ""}Use at least {MIN_PASSWORD} characters. A short sentence works well.
              </span>
            </div>
          }
        />

        <ErrorNote message={error} />

        <button type="submit" disabled={busy} className="btn btn-primary h-11 text-[15px]">
          {busy ? "Creating your account…" : "Create account"}
          {!busy && <Icon name="arrow" size={18} strokeWidth={2} />}
        </button>

        <AuthSwitch question="Already have an account?" to={loginTo} action="Sign in" />
        <p className="border-t border-line pt-4 text-center text-[13px] text-dim">
          <Link to="/" className="hover:text-ink hover:underline">
            What is AI Employees?
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}

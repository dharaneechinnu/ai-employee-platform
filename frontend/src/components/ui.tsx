/**
 * Shared pieces of the "Gilded" interface.
 *
 * Colour lives in CSS variables (src/index.css), so nothing here knows
 * whether it is dark or light. One gold button per screen; status is a
 * word plus a dot shape, never colour alone.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { useTheme } from "../lib/theme";
import { Icon, type IconName } from "./icons";

// ------------------------------------------------------------- buttons

type Variant = "gold" | "primary" | "ghost" | "ok" | "danger" | "danger-ghost";

const VARIANT_CLASS: Record<Variant, string> = {
  gold: "btn-gold",
  primary: "btn-gold",
  ghost: "btn-ghost",
  ok: "btn-ok",
  danger: "btn-danger",
  "danger-ghost": "btn-danger-ghost",
};

export function Button({
  children,
  variant = "gold",
  size = "md",
  icon,
  className = "",
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "md" | "sm";
  icon?: IconName;
}) {
  return (
    <button
      type={type}
      className={`btn ${VARIANT_CLASS[variant]} ${size === "sm" ? "btn-sm" : ""} ${className}`}
      {...rest}
    >
      {icon && <Icon name={icon} size={16} strokeWidth={2.2} />}
      {children}
    </button>
  );
}

/**
 * A button that must be held for a second before it fires. Used where a
 * mis-click cannot be undone. Keyboard users press Enter or Space twice.
 */
export function HoldButton({
  children,
  onConfirm,
  variant = "ok",
  ms = 1200,
}: {
  children: ReactNode;
  onConfirm: () => void;
  variant?: Variant;
  ms?: number;
}) {
  const [holding, setHolding] = useState(false);
  const [armed, setArmed] = useState(false);
  const timer = useRef<number>();

  useEffect(() => () => window.clearTimeout(timer.current), []);

  function start() {
    setHolding(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setHolding(false);
      onConfirm();
    }, ms);
  }

  function stop() {
    setHolding(false);
    window.clearTimeout(timer.current);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (event.repeat) return;
    if (armed) {
      setArmed(false);
      onConfirm();
    } else {
      setArmed(true);
      window.setTimeout(() => setArmed(false), 3000);
    }
  }

  return (
    <button
      type="button"
      className={`btn hold ${VARIANT_CLASS[variant]}`}
      data-holding={holding}
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      onKeyDown={onKeyDown}
    >
      <span>{armed ? "Press again to confirm" : children}</span>
    </button>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  return (
    <button type="button" className="icon-btn spin-hover" onClick={toggle} aria-label={label} title={label}>
      <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
    </button>
  );
}

// -------------------------------------------------------------- layout

export function Card({
  children,
  className = "",
  lift = false,
}: {
  children: ReactNode;
  className?: string;
  lift?: boolean;
}) {
  return <div className={`card ${lift ? "lift" : ""} ${className}`}>{children}</div>;
}

/** The bar at the top of every screen: where you are, the screen's actions, the theme switch. */
export function PageHeader({
  crumb,
  title,
  children,
}: {
  crumb?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-[18px] sm:px-6 lg:px-10">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {crumb && <div className="flex items-center gap-2 truncate text-[13px] text-dim">{crumb}</div>}
        <h1 className="truncate font-display text-[26px] font-semibold tracking-[-0.02em]">{title}</h1>
      </div>
      {children}
      <ThemeToggle />
    </header>
  );
}

export function PageBody({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`flex flex-col gap-5 px-4 pb-14 pt-6 sm:px-6 lg:px-10 ${className}`}>{children}</div>;
}

// -------------------------------------------------------------- inputs

export function Input({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required,
  hideLabel,
  mono,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  hideLabel?: boolean;
  mono?: boolean;
  autoComplete?: string;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className={hideLabel ? "sr-only" : "label"}>{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className={`field ${mono ? "font-mono" : ""}`}
      />
    </label>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
  hideLabel,
  badge,
  inputRef,
  onKeyDown,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  hideLabel?: boolean;
  badge?: ReactNode;
  inputRef?: React.Ref<HTMLTextAreaElement>;
  onKeyDown?: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className={hideLabel ? "sr-only" : "label flex items-center gap-2"}>
        {badge}
        {label}
      </span>
      <textarea
        ref={inputRef}
        value={value}
        rows={rows}
        placeholder={placeholder}
        onKeyDown={onKeyDown}
        onChange={(e) => onChange(e.target.value)}
        className="field"
      />
    </label>
  );
}

export function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="field">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      className="switch"
      onClick={() => onChange(!checked)}
    />
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
}) {
  return (
    <label className="flex h-11 min-w-0 flex-[0_1_300px] items-center gap-2.5 rounded-xl border border-line2 bg-sunken px-3 text-dim transition-colors focus-within:border-accent">
      <Icon name="search" size={16} strokeWidth={2} />
      <span className="sr-only">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="min-w-0 flex-1 border-0 bg-transparent text-sm text-ink outline-none placeholder:text-dim"
      />
    </label>
  );
}

export function Tabs<K extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: { key: K; label: string; count?: number }[];
  value: K;
  onChange: (key: K) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="group" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className="tab"
          aria-pressed={item.key === value}
          onClick={() => onChange(item.key)}
        >
          {item.label}
          {item.count !== undefined && <b className="font-mono text-[11px] font-medium text-dim">{item.count}</b>}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------- status

export type Tone = "run" | "ok" | "ask" | "bad" | "gold" | "mute";

/** Colour by meaning, so a run's state is readable at a glance. */
export function statusTone(status: string): Tone {
  if (["running", "queued", "working"].includes(status)) return status === "working" ? "ok" : "run";
  if (["completed", "active", "auto"].includes(status)) return "ok";
  if (["awaiting_approval", "ask", "paused", "untested"].includes(status)) return "ask";
  if (["failed", "cancelled", "blocked", "destructive", "suspended", "closed"].includes(status)) return "bad";
  if (["draft", "write"].includes(status)) return "gold";
  return "mute";
}

/** "awaiting_approval" reads better as "awaiting approval". */
export function humanise(value: string): string {
  return value.replace(/_/g, " ");
}

export function Chip({
  children,
  tone = "mute",
  dot = true,
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={`chip chip-${tone} ${className}`}>
      {dot && <i />}
      {children}
    </span>
  );
}

export function StatusChip({ status }: { status: string }) {
  return <Chip tone={statusTone(status)}>{humanise(status)}</Chip>;
}

/** @deprecated kept so older call sites read naturally; prefer Chip. */
export function Badge({ children, tone = "mute" }: { children: ReactNode; tone?: Tone }) {
  return (
    <Chip tone={tone} dot={false}>
      {children}
    </Chip>
  );
}

const AVATAR_GRADIENTS = [
  "linear-gradient(135deg,#D4A84B,#F0CF7A)",
  "linear-gradient(135deg,#5AB8F0,#A8DDF9)",
  "linear-gradient(135deg,#7BC99A,#BDE7CC)",
  "linear-gradient(135deg,#E8677A,#F6B3BD)",
  "linear-gradient(135deg,#B48CF0,#DCC8FA)",
];

function hash(text: string): number {
  let value = 0;
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0;
  return value;
}

/** A coloured initial. The colour is stable per name, so people learn it. */
export function Avatar({
  name,
  size = 32,
  rounded = "rounded-full",
  muted = false,
}: {
  name: string;
  size?: number;
  rounded?: string;
  muted?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center font-display font-bold ${rounded}`}
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.4),
        color: "#1A1306",
        background: AVATAR_GRADIENTS[hash(name) % AVATAR_GRADIENTS.length],
        opacity: muted ? 0.55 : 1,
      }}
    >
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}

export function UsageMeter({ used, limit, label }: { used: number; limit: number; label: string }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="flex min-w-[160px] flex-col gap-1.5">
      <div className="flex justify-between text-xs text-muted">
        <span>{label}</span>
        <span className="font-mono text-ink">
          {used} / {limit}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-raised" role="presentation">
        <div
          className="grow-x h-full rounded-full"
          style={{ width: `${pct}%`, background: "linear-gradient(90deg,var(--accent),var(--accent2))" }}
        />
      </div>
    </div>
  );
}

// ------------------------------------------------------ empty & errors

export function Empty({ message, hint, children }: { message: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-[18px] border-[1.5px] border-dashed border-line2 p-8 text-center">
      <p className="font-display text-base font-semibold">{message}</p>
      {hint && <p className="max-w-md text-sm text-muted">{hint}</p>}
      {children}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="flex items-start gap-2.5 rounded-xl bg-bad-soft px-3.5 py-2.5 text-sm text-bad-text">
      <Icon name="warn" size={18} className="mt-px" />
      <span>{message}</span>
    </div>
  );
}

/** The shape of what is coming, instead of a bare "Loading…". */
export function Spinner({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3 p-6" aria-busy="true" aria-label="Loading">
      <div className="skeleton h-7 w-48" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton h-16" style={{ opacity: 1 - i * 0.2 }} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------- toasts

type ToastTone = "ok" | "bad" | "info";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

const ToastContext = createContext<(message: string, tone?: ToastTone) => void>(() => {});

/** Every action ends in a short confirmation, then the toast leaves. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const show = useCallback((message: string, tone: ToastTone = "ok") => {
    const id = nextId.current++;
    setItems((current) => [...current.slice(-2), { id, message, tone }]);
    window.setTimeout(() => setItems((current) => current.filter((t) => t.id !== id)), 4000);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="pointer-events-none fixed bottom-6 right-4 z-50 flex flex-col items-end gap-2 sm:right-8" role="status" aria-live="polite">
        {items.map((toast) => (
          <div
            key={toast.id}
            className="pointer-events-auto flex min-w-[260px] max-w-sm items-center gap-3 rounded-[14px] border border-line2 bg-panel px-4 py-3 text-sm shadow-lift"
            style={{ animation: "toast-in .45s cubic-bezier(.16,1,.3,1) both" }}
          >
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px] ${
                toast.tone === "bad"
                  ? "bg-bad-soft text-bad-text"
                  : toast.tone === "info"
                    ? "bg-accent-soft text-accent-text"
                    : "bg-ok-soft text-ok-text"
              }`}
            >
              <Icon name={toast.tone === "bad" ? "x" : toast.tone === "info" ? "info" : "check"} size={16} strokeWidth={2.4} />
            </span>
            <span className="flex-1">{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

// --------------------------------------------------------------- time

/** "3 min ago", "in 47 min": the precise timestamp goes in a title attribute. */
export function relativeTime(iso: string, now = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  const minutes = Math.round(Math.abs(diff) / 60000);
  const future = diff > 0;
  let text: string;
  if (minutes < 1) return future ? "in under a minute" : "just now";
  if (minutes < 60) text = `${minutes} min`;
  else if (minutes < 60 * 24) {
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    text = rest && hours < 6 ? `${hours} h ${rest} min` : `${hours} h`;
  } else text = `${Math.round(minutes / (60 * 24))} d`;
  return future ? `in ${text}` : `${text} ago`;
}

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import { useToast } from "../ui";
import { initials, tileColour } from "./format";

/**
 * Small pieces the staff console screens share: the logo and STAFF
 * badge, the person tile, yes-or-no chips, the three-way choice, the
 * row menu, and an empty state.
 */

/** Baton's mark, in the console's colours. */
export function StaffLogo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <rect x="7" y="12" width="13" height="13" rx="3" fill="var(--on-accent)" />
      <rect x="20" y="7" width="6" height="6" rx="1.5" fill="var(--logo-spark)" />
    </svg>
  );
}

/** The word STAFF in reversed ink, next to the logo. */
export function StaffBadge({ large = false }: { large?: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-md font-semibold tracking-[0.08em] ${large ? "h-6 px-[9px] text-[11.5px]" : "h-[22px] px-2 text-[11px]"}`}
      style={{ background: "var(--strip-bg)", color: "var(--strip-text)" }}
    >
      STAFF
    </span>
  );
}

/** A person's initials on their own steady colour. */
export function PersonTile({ name, seed, size = 36 }: { name: string; seed: string; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center font-semibold text-white"
      style={{
        width: size,
        height: size,
        borderRadius: size >= 48 ? 14 : 10,
        background: tileColour(seed),
        fontSize: size >= 48 ? 18 : 13,
      }}
    >
      {initials(name)}
    </span>
  );
}

/** Active or Suspended: a word, a dot and a shape, never colour alone. */
export function StatusText({ active }: { active: boolean }) {
  return active ? (
    <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ok-text">
      <span aria-hidden="true" className="h-2 w-2 rounded-full bg-ok" />
      Active
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-bad-text">
      <span aria-hidden="true" className="h-2 w-2 rounded-[2px] bg-bad" />
      Suspended
    </span>
  );
}

/** A soft pill for a fact, e.g. "Signed up themselves". */
export function Pill({ children, tone = "mute", strong = false }: { children: ReactNode; tone?: "mute" | "brand" | "ask" | "ok" | "bad" | "run"; strong?: boolean }) {
  const tones = {
    mute: "bg-raised text-muted",
    brand: "bg-accent-soft text-accent-text",
    ask: "bg-ask-soft text-ask-text",
    ok: "bg-ok-soft text-ok-text",
    bad: "bg-bad-soft text-bad-text",
    run: "bg-run-soft text-run-text",
  };
  return (
    <span className={`inline-flex h-[26px] items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-[12.5px] ${strong ? "font-semibold" : "font-medium"} ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** "Yes", "No" or "last check failed", as a chip with a mark. */
export function YesNoChip({ name, state, tag }: { name: string; state: "yes" | "no" | "warn"; tag?: string }) {
  if (state === "yes") {
    return (
      <span className="inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium text-ok-text" style={{ borderColor: "color-mix(in srgb, var(--ok) 40%, transparent)", background: "color-mix(in srgb, var(--ok-soft) 55%, var(--panel))" }}>
        <Icon name="check" size={14} strokeWidth={2.4} />
        {name}
        {tag && <span className="text-xs text-muted">· {tag}</span>}
      </span>
    );
  }
  if (state === "warn") {
    return (
      <span className="inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium text-ask-text" style={{ borderColor: "color-mix(in srgb, var(--ask) 45%, transparent)", background: "color-mix(in srgb, var(--ask-soft) 60%, var(--panel))" }}>
        <Icon name="info" size={14} strokeWidth={2.2} />
        {name}
        <span className="text-xs">· last check failed</span>
      </span>
    );
  }
  return (
    <span className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-line2 bg-panel px-3 text-[13px] text-dim">
      {name} <span className="text-xs">· no</span>
    </span>
  );
}

/** Same as everyone, Allow or Block. */
export type Choice = "same" | "allow" | "block";

export function ThreeWay({ value, onChange, label, disabled }: { value: Choice; onChange: (next: Choice) => void; label: string; disabled?: boolean }) {
  const options: { key: Choice; label: string; on: string }[] = [
    { key: "same", label: "Same as everyone", on: "bg-panel text-ink" },
    { key: "allow", label: "Allow", on: "bg-ok text-ok-on" },
    { key: "block", label: "Block", on: "bg-bad text-bad-on" },
  ];
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex gap-0.5 rounded-[9px] bg-raised p-0.5">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          role="radio"
          aria-checked={value === o.key}
          disabled={disabled}
          onClick={() => value !== o.key && onChange(o.key)}
          className={`h-[30px] rounded-[7px] px-2.5 text-[12.5px] transition-colors disabled:opacity-60 ${value === o.key ? `${o.on} font-semibold shadow-[0_1px_2px_rgba(16,24,40,.08)]` : "font-medium text-muted hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A copy-to-clipboard helper that says what happened. */
export function useCopy() {
  const toast = useToast();
  return async (text: string, done = "Copied.") => {
    try {
      await navigator.clipboard.writeText(text);
      toast(done);
      return true;
    } catch {
      toast("Copy failed. Select the text and copy it by hand.", "bad");
      return false;
    }
  };
}

export interface MenuItem {
  label: string;
  icon?: IconName;
  danger?: boolean;
  onSelect: () => void;
}

/** The ⋮ button and its short list of actions. Closes on Escape or a click outside. */
export function RowMenu({ label, items, size = 36 }: { label: string; items: MenuItem[]; size?: number }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center justify-center rounded-lg text-muted transition-colors hover:bg-raised hover:text-ink"
        style={{ width: size, height: size }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="12" cy="5" r="1.8" />
          <circle cx="12" cy="12" r="1.8" />
          <circle cx="12" cy="19" r="1.8" />
        </svg>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1 flex min-w-[200px] flex-col rounded-xl border border-line bg-panel p-1 shadow-lift">
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`flex min-h-[40px] items-center gap-2.5 rounded-lg px-3 text-left text-sm hover:bg-raised ${item.danger ? "text-bad-text" : "text-ink"}`}
            >
              {item.icon && <Icon name={item.icon} size={16} />}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** A centred empty state with a soft icon tile. */
export function EmptyCard({ icon, tone = "mute", title, children, actions }: { icon: IconName; tone?: "mute" | "brand"; title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2.5 px-6 py-9 text-center">
      <span aria-hidden="true" className={`inline-flex h-12 w-12 items-center justify-center rounded-[14px] ${tone === "brand" ? "bg-accent-soft text-accent-text" : "bg-bg text-dim"}`}>
        <Icon name={icon} size={22} strokeWidth={2} />
      </span>
      <h3 className="mt-1 text-base font-semibold">{title}</h3>
      <p className="max-w-[300px] text-[13.5px] text-muted">{children}</p>
      {actions && <div className="mt-1.5 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

/** The heading of a console screen, with a line underneath. */
export function ScreenTitle({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em] sm:text-[30px]">{title}</h1>
        {children && <p className="mt-1.5 max-w-[760px] text-[13px] text-muted sm:text-sm">{children}</p>}
      </div>
      {action}
    </div>
  );
}

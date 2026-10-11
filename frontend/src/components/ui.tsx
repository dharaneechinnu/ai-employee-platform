/** Small shared pieces. Deliberately plain: this is a skeleton. */

import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-neutral-800 bg-neutral-900 p-4 ${className}`}>
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "ghost" | "danger";
  disabled?: boolean;
}) {
  const styles = {
    primary: "bg-sky-600 hover:bg-sky-500 text-white",
    ghost: "border border-neutral-700 hover:bg-neutral-800 text-neutral-200",
    danger: "bg-red-700 hover:bg-red-600 text-white",
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-3 py-1.5 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  );
}

export function Input({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-neutral-400">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm outline-none focus:border-sky-600"
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-neutral-400">{label}</span>
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm outline-none focus:border-sky-600"
      />
    </label>
  );
}

const TONES: Record<string, string> = {
  green: "bg-green-950 text-green-300 border-green-800",
  amber: "bg-amber-950 text-amber-300 border-amber-800",
  red: "bg-red-950 text-red-300 border-red-800",
  blue: "bg-sky-950 text-sky-300 border-sky-800",
  gray: "bg-neutral-800 text-neutral-300 border-neutral-700",
};

export function Badge({ children, tone = "gray" }: { children: ReactNode; tone?: string }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs ${TONES[tone] ?? TONES.gray}`}>
      {children}
    </span>
  );
}

/** Colour by meaning, so a run's state is readable at a glance. */
export function statusTone(status: string): string {
  if (["completed", "active", "working", "auto"].includes(status)) return "green";
  if (["running", "queued", "draft"].includes(status)) return "blue";
  if (["awaiting_approval", "ask", "paused", "untested"].includes(status)) return "amber";
  if (["failed", "cancelled", "blocked", "destructive"].includes(status)) return "red";
  return "gray";
}

export function Empty({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-neutral-800 p-8 text-center">
      <p className="text-sm text-neutral-400">{message}</p>
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="rounded border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
      {message}
    </div>
  );
}

export function Spinner() {
  return <p className="p-6 text-sm text-neutral-500">Loading…</p>;
}

import { useState } from "react";
import { ApiError, api, type ToolEntry } from "../lib/api";
import { toolAction, toolLabel } from "../lib/labels";
import { Icon } from "./icons";
import { useToast } from "./ui";

/**
 * Always allow / Ask me first / Blocked, for one tool.
 *
 * The same control on Connections, in an AI Employee's tool list and on
 * Permissions, so the choice is made right where the tool is. It saves a
 * company-wide rule for that tool, which every AI Employee (and every
 * specialist they hand work to) follows.
 *
 * "Always allow" on something that can't be undone asks once more, in
 * plain words, because it removes the person from the loop.
 */

export type Setting = "auto" | "ask" | "blocked";

export const PERMISSION_OPTIONS: { key: Setting; label: string; hint: string }[] = [
  { key: "auto", label: "Always allow", hint: "Runs without asking" },
  { key: "ask", label: "Ask me first", hint: "Waits for a person's OK" },
  { key: "blocked", label: "Blocked", hint: "Never runs" },
];

export const PERMISSION_LABEL: Record<Setting, string> = { auto: "Always allow", ask: "Ask me first", blocked: "Blocked" };

const SELECTED: Record<Setting, string> = {
  auto: "bg-ok-soft text-ok-text shadow-[inset_0_0_0_1px_var(--ok)] font-semibold",
  ask: "bg-ask-soft text-ask-text shadow-[inset_0_0_0_1px_var(--ask)] font-semibold",
  blocked: "bg-bad-soft text-bad-text shadow-[inset_0_0_0_1px_var(--bad)] font-semibold",
};

export default function PermissionChoice({
  orgId,
  tool,
  onSaved,
  disabled,
  size = "md",
}: {
  orgId: string;
  tool: Pick<ToolEntry, "name" | "side_effect" | "effective_setting" | "permanently_blocked">;
  onSaved?: (setting: Setting) => void;
  disabled?: boolean;
  size?: "md" | "sm";
}) {
  const toast = useToast();
  const [value, setValue] = useState<Setting>(tool.effective_setting as Setting);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const label = toolLabel(tool.name);

  if (tool.permanently_blocked) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-lg bg-bad-soft px-2.5 py-1.5 text-xs font-medium text-bad-text">
        <Icon name="lock" size={13} /> Never allowed on this platform
      </span>
    );
  }

  async function save(next: Setting) {
    const before = value;
    setValue(next); // show it straight away; undo if the save fails
    setConfirming(false);
    setSaving(true);
    try {
      await api.put(`/orgs/${orgId}/policies`, { scope: "tool", scope_value: tool.name, side_effect: null, setting: next });
      toast(
        next === "auto"
          ? `${label}: always allowed. No approval needed.`
          : next === "ask"
            ? `${label}: AI Employees will ask you first.`
            : `${label}: blocked.`,
        next === "blocked" ? "info" : "ok",
      );
      onSaved?.(next);
    } catch (err) {
      setValue(before);
      toast(err instanceof ApiError ? err.message : "Could not save that.", "bad");
    } finally {
      setSaving(false);
    }
  }

  function choose(next: Setting) {
    if (next === value) return;
    // Removing the person from something that can't be undone deserves
    // one plain-language "are you sure".
    if (next === "auto" && tool.side_effect === "destructive") {
      setConfirming(true);
      return;
    }
    void save(next);
  }

  const h = size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3 text-[13px]";

  return (
    <div className="flex flex-col gap-2">
      <span
        role="radiogroup"
        aria-label={`${label}: when may AI Employees use it?`}
        aria-busy={saving}
        className="inline-flex self-start rounded-[11px] border border-line bg-sunken p-[3px]"
        data-coach="policy-choice"
      >
        {PERMISSION_OPTIONS.map((option) => {
          const on = option.key === value;
          return (
            <button
              key={option.key}
              type="button"
              role="radio"
              aria-checked={on}
              title={option.hint}
              disabled={disabled || saving}
              onClick={() => choose(option.key)}
              className={`seg-btn ${h} whitespace-nowrap rounded-lg transition-[background-color,color,box-shadow] duration-200 disabled:cursor-not-allowed ${
                on ? SELECTED[option.key] : "font-medium text-muted hover:text-ink"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </span>

      {confirming && (
        <div className="flex flex-col gap-2.5 rounded-xl border border-ask bg-ask-soft p-3 text-[13px] leading-snug" role="alert">
          <span className="flex gap-2">
            <Icon name="warn" size={16} className="mt-0.5 shrink-0 text-ask-text" />
            <span>
              AI Employees will <b>{toolAction(tool.name)}</b> without asking anyone, and it can't be undone. Allow it
              anyway?
            </span>
          </span>
          <span className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-sm btn-ok" onClick={() => void save("auto")}>
              Yes, always allow
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setConfirming(false)}>
              Keep asking me
            </button>
          </span>
        </div>
      )}
    </div>
  );
}

import type { AgentSchedule } from "../../lib/api";
import { defaultSchedule, describeSchedule, localZone } from "../../lib/agents";
import { Select, Switch } from "../ui";

const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const ZONES = [
  "Asia/Kolkata",
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

/**
 * When an agent runs on its own: how often, at what time, in which time
 * zone. Off means it only works when someone chats with it.
 */
export default function ScheduleEditor({
  value,
  onChange,
  disabled,
}: {
  value: AgentSchedule | null;
  onChange: (next: AgentSchedule | null) => void;
  disabled?: boolean;
}) {
  const zones = value && !ZONES.includes(value.timezone) ? [value.timezone, ...ZONES] : [localZone(), ...ZONES.filter((z) => z !== localZone())];

  function set(patch: Partial<AgentSchedule>) {
    if (!value) return;
    const next = { ...value, ...patch };
    if (next.frequency === "weekly" && next.days.length === 0) next.days = [0];
    onChange(next);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Switch
          checked={value !== null}
          label="Run on its own"
          disabled={disabled}
          onChange={(on) => onChange(on ? defaultSchedule() : null)}
        />
        <span className="text-[14px] font-medium">Run on its own</span>
        {value === null && <span className="text-[13px] text-dim">Off: it only works when you chat with it.</span>}
      </div>

      {value && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Select
              label="How often"
              value={value.frequency}
              onChange={(v) => set({ frequency: v as AgentSchedule["frequency"] })}
              options={[
                { value: "daily", label: "Every day" },
                { value: "weekdays", label: "Weekdays" },
                { value: "weekly", label: "Chosen days" },
              ]}
            />
            <label className="flex flex-col gap-2">
              <span className="label">At what time</span>
              <input
                type="time"
                className="field"
                value={value.time}
                disabled={disabled}
                onChange={(e) => e.target.value && set({ time: e.target.value })}
              />
            </label>
            <Select
              label="Time zone"
              value={value.timezone}
              onChange={(v) => set({ timezone: v })}
              options={zones.map((z) => ({ value: z, label: z }))}
            />
          </div>

          {value.frequency === "weekly" && (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Days of the week">
              {DAY_SHORT.map((label, day) => {
                const on = value.days.includes(day);
                return (
                  <button
                    key={label}
                    type="button"
                    aria-pressed={on}
                    disabled={disabled}
                    className={`agent-tool ${on ? "is-on" : ""}`}
                    onClick={() => set({ days: on ? value.days.filter((d) => d !== day) : [...value.days, day].sort() })}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}

          <p className="text-[13.5px] font-medium text-accent-text">{describeSchedule(value)}</p>
        </>
      )}
    </div>
  );
}

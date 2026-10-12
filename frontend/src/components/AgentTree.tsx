import { useMemo, useState } from "react";
import type { RunEvent } from "../lib/api";
import { Icon } from "./icons";
import { Avatar, Chip, type Tone } from "./ui";

/**
 * The delegation tree for one run, built from its event log.
 *
 * A manager asks up to three specialists (depth 1: they cannot pass the
 * work on again), then checks and combines what comes back. Each hand-off
 * is a `delegate_to_specialist` tool call in the log, so the tree is
 * exactly what happened, not a separate model of it.
 */

const DELEGATE = "delegate_to_specialist";

type BranchState = "working" | "done" | "failed" | "ask" | "blocked" | "stopped";

export interface Branch {
  name: string;
  task: string | null;
  state: BranchState;
  detail: string | null;
  placeholder: boolean;
}

const STATE: Record<BranchState, { tone: Tone; label: string; stroke: string; soft: string }> = {
  working: { tone: "run", label: "working", stroke: "var(--run)", soft: "var(--run-soft)" },
  done: { tone: "ok", label: "returned", stroke: "var(--ok)", soft: "var(--ok-soft)" },
  failed: { tone: "bad", label: "could not finish", stroke: "var(--bad)", soft: "var(--bad-soft)" },
  ask: { tone: "ask", label: "needs approval", stroke: "var(--ask)", soft: "var(--ask-soft)" },
  blocked: { tone: "bad", label: "blocked", stroke: "var(--bad)", soft: "var(--bad-soft)" },
  stopped: { tone: "mute", label: "stopped", stroke: "var(--line2)", soft: "var(--raised)" },
};

export function buildBranches(events: RunEvent[], runEnded: boolean): Branch[] {
  const branches: Branch[] = [];

  for (const event of events) {
    if (event.tool !== DELEGATE) continue;

    if (event.type === "approval_requested") {
      // The arguments arrive with the tool call after approval, so hold
      // a place for the specialist until then.
      branches.push({ name: "Awaiting approval", task: null, state: "ask", detail: null, placeholder: true });
    } else if (event.type === "tool_blocked") {
      const index = branches.findIndex((b) => b.placeholder);
      const blocked: Branch = {
        name: "Blocked by policy",
        task: null,
        state: "blocked",
        detail: typeof event.reason === "string" ? event.reason : null,
        placeholder: false,
      };
      if (index >= 0) branches[index] = blocked;
      else branches.push(blocked);
    } else if (event.type === "tool_call") {
      const args = (event.arguments ?? {}) as { specialist_name?: string; task?: string };
      const branch: Branch = {
        name: args.specialist_name || "Specialist",
        task: args.task ?? null,
        state: "working",
        detail: null,
        placeholder: false,
      };
      const index = branches.findIndex((b) => b.placeholder);
      if (index >= 0) branches[index] = branch;
      else branches.push(branch);
    } else if (event.type === "tool_result") {
      // Results come back in call order, including after a parallel batch.
      const branch = branches.find((b) => b.state === "working");
      if (branch) {
        branch.state = event.ok ? "done" : "failed";
        branch.detail = event.ok ? null : String(event.error_class ?? "error");
      }
    }
  }

  if (runEnded) {
    for (const branch of branches) {
      if (branch.state === "working" || branch.state === "ask") branch.state = "stopped";
    }
  }
  return branches;
}

/** One SVG for the fan: lines from a single point to each child, or back. */
function Fan({ branches, direction }: { branches: Branch[]; direction: "out" | "in" }) {
  const n = branches.length;
  return (
    <svg className="h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {branches.map((branch, i) => {
        const y = ((i + 0.5) / n) * 100;
        const style = STATE[branch.state];
        const live = branch.state === "working" || branch.state === "ask";
        const settled = direction === "in" && branch.state !== "done";
        const d = direction === "out" ? `M0 50 H50 V${y} H100` : `M0 ${y} H50 V50 H100`;
        return (
          <path
            key={i}
            d={d}
            fill="none"
            stroke={settled ? "var(--line2)" : style.stroke}
            strokeWidth={2}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            strokeDasharray={settled ? "4 6" : undefined}
            className={live && direction === "out" ? "flow-line" : undefined}
          />
        );
      })}
    </svg>
  );
}

function Connector({ live = false }: { live?: boolean }) {
  return (
    <svg className="h-2 w-full self-center overflow-visible" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
      <path
        d="M0 4 H100"
        stroke="var(--accent)"
        strokeWidth={2}
        vectorEffect="non-scaling-stroke"
        className={live ? "flow-line" : undefined}
      />
    </svg>
  );
}

export default function AgentTree({
  events,
  managerName,
  taskTitle,
  runStatus,
}: {
  events: RunEvent[];
  managerName: string;
  taskTitle: string;
  runStatus: string | null;
}) {
  const ended = !!runStatus && !["running", "queued", "awaiting_approval"].includes(runStatus);
  const branches = useMemo(() => buildBranches(events, ended), [events, ended]);
  const [selected, setSelected] = useState(0);
  const chosen = branches[Math.min(selected, branches.length - 1)];
  const returned = branches.filter((b) => b.state === "done").length;
  const completed = runStatus === "completed";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-muted">
        <span className="font-medium text-ink">
          {branches.length ? "Select a specialist to see what it was asked" : `${managerName} worked alone on this run`}
        </span>
        <span className="ml-auto flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-run" />working</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-ok" />returned</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-ask" />needs a person</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-[2px] bg-bad" />failed</span>
      </div>

      <div className="dot-grid overflow-x-auto rounded-2xl border border-line">
        <div
          className="grid min-w-[780px] items-stretch p-6"
          style={{
            gridTemplateColumns: branches.length
              ? "150px 40px 180px 56px minmax(210px,1fr) 56px 170px"
              : "150px 40px 180px 40px 170px",
            minHeight: Math.max(220, branches.length * 112 + 48),
          }}
        >
          <div className="pop flex flex-col justify-center gap-1 self-center rounded-[14px] border border-line2 bg-panel px-3.5 py-3">
            <span className="font-mono text-[11px] tracking-[0.1em] text-muted">TASK</span>
            <span className="line-clamp-3 text-sm font-semibold">{taskTitle}</span>
          </div>
          <Connector />
          <div
            className="pop flex items-center gap-3 self-center rounded-2xl px-3.5 py-3.5"
            style={{
              background: "var(--accent-soft)",
              border: "1.5px solid var(--accent)",
              boxShadow: "0 20px 50px -24px var(--glow)",
              animationDelay: ".1s",
            }}
          >
            <Avatar name={managerName} size={40} rounded="rounded-xl" />
            <span className="min-w-0">
              <b className="block truncate text-[15px] font-semibold">{managerName}</b>
              <span className="text-sm text-accent-text">{branches.length ? "manager" : "worked alone"}</span>
            </span>
          </div>

          {branches.length > 0 && (
            <>
              <Fan branches={branches} direction="out" />
              <div className="flex flex-col">
                {branches.map((branch, i) => {
                  const style = STATE[branch.state];
                  const isSelected = chosen === branch;
                  return (
                    <div key={i} className="flex flex-1 items-center py-2">
                      <button
                        type="button"
                        onClick={() => setSelected(i)}
                        aria-pressed={isSelected}
                        className={`pop flex w-full items-center gap-3 rounded-2xl px-3.5 py-3 text-left transition-transform hover:-translate-y-0.5 ${
                          branch.state === "working" ? "live-run" : branch.state === "ask" ? "live-ask" : ""
                        }`}
                        style={{
                          background: style.soft,
                          border: `1.5px solid ${style.stroke}`,
                          outline: isSelected ? "2px solid var(--accent)" : "2px solid transparent",
                          outlineOffset: 4,
                          animationDelay: `${0.2 + i * 0.1}s`,
                        }}
                      >
                        <Avatar name={branch.placeholder ? "?" : branch.name} size={36} rounded="rounded-[11px]" muted={branch.placeholder} />
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <b className="truncate text-[15px] font-semibold">{branch.name}</b>
                          <span className="font-mono text-xs" style={{ color: `var(--${style.tone === "mute" ? "muted" : style.tone + "-text"})` }}>
                            {style.label}
                            {branch.state === "working" && <span className="caret">_</span>}
                          </span>
                        </span>
                      </button>
                    </div>
                  );
                })}
              </div>
              <Fan branches={branches} direction="in" />
            </>
          )}
          {branches.length === 0 && <Connector live={!ended} />}

          <div
            className="pop flex items-center gap-3 self-center rounded-2xl px-3.5 py-3.5"
            style={{
              background: completed ? "var(--ok-soft)" : "var(--panel)",
              border: completed ? "1.5px solid var(--ok)" : "1.5px dashed var(--line2)",
              animationDelay: ".5s",
            }}
          >
            <span
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
              style={{ background: completed ? "var(--ok)" : "var(--raised)", color: completed ? "var(--on-ok)" : "var(--muted)" }}
            >
              <Icon name={completed ? "check" : "sparkle"} size={18} strokeWidth={2.2} />
            </span>
            <span className="min-w-0">
              <b className="block text-[15px] font-semibold">Result</b>
              <span className="font-mono text-xs text-muted">
                {completed
                  ? "combined"
                  : branches.length
                    ? `${returned} of ${branches.length} back`
                    : ended
                      ? humaniseStatus(runStatus)
                      : "in progress"}
              </span>
            </span>
          </div>
        </div>
      </div>

      {chosen && (
        <div className="card rise flex flex-col gap-3 p-5" key={selected}>
          <div className="flex flex-wrap items-center gap-3">
            <Avatar name={chosen.placeholder ? "?" : chosen.name} size={36} rounded="rounded-[11px]" muted={chosen.placeholder} />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{chosen.name}</div>
              <div className="text-[13px] text-muted">Specialist · cannot delegate further</div>
            </div>
            <Chip tone={STATE[chosen.state].tone}>{STATE[chosen.state].label}</Chip>
          </div>
          {chosen.task ? (
            <p className="rounded-[10px] bg-accent-soft px-3 py-2.5 text-sm leading-relaxed">
              <span className="font-medium">{managerName} asked:</span> “{chosen.task}”
            </p>
          ) : (
            <p className="text-sm text-muted">
              {chosen.state === "ask"
                ? "The hand-off is waiting for someone to approve it. The specialist is named once it is approved."
                : "No task text was recorded for this hand-off."}
            </p>
          )}
          {chosen.detail && <p className="font-mono text-xs text-bad-text">{chosen.detail}</p>}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { icon: "tree" as const, title: "Depth limit 1", text: "Specialists cannot delegate. Errors multiply with each level." },
          { icon: "members" as const, title: "At most 3 specialists", text: "Side by side, never in a chain." },
          { icon: "check" as const, title: "Manager checks", text: `${managerName} checks each result before using it.` },
          { icon: "tasks" as const, title: "Every hand-off logged", text: "Each one is a step in this run's timeline." },
        ].map((rule) => (
          <div key={rule.title} className="flex gap-3 rounded-2xl border border-line bg-sunken p-4">
            <Icon name={rule.icon} size={20} className="text-accent-text" />
            <div>
              <div className="text-sm font-medium">{rule.title}</div>
              <div className="text-[13px] leading-normal text-muted">{rule.text}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function humaniseStatus(status: string | null): string {
  return (status ?? "").replace(/_/g, " ");
}

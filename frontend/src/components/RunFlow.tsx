import { useEffect, useMemo, useRef, useState } from "react";
import type { RunEvent } from "../lib/api";
import { Icon, type IconName } from "./icons";
import {
  SERVICE_NAME,
  ServiceMark,
  VendorChip,
  serviceForTool,
  vendorFor,
  type ServiceKey,
} from "./ServiceMark";

/**
 * The journey of one run, end to end.
 *
 * The Timeline answers "what happened, in order". This answers a
 * different question people actually ask first: *where does my work
 * go?* So it is drawn as a route — you hand work to the AI Employee,
 * it asks the model what to do, the model names a tool, we go out to
 * Gmail or Drive or the database, the answer comes back, and round
 * again until there is something to say.
 *
 * Built from the same event log as everything else, so it is what
 * happened rather than a second story about it. A live run grows a
 * stage at a time; a finished one replays on open, because watching
 * the route draw itself is most of what makes the loop legible.
 */

type StageKind = "trigger" | "think" | "model" | "tool" | "wait" | "answer" | "stopped";

interface Stage {
  kind: StageKind;
  /** The heading: "Ravi thinks", "Gmail", "Groq". */
  title: string;
  /** One line under it, in plain words. */
  detail: string | null;
  icon: IconName;
  /** The service's own logo, where it has one we can draw. */
  service?: ServiceKey;
  /** A model vendor with no logo of its own: a lettermark instead. */
  vendor?: { label: string; color: string };
  /** Where it sits: inside our platform, or out at somebody else's. */
  away: boolean;
  state: "done" | "working" | "failed" | "ask";
  /** Tokens, milliseconds — only where they mean something. */
  meta: string | null;
}

/** Which outside service a tool actually reaches. */
const DESTINATIONS: { match: RegExp; name: string; icon: IconName; away: boolean }[] = [
  { match: /^gmail_|^outlook_/, name: "Email", icon: "mail", away: true },
  { match: /calendar/, name: "Calendar", icon: "calendar", away: true },
  { match: /drive|onedrive/, name: "Files", icon: "folder", away: true },
  { match: /^run_query$|^list_tables$|^describe_table$/, name: "Your database", icon: "database", away: true },
  { match: /^get_webpage$/, name: "The web", icon: "link", away: true },
  { match: /^recall$|^remember$/, name: "Company memory", icon: "memory", away: false },
  { match: /^delegate_to_specialist$/, name: "A specialist", icon: "employees", away: false },
];

function destinationFor(tool: string) {
  const hit = DESTINATIONS.find((d) => d.match.test(tool));
  return hit ?? { name: "A tool", icon: "terminal" as IconName, away: true };
}

/** "gmail_search" → "searches your email" */
const VERBS: Record<string, string> = {
  gmail_search: "searches your inbox",
  gmail_read: "opens a message",
  gmail_create_draft: "writes a draft",
  gmail_send: "sends a message",
  outlook_search: "searches your inbox",
  outlook_read: "opens a message",
  outlook_create_draft: "writes a draft",
  outlook_send: "sends a message",
  google_calendar_list: "checks the calendar",
  google_calendar_create: "adds an event",
  google_drive_search: "looks for a file",
  google_drive_read: "reads a file",
  run_query: "asks the database a question",
  list_tables: "looks at what tables exist",
  describe_table: "checks a table's columns",
  get_webpage: "reads a page",
  recall: "remembers what the company knows",
  remember: "writes something down to keep",
  delegate_to_specialist: "hands part of the job to a specialist",
};

export function buildStages(
  events: RunEvent[],
  employee: string,
  runStatus: string | null,
): Stage[] {
  const stages: Stage[] = [
    {
      kind: "trigger",
      title: "You assign the work",
      detail: `${employee} picks it up`,
      icon: "tasks",
      away: false,
      state: "done",
      meta: null,
    },
  ];

  const str = (v: unknown) => (typeof v === "string" ? v : null);

  for (const event of events) {
    switch (event.type) {
      case "thinking":
        stages.push({
          kind: "think",
          title: `${employee} works out the next step`,
          detail: null,
          icon: "sparkle",
          away: false,
          state: "working",
          meta: typeof event.step === "number" ? `step ${event.step}` : null,
        });
        break;

      case "llm_call": {
        const tokens =
          typeof event.prompt_tokens === "number" && typeof event.output_tokens === "number"
            ? `${event.prompt_tokens + event.output_tokens} tokens`
            : null;
        const ms = typeof event.latency_ms === "number" ? `${event.latency_ms} ms` : null;
        const model = str(event.model) ?? "The AI model";
        const vendor = vendorFor(model);
        stages.push({
          kind: "model",
          title: model,
          detail: "decides what to do next",
          icon: "chat",
          service: vendor?.label === "Gemini" ? "gemini" : undefined,
          vendor: vendor && vendor.label !== "Gemini" ? vendor : undefined,
          away: true,
          state: "done",
          meta: [tokens, ms].filter(Boolean).join(" · ") || null,
        });
        // The thinking stage that led here is finished now.
        const think = [...stages].reverse().find((s) => s.kind === "think" && s.state === "working");
        if (think) think.state = "done";
        break;
      }

      case "tool_call": {
        const tool = str(event.tool) ?? "a tool";
        const dest = destinationFor(tool);
        const service = serviceForTool(tool);
        stages.push({
          kind: "tool",
          // Named for the service itself when we know it: "Gmail" is
          // more use than "Email" when you are working out where your
          // data actually went.
          title: service ? SERVICE_NAME[service] : dest.name,
          detail: VERBS[tool] ?? tool.replace(/_/g, " "),
          icon: dest.icon,
          service: service ?? undefined,
          away: dest.away,
          state: "working",
          meta: null,
        });
        break;
      }

      case "tool_result": {
        const open = [...stages].reverse().find((s) => s.kind === "tool" && s.state === "working");
        if (open) {
          open.state = event.ok === false ? "failed" : "done";
          if (event.ok === false && str(event.error_class)) {
            open.detail = `could not do it (${str(event.error_class)})`;
          }
        }
        break;
      }

      case "approval_requested": {
        const tool = str(event.tool) ?? "something";
        stages.push({
          kind: "wait",
          title: "Waiting for you",
          detail: `${VERBS[tool] ?? tool.replace(/_/g, " ")} — needs a person to say yes`,
          icon: "approvals",
          away: false,
          state: "ask",
          meta: null,
        });
        break;
      }

      case "approval_granted": {
        const wait = [...stages].reverse().find((s) => s.kind === "wait");
        if (wait) {
          wait.state = "done";
          wait.title = "You approved it";
          wait.detail = "the run picked up where it stopped";
        }
        break;
      }

      case "run_finished":
        stages.push({
          kind: "answer",
          title: "You get the answer",
          detail: `${employee} writes up what it found`,
          icon: "check",
          away: false,
          state: "done",
          meta: null,
        });
        break;

      case "run_stopped":
        stages.push({
          kind: "stopped",
          title: "Stopped",
          detail: str(event.cause)?.replace(/_/g, " ") ?? null,
          icon: "stop",
          away: false,
          state: "failed",
          meta: null,
        });
        break;

      case "provider_error":
        stages.push({
          kind: "stopped",
          title: "The AI service could not answer",
          detail: str(event.error) ?? null,
          icon: "warn",
          away: true,
          state: "failed",
          meta: null,
        });
        break;
    }
  }

  // A run still going has one stage genuinely in flight; anything left
  // marked "working" on a finished run never completed.
  const ended = !!runStatus && !["running", "queued", "awaiting_approval"].includes(runStatus);
  if (ended) {
    for (const s of stages) if (s.state === "working") s.state = "failed";
  }

  return stages;
}

const TONE: Record<Stage["state"], { stroke: string; soft: string; text: string }> = {
  done: { stroke: "var(--ok)", soft: "var(--ok-soft)", text: "var(--ok-text)" },
  working: { stroke: "var(--run)", soft: "var(--run-soft)", text: "var(--run-text)" },
  failed: { stroke: "var(--bad)", soft: "var(--bad-soft)", text: "var(--bad-text)" },
  ask: { stroke: "var(--ask)", soft: "var(--ask-soft)", text: "var(--ask-text)" },
};

export default function RunFlow({
  events,
  employee,
  runStatus,
}: {
  events: RunEvent[];
  employee: string;
  runStatus: string | null;
}) {
  const stages = useMemo(
    () => buildStages(events, employee, runStatus),
    [events, employee, runStatus],
  );

  // Replay on open: reveal one stage at a time so the route draws
  // itself. A live run has usually already revealed everything by the
  // time the next event lands, so this costs nothing there.
  const [shown, setShown] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (shown >= stages.length) return;
    timer.current = window.setTimeout(() => setShown((n) => n + 1), shown === 0 ? 120 : 260);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [shown, stages.length]);

  // A run that grows past what we have drawn should keep drawing, but a
  // reopened run should not start from zero again mid-stream.
  useEffect(() => {
    if (stages.length < shown) setShown(stages.length);
  }, [stages.length, shown]);

  const visible = stages.slice(0, shown);
  const live = !runStatus || ["running", "queued", "awaiting_approval"].includes(runStatus);

  return (
    <div className="flex flex-col">
      <p className="mb-4 flex items-start gap-2 text-[13px] leading-normal text-muted">
        <Icon name="info" size={15} className="mt-0.5 shrink-0 text-accent-text" />
        Where your work goes. Everything marked{" "}
        <b className="font-medium text-ink">away</b> leaves this platform — that is the part worth
        reading before you give an AI Employee more tools.
      </p>

      <ol className="flex flex-col">
        {visible.map((stage, i) => {
          const tone = TONE[stage.state];
          const last = i === stages.length - 1;
          return (
            <li key={i} className="flow-step" style={{ animationDelay: `${Math.min(i, 12) * 0.04}s` }}>
              <div className="flex gap-3.5">
                {/* rail: the dot, and the line down to the next stage */}
                <div className="flex w-9 shrink-0 flex-col items-center">
                  <span
                    className="relative flex h-9 w-9 items-center justify-center rounded-full border-2"
                    style={{
                      borderColor: tone.stroke,
                      background: stage.service || stage.vendor ? "var(--panel)" : tone.soft,
                      color: tone.text,
                    }}
                  >
                    {stage.service ? (
                      <ServiceMark service={stage.service} size={18} />
                    ) : stage.vendor ? (
                      <VendorChip label={stage.vendor.label} color={stage.vendor.color} size={18} />
                    ) : (
                      <Icon name={stage.icon} size={16} />
                    )}
                    {stage.state === "working" && (
                      <span
                        className="absolute inset-0 rounded-full border-2"
                        style={{ borderColor: tone.stroke, animation: "flow-ping 1.4s ease-out infinite" }}
                      />
                    )}
                  </span>
                  {!last && (
                    <span className="relative my-1 w-0.5 flex-1 rounded" style={{ background: "var(--line2)" }}>
                      {/* a pulse travelling to the next stage, only
                          while this one is the live edge */}
                      {stage.state === "working" && (
                        <span
                          className="absolute left-1/2 h-2.5 w-2.5 -translate-x-1/2 rounded-full"
                          style={{
                            background: tone.stroke,
                            boxShadow: `0 0 10px ${tone.stroke}`,
                            animation: "flow-travel 1.1s ease-in-out infinite",
                          }}
                        />
                      )}
                    </span>
                  )}
                </div>

                <div className={`min-w-0 flex-1 ${last ? "pb-0" : "pb-5"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{stage.title}</span>
                    {stage.away && (
                      <span className="rounded-full border border-line2 px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
                        away
                      </span>
                    )}
                    {stage.meta && (
                      <span className="font-mono text-[11px] text-dim">{stage.meta}</span>
                    )}
                  </div>
                  {stage.detail && (
                    <div className="mt-0.5 text-[13px] text-muted">{stage.detail}</div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      {live && shown >= stages.length && (
        <div className="ml-[18px] flex items-center gap-2.5 border-l-2 border-dashed border-line2 py-3 pl-[22px] text-[13px] text-muted">
          <Icon name="spinner" size={14} className="spin" />
          still going…
        </div>
      )}
    </div>
  );
}

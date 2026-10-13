import { Link } from "react-router-dom";
import { Icon } from "./icons";

/**
 * First-time setup, as a checklist on the Tasks page.
 *
 * Without it a new admin can assign a task before any AI key exists and
 * watch it fail. Each step links to the page that does it, and the
 * guide disappears once the first task has been assigned.
 */

export type SetupStatus = {
  ai_connected: boolean;
  apps_connected: boolean;
  employees: number;
  employees_active: number;
  tasks: number;
};

export function setupComplete(s: SetupStatus): boolean {
  return s.ai_connected && s.employees_active > 0 && s.tasks > 0;
}

export default function SetupGuide({ status, isAdmin }: { status: SetupStatus; isAdmin: boolean }) {
  if (setupComplete(status)) return null;

  if (!isAdmin) {
    if (status.ai_connected) return null;
    return (
      <div className="card rise flex items-start gap-3 border-ask/40 p-4 text-sm" role="status">
        <Icon name="info" size={18} className="mt-0.5 shrink-0 text-ask-text" />
        <p className="leading-relaxed text-muted">
          <span className="font-medium text-ink">Not ready yet.</span> An admin needs to connect an AI key before
          tasks can run. Ask them to open <span className="text-ink">Providers</span>.
        </p>
      </div>
    );
  }

  const steps = [
    {
      done: status.ai_connected,
      title: "Connect an AI key",
      hint: "Free from Google Gemini or Groq. It powers every AI Employee.",
      to: "/providers",
      action: "Add key",
    },
    {
      done: status.apps_connected,
      title: "Connect Gmail or Outlook",
      hint: "Lets AI Employees read email, calendars and files.",
      to: "/connections",
      action: "Connect",
      optional: true,
    },
    {
      done: status.employees_active > 0,
      title: status.employees > 0 ? "Switch on an AI Employee" : "Create an AI Employee",
      hint: "Start from a template; it takes a minute.",
      to: "/employees",
      action: status.employees > 0 ? "Switch on" : "Create",
    },
    {
      done: status.tasks > 0,
      title: "Assign the first task",
      hint: "Type or speak it in the box below.",
    },
  ];
  const required = steps.filter((s) => !s.optional);
  const doneCount = required.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done && !s.optional) ?? steps.find((s) => !s.done);

  return (
    <section className="card rise flex flex-col gap-4 p-5" aria-label="Get started">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex-1 font-display text-[17px] font-semibold">Get started</h2>
        <span className="text-[13px] text-muted">
          {doneCount} of {required.length} done
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden="true">
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${(doneCount / required.length) * 100}%` }} />
      </div>
      <ol className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, i) => {
          const isNext = step === next;
          return (
            <li
              key={step.title}
              className={`flex flex-col gap-2 rounded-xl border p-3.5 ${isNext ? "border-accent-line bg-accent-soft" : "border-line bg-raised"}`}
            >
              <div className="flex items-center gap-2.5">
                <span
                  className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-[13px] font-semibold ${
                    step.done ? "bg-ok text-ok-on" : "border border-line2 text-muted"
                  }`}
                  aria-hidden="true"
                >
                  {step.done ? <Icon name="check" size={14} strokeWidth={2.6} /> : i + 1}
                </span>
                <span className={`text-sm font-medium ${step.done ? "text-muted line-through decoration-1" : "text-ink"}`}>
                  {step.title}
                  {step.optional && <span className="ml-1.5 text-xs font-normal text-dim">optional</span>}
                </span>
                <span className="sr-only">{step.done ? "(done)" : "(to do)"}</span>
              </div>
              <p className="text-[13px] leading-snug text-muted">{step.hint}</p>
              {!step.done && step.to && (
                <Link to={step.to} className={`btn btn-sm mt-auto self-start ${isNext ? "btn-primary" : "btn-ghost"}`}>
                  {step.action}
                  <Icon name="arrow" size={14} strokeWidth={2.2} />
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon } from "./icons";
import { useSetup } from "../lib/setup";

/**
 * A slim bar above every page until first-time setup is done.
 *
 * It only ever shows the next step. Steps tick on the server from real
 * events, so nothing here asks anyone to click "done", and it goes away
 * for good once the last step is seen.
 */
const STEPS: Record<string, { label: string; to: string; cta: string }> = {
  pick_ai: { label: "Pick an AI", to: "/providers", cta: "Choose one" },
  add_key: { label: "Add its key", to: "/providers", cta: "Add the key" },
  connect_app: { label: "Connect an app", to: "/connections", cta: "Connect one" },
  first_agent: { label: "Make or run an agent", to: "/agents", cta: "Make one" },
};

export default function SetupBar() {
  const { state, refresh } = useSetup();
  const { pathname } = useLocation();

  // A step usually completes on another screen, so look again on each page change.
  useEffect(() => {
    void refresh();
  }, [pathname, refresh]);

  if (!state || state.complete || !state.next_step) return null;
  const next = STEPS[state.next_step];
  if (!next) return null;

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-4 py-2 text-[13px]"
    >
      <ol className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {state.steps.map((id, i) => {
          const done = state.done.includes(id);
          const current = id === state.next_step;
          return (
            <li
              key={id}
              aria-current={current ? "step" : undefined}
              className={`flex items-center gap-1.5 ${done ? "text-ok-text" : current ? "font-medium text-ink" : "text-dim"}`}
            >
              <span
                className={`grid h-5 w-5 place-items-center rounded-full text-[11px] ${
                  done ? "bg-ok-soft" : current ? "bg-accent text-on-accent" : "bg-raised"
                }`}
              >
                {done ? <Icon name="check" size={12} strokeWidth={3} /> : i + 1}
              </span>
              {STEPS[id]?.label ?? id}
            </li>
          );
        })}
      </ol>
      {pathname !== next.to && (
        <Link to={next.to} className="ml-auto flex items-center gap-1 font-medium text-accent-text hover:underline">
          {next.cta}
          <Icon name="arrow" size={14} />
        </Link>
      )}
    </div>
  );
}

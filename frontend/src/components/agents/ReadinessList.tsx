import { Link } from "react-router-dom";
import type { Readiness } from "../../lib/api";
import { fixTarget } from "../../lib/agents";
import { Icon } from "../icons";

/**
 * The chain behind an agent, one link per line: is the app connected,
 * allowed, granted, and permitted to run. A broken link says what is
 * wrong and offers the way to fix it.
 */
export default function ReadinessList({
  readiness,
  loading,
  onRecheck,
}: {
  readiness: Readiness | null;
  loading: boolean;
  onRecheck?: () => void;
}) {
  if (!readiness) {
    return (
      <p className="flex items-center gap-2 text-[13px] text-dim" aria-live="polite">
        <Icon name="spinner" size={14} className="animate-spin" /> Checking what it needs…
      </p>
    );
  }
  if (readiness.checks.length === 0) {
    return <p className="text-[13px] text-dim">It uses no connected apps, so there is nothing to check.</p>;
  }
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      <ul className="flex flex-col gap-1.5">
        {readiness.checks.map((c, i) => {
          const fix = c.ok ? null : fixTarget(c.fix);
          return (
            <li
              key={`${c.title}-${i}`}
              className={`flex items-start gap-2.5 rounded-xl border px-3 py-2 text-[13.5px] ${
                c.ok ? "border-line bg-raised" : "border-bad/30 bg-bad-soft"
              }`}
            >
              <Icon
                name={c.ok ? "check" : "warn"}
                size={15}
                className={`mt-0.5 shrink-0 ${c.ok ? "text-ok-text" : "text-bad-text"}`}
              />
              <div className="min-w-0 flex-1">
                <b className="block font-semibold">{c.title}</b>
                <span className={c.ok ? "text-dim" : "text-bad-text"}>{c.detail}</span>
              </div>
              {fix && (
                <Link to={fix.to} className="btn btn-sm btn-ghost shrink-0" target="_blank" rel="noreferrer">
                  {fix.label}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex items-center gap-3 text-[12.5px] text-dim">
        {loading ? "Checking again…" : readiness.ok ? "Everything it needs is ready." : "Fix the lines in red, then check again."}
        {onRecheck && !loading && (
          <button type="button" className="underline underline-offset-2" onClick={onRecheck}>
            Check again
          </button>
        )}
      </div>
    </div>
  );
}

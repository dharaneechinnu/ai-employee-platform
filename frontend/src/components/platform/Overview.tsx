import type { ReactNode } from "react";
import { Icon } from "../icons";
import type { OAuthApp, Overview, Provider } from "./api";

/**
 * The headline numbers at the top of "Overview and people": four cards,
 * then a quieter row. Counts only. On a phone the four cards sit two by
 * two and the quieter row is left out.
 */

const n = (value: number) => value.toLocaleString("en-GB");

function Bar({ parts }: { parts: { pct: number; colour: string }[] }) {
  return (
    <div aria-hidden="true" className="hidden h-1.5 overflow-hidden rounded-full bg-raised sm:flex">
      {parts.map((p, i) => (
        <div key={i} style={{ width: `${p.pct}%`, background: p.colour }} />
      ))}
    </div>
  );
}

function share(part: number, whole: number) {
  return whole > 0 ? (part / whole) * 100 : 0;
}

function Headline({ label, phoneLabel, value, bar, children }: { label: string; phoneLabel?: string; value: number; bar?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-line bg-panel p-3 sm:gap-2.5 sm:rounded-[14px] sm:p-[18px]">
      <div className="text-xs font-medium text-muted sm:text-[13px]">
        {phoneLabel ? (
          <>
            <span className="sm:hidden">{phoneLabel}</span>
            <span className="hidden sm:inline">{label}</span>
          </>
        ) : (
          label
        )}
      </div>
      <div className="text-2xl font-semibold leading-tight tracking-[-0.02em] sm:text-[32px] sm:leading-none">{n(value)}</div>
      {bar ?? <div className="hidden h-1.5 sm:block" />}
      <div className="text-xs text-muted sm:text-[12.5px]">{children}</div>
    </div>
  );
}

/** `expiringToday` is worked out from the people list, in the viewer's own day. */
export function HeadlineCards({ data, expiringToday }: { data: Overview; expiringToday: number }) {
  const joined = data.joined_this_week_self + data.joined_this_week_invited;
  return (
    <section aria-label="Headline numbers" className="grid grid-cols-2 gap-2.5 sm:gap-3 sm:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      <Headline
        label="People"
        value={data.people_total}
        bar={<Bar parts={[{ pct: share(data.people_active, data.people_total), colour: "var(--ok)" }, { pct: share(data.people_suspended, data.people_total), colour: "var(--bad)" }]} />}
      >
        <span className="font-semibold text-ok-text">{n(data.people_active)} active</span> ·{" "}
        <span className="font-semibold text-bad-text">
          {n(data.people_suspended)} <span className="sm:hidden">susp.</span>
          <span className="hidden sm:inline">suspended</span>
        </span>
      </Headline>
      <Headline
        label="Joined this week"
        value={joined}
        bar={<Bar parts={[{ pct: share(data.joined_this_week_self, joined), colour: "var(--accent)" }, { pct: share(data.joined_this_week_invited, joined), colour: "var(--accent-line)" }]} />}
      >
        {n(data.joined_this_week_self)} signed up · {n(data.joined_this_week_invited)} invited
      </Headline>
      <Headline label="Setup links waiting" value={data.setup_links_waiting}>
        {expiringToday > 0 ? (
          <span className="font-semibold text-ask-text">
            {n(expiringToday)} {expiringToday === 1 ? "expires" : "expire"} today
          </span>
        ) : data.setup_links_waiting > 0 ? (
          "None expire today"
        ) : (
          "Nobody is waiting"
        )}
      </Headline>
      <Headline
        label="AI keys connected"
        phoneLabel="AI keys"
        value={data.ai_keys_total}
        bar={<Bar parts={[{ pct: share(data.ai_keys_free, data.ai_keys_total), colour: "var(--ok)" }, { pct: share(data.ai_keys_paid, data.ai_keys_total), colour: "var(--run)" }]} />}
      >
        <span className="font-semibold text-ok-text">{n(data.ai_keys_free)} free</span> ·{" "}
        <span className="font-semibold text-run-text">{n(data.ai_keys_paid)} paid</span>
      </Headline>
    </section>
  );
}

function Quiet({ label, children, onOpen }: { label: string; children: ReactNode; onOpen?: () => void }) {
  const body = (
    <div className="min-w-0 text-left">
      <div className="text-[12.5px] text-muted">{label}</div>
      {children}
    </div>
  );
  const box = "flex items-center justify-between gap-2 rounded-xl border border-line bg-panel px-4 py-3.5 text-ink";
  return onOpen ? (
    <button type="button" onClick={onOpen} className={`${box} transition-colors hover:border-line2`}>
      {body}
      <Icon name="chevron" size={16} strokeWidth={2} className="text-dim" />
    </button>
  ) : (
    <div className={box}>{body}</div>
  );
}

export function ActivityRow({ data, providers, apps, onOpenSettings }: { data: Overview; providers: Provider[] | null; apps: OAuthApp[] | null; onOpenSettings: () => void }) {
  const ai = (providers ?? []).filter((p) => p.kind === "llm");
  const paused = ai.filter((p) => !p.enabled);
  return (
    <section aria-label="Activity" className="hidden gap-3 sm:grid sm:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      <Quiet label="Agents built">
        <div className="text-xl font-semibold">{n(data.agents_built)}</div>
      </Quiet>
      <Quiet label="Runs this week">
        <div className="text-xl font-semibold">{n(data.runs_this_week)}</div>
      </Quiet>
      <Quiet label="AI providers on" onOpen={onOpenSettings}>
        <div className="text-xl font-semibold">
          {providers ? `${ai.length - paused.length} of ${ai.length}` : "…"}
          {paused.length > 0 && (
            <span className="text-[12.5px] font-medium text-ask-text">
              {" "}
              · {paused.length === 1 ? `${paused[0].display_name} paused` : `${paused.length} paused`}
            </span>
          )}
        </div>
      </Quiet>
      <Quiet label="One-click sign-in" onOpen={onOpenSettings}>
        <div className="pt-[3px] text-[15px] font-semibold">
          {apps && apps.length > 0 && apps.every((app) => !app.client_id) && <span className="text-ask-text">None set up yet</span>}
          {(apps ?? []).some((app) => app.client_id) && (apps ?? []).map((app, i) => (
            <span key={app.provider}>
              {i > 0 && " · "}
              {app.configured ? (
                `${app.display_name.split(" ")[0]} on`
              ) : (
                <span className="text-ask-text">
                  {app.display_name.split(" ")[0]} {app.client_id ? "paused" : "not set up"}
                </span>
              )}
            </span>
          ))}
          {!apps && "…"}
        </div>
      </Quiet>
    </section>
  );
}

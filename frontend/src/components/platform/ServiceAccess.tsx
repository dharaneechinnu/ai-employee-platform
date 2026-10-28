import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { Switch, useToast } from "../ui";
import { ScreenTitle } from "./bits";
import { call, type AppAccess, type ServiceAccessRow } from "./api";
import { APP_NAME, SERVICE_HINT } from "./format";

/**
 * Settings: what everyone's agents may touch.
 *
 * Three checks must all say yes before an agent uses anything: this
 * screen (the outer limit for everyone), the person (only what they
 * agreed to when connecting) and the agent (only the tools it was
 * given). A person can still be set differently from their own panel.
 */

const STEPS = [
  { n: 1, title: "You, here.", text: "The limit for everyone.", bg: "var(--strip-bg)", fg: "var(--strip-text)" },
  { n: 2, title: "The person.", text: "Only what they agreed to when connecting.", bg: "var(--muted)", fg: "var(--panel)" },
  { n: 3, title: "The agent.", text: "Only the tools it was given. All three must say yes.", bg: "var(--dim)", fg: "var(--panel)" },
];

function group(rows: ServiceAccessRow[]) {
  const apps = new Map<string, Map<string, { name: string; read?: ServiceAccessRow; edit?: ServiceAccessRow }>>();
  for (const row of rows) {
    const services = apps.get(row.app) ?? new Map();
    apps.set(row.app, services);
    const entry = services.get(row.service) ?? { name: row.name };
    entry[row.level] = row;
    services.set(row.service, entry);
  }
  return apps;
}

export function ServiceAccess({ onOpenSignIn }: { onOpenSignIn: () => void }) {
  const toast = useToast();
  const [apps, setApps] = useState<AppAccess[] | null>(null);
  const [rows, setRows] = useState<ServiceAccessRow[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([call<AppAccess[]>("/app-access"), call<ServiceAccessRow[]>("/service-access")])
      .then(([a, r]) => {
        setApps(a);
        setRows(r);
      })
      .catch(() => toast("Could not load service access.", "bad"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function setApp(app: AppAccess, allowed: boolean) {
    setBusy(app.kind);
    try {
      setApps(await call<AppAccess[]>(`/app-access/${app.kind}`, { allowed }, "PUT"));
      toast(`${APP_NAME[app.kind] ?? app.display_name} turned ${allowed ? "on" : "off"} for everyone.`, allowed ? "ok" : "info");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function setService(row: ServiceAccessRow, allowed: boolean) {
    const key = `${row.service}:${row.level}`;
    setBusy(key);
    try {
      setRows(await call<ServiceAccessRow[]>(`/service-access/${row.service}/${row.level}`, { allowed }, "PUT"));
      setApps(await call<AppAccess[]>("/app-access"));
      toast(`${row.name} · ${row.level === "edit" ? "change" : "look"} turned ${allowed ? "on" : "off"} for everyone.`, allowed ? "ok" : "info");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(null);
    }
  }

  const byKind = new Map((apps ?? []).map((a) => [a.kind, a]));
  const grouped = group(rows ?? []);

  return (
    <div className="flex flex-col gap-7">
      <ScreenTitle title="Service access">
        What everyone's agents are allowed to touch. Each person still has to connect and agree themselves; this only sets the outer limit. To change it for one person, open them from People.
      </ScreenTitle>

      <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
        {STEPS.map((s) => (
          <div key={s.n} className="flex items-start gap-2.5 rounded-xl border border-line bg-panel px-3.5 py-3">
            <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold" style={{ background: s.bg, color: s.fg }}>
              {s.n}
            </span>
            <div className="text-[13px]">
              <strong className="font-semibold">{s.title}</strong> <span className="text-muted">{s.text}</span>
            </div>
          </div>
        ))}
      </div>

      <section aria-labelledby="apps-h" className="flex flex-col gap-3">
        <h2 id="apps-h" className="text-[19px] font-semibold">
          Apps people can connect
        </h2>
        <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(min(250px,100%),1fr))]">
          {!apps && <div className="skeleton h-[70px] rounded-xl" />}
          {(apps ?? []).map((a) => (
            <div key={a.kind} className="flex items-center justify-between gap-2.5 rounded-xl border border-line bg-panel p-3.5">
              <div className="min-w-0">
                <div className="font-semibold">{APP_NAME[a.kind] ?? a.display_name}</div>
                {a.platform_ready ? (
                  <div className="text-[12.5px] text-muted">
                    {a.people_connected.toLocaleString("en-GB")} {a.people_connected === 1 ? "person" : "people"} connected
                  </div>
                ) : (
                  <div className="text-[12.5px] text-ask-text">
                    Needs sign-in app.{" "}
                    <button type="button" onClick={onOpenSignIn} className="font-semibold underline">
                      Set up
                    </button>
                  </div>
                )}
              </div>
              <Switch checked={a.allowed} label={`${APP_NAME[a.kind] ?? a.display_name} allowed for everyone`} disabled={busy === a.kind} onChange={(next) => void setApp(a, next)} />
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="svc-h" className="flex flex-col gap-3">
        <div>
          <h2 id="svc-h" className="text-[19px] font-semibold">
            Parts of Google and Microsoft
          </h2>
          <p className="mt-1 text-[13.5px] text-muted">
            <strong className="font-semibold text-ink">Look</strong> lets agents read. <strong className="font-semibold text-ink">Change</strong> lets them send, edit or create, and still asks the person first when it's risky.
          </p>
        </div>
        <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(380px,100%),1fr))]">
          {!rows && <div className="skeleton h-64 rounded-2xl" />}
          {[...grouped.entries()].map(([app, services]) => {
            const access = byKind.get(app);
            const own = access?.people_with_own_settings ?? 0;
            return (
              <div key={app} className="overflow-hidden rounded-2xl border border-line bg-panel">
                <div className="grid grid-cols-[minmax(0,1fr)_72px_72px] items-center gap-2 border-b border-line px-4 py-3 sm:grid-cols-[minmax(0,1fr)_88px_88px] sm:px-[18px]" style={{ background: "var(--staff-head)" }}>
                  <h3 className="text-[15px] font-semibold">{APP_NAME[app] ?? app}</h3>
                  <span className="text-center text-xs font-semibold text-muted">Look</span>
                  <span className="text-center text-xs font-semibold text-muted">Change</span>
                </div>
                {access && !access.platform_ready && (
                  <div className="border-b border-line bg-ask-soft px-4 py-2.5 text-[12.5px] text-ask-text sm:px-[18px]">
                    {APP_NAME[app] ?? app} sign-in isn't set up, so nobody can use these yet. Your choices are saved for when it is.
                  </div>
                )}
                {[...services.entries()].map(([sid, svc]) => (
                  <div key={sid} className="grid grid-cols-[minmax(0,1fr)_72px_72px] items-center gap-2 border-b border-raised px-4 py-3 sm:grid-cols-[minmax(0,1fr)_88px_88px] sm:px-[18px]">
                    <div>
                      <div className="font-medium">{svc.name}</div>
                      <div className="text-xs text-muted">{SERVICE_HINT[sid] ?? ""}</div>
                    </div>
                    {(["read", "edit"] as const).map((level) => {
                      const row = svc[level];
                      return (
                        <div key={level} className="flex justify-center">
                          {row ? (
                            <Switch checked={row.allowed} label={`${svc.name}: ${level === "edit" ? "change" : "look"}`} disabled={busy === `${sid}:${level}`} onChange={(next) => void setService(row, next)} />
                          ) : (
                            <span className="text-xs text-dim">Look only</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
                <div className="px-4 py-2.5 text-[12.5px] text-muted sm:px-[18px]">
                  {own === 0 ? "Nobody has their own settings here." : `${own} ${own === 1 ? "person has" : "people have"} their own settings here.`}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

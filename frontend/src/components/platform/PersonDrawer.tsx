import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { Icon } from "../icons";
import { Spinner, useToast } from "../ui";
import { Pill, PersonTile, ThreeWay, YesNoChip, type Choice } from "./bits";
import { call, type AuditEntry, type ConnectionAccess, type Person, type PersonDetail, type PersonServiceRow, type Provider, type ServiceAccessRow } from "./api";
import { APP_NAME, auditLine, dayAndTime, firstName, joinedLabel, lastActive, nameOf, shortDate, staffName } from "./format";

/**
 * One person, in a panel that slides in from the right.
 *
 * Everything a Platform Admin may know about them: facts, counts, which
 * AI providers and apps are connected (yes or no), the access set just
 * for them, and what staff have done to the account. There is no section
 * for their chats, memory, tasks or keys, because no endpoint returns
 * them.
 */

interface OverrideRow {
  key: string;
  name: string;
  sub: string;
  choice: Choice;
  note: string | null;
  save: (allowed: boolean | null, note: string | null) => Promise<void>;
}

const FOLDED = 4;

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-panel px-3.5 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 font-semibold">{children}</dd>
    </div>
  );
}

function Override({ row, person }: { row: OverrideRow; person: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(row.note ?? "");

  useEffect(() => setNote(row.note ?? ""), [row.note]);

  async function choose(next: Choice, withNote: string | null = row.note) {
    setBusy(true);
    try {
      await row.save(next === "same" ? null : next === "allow", next === "same" ? null : withNote);
      toast(next === "same" ? `${row.name}: same as everyone again.` : `${row.name} ${next === "allow" ? "allowed" : "blocked"} for ${person}.`, next === "block" ? "info" : "ok");
      setEditing(false);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not change that.", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-raised px-3.5 py-3 last:border-b-0">
      <div className="min-w-0">
        <div className="text-[13.5px] font-semibold">{row.name}</div>
        <div className="text-xs text-muted">{row.sub}</div>
      </div>
      <ThreeWay value={row.choice} label={`${row.name} for ${person}`} disabled={busy} onChange={(next) => void choose(next)} />
      {row.choice !== "same" && !editing && (
        <div className={`flex basis-full flex-wrap items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs ${row.choice === "block" ? "bg-bad-soft text-bad-text" : "bg-ok-soft text-ok-text"}`}>
          <span>{row.note ? `Note: ${row.note}` : "No note yet."}</span>
          <button type="button" onClick={() => setEditing(true)} className="font-semibold underline-offset-2 hover:underline">
            {row.note ? "Change note" : "Add a note"}
          </button>
        </div>
      )}
      {editing && (
        <form
          className="flex basis-full gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void choose(row.choice, note.trim() || null);
          }}
        >
          <label className="flex-1">
            <span className="sr-only">Note for {row.name}</span>
            <input className="field !h-9 !text-[13px]" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Why, so the next person knows" autoFocus />
          </label>
          <button type="submit" disabled={busy} className="h-9 rounded-lg bg-accent px-3 text-[13px] font-semibold text-accent-on">
            Save
          </button>
          <button type="button" onClick={() => setEditing(false)} className="h-9 rounded-lg border border-line px-3 text-[13px]">
            Cancel
          </button>
        </form>
      )}
    </div>
  );
}

export function PersonDrawer({
  personId,
  providers,
  onClose,
  onSuspend,
  onRestore,
  onOpenAccess,
  onOpenAudit,
  version,
}: {
  personId: string;
  providers: Provider[] | null;
  onClose: () => void;
  onSuspend: (p: Person) => void;
  onRestore: (p: Person) => void;
  onOpenAccess: () => void;
  onOpenAudit: (search: string) => void;
  /** Bumped by the page when the person changes elsewhere, to reload. */
  version: number;
}) {
  const toast = useToast();
  const closeRef = useRef<HTMLButtonElement>(null);
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [apps, setApps] = useState<ConnectionAccess[] | null>(null);
  const [services, setServices] = useState<PersonServiceRow[] | null>(null);
  const [everyone, setEveryone] = useState<ServiceAccessRow[] | null>(null);
  const [log, setLog] = useState<AuditEntry[] | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([
      call<PersonDetail>(`/people/${personId}`),
      call<ConnectionAccess[]>(`/people/${personId}/connections`),
      call<PersonServiceRow[]>(`/people/${personId}/services`),
      call<ServiceAccessRow[]>("/service-access"),
      call<AuditEntry[]>(`/audit?target_id=${personId}&limit=20`),
    ])
      .then(([d, a, s, e, l]) => {
        if (!live) return;
        setDetail(d);
        setApps(a);
        setServices(s);
        setEveryone(e);
        setLog(l);
      })
      .catch(() => {
        toast("Could not load this person.", "bad");
        onClose();
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personId, version]);

  useEffect(() => {
    closeRef.current?.focus();
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  async function reloadLog() {
    setLog(await call<AuditEntry[]>(`/audit?target_id=${personId}&limit=20`));
  }

  const rows = useMemo<OverrideRow[]>(() => {
    if (!apps || !services || !everyone) return [];
    const platform = new Map(everyone.map((r) => [`${r.service}:${r.level}`, r.allowed]));
    const out: OverrideRow[] = [
      ...apps.map((c) => ({
        key: `app:${c.kind}`,
        name: APP_NAME[c.kind] ?? c.display_name,
        sub: `Whole app · everyone: ${c.everyone_allowed ? "allowed" : "off"}${c.platform_ready ? "" : " · not set up yet"}`,
        choice: (c.overridden ? (c.allowed ? "allow" : "block") : "same") as Choice,
        note: c.note,
        save: async (allowed: boolean | null, note: string | null) => {
          setApps(await call<ConnectionAccess[]>(`/people/${personId}/connections/${c.kind}`, { allowed, note }, "PUT"));
          await reloadLog();
        },
      })),
      ...services.map((r) => ({
        key: `${r.service}:${r.level}`,
        name: `${r.name} · ${r.level === "edit" ? "change" : "look"}`,
        sub: `Everyone: ${platform.get(`${r.service}:${r.level}`) === false ? "off" : "on"}`,
        choice: (r.overridden ? (r.allowed ? "allow" : "block") : "same") as Choice,
        note: r.note,
        save: async (allowed: boolean | null, note: string | null) => {
          setServices(await call<PersonServiceRow[]>(`/people/${personId}/services/${r.service}/${r.level}`, { allowed, note }, "PUT"));
          await reloadLog();
        },
      })),
    ];
    // Their own settings first: those are the ones worth reading.
    return [...out.filter((r) => r.choice !== "same"), ...out.filter((r) => r.choice === "same")];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps, services, everyone, personId]);

  const own = rows.filter((r) => r.choice !== "same").length;
  const shown = showAll ? rows : rows.slice(0, Math.max(FOLDED, own));
  const person = detail ? firstName(detail) : "";
  const llm = (providers ?? []).filter((p) => p.kind === "llm");
  const status = new Map((detail?.providers ?? []).map((p) => [p.provider_key, p.status]));

  return (
    <div className="fixed inset-0 z-[60]">
      <div aria-hidden="true" className="absolute inset-0" style={{ background: "var(--scrim)" }} onMouseDown={onClose} />
      <aside role="dialog" aria-modal="true" aria-labelledby="person-h" className="staff-drawer absolute inset-y-0 right-0 flex w-full max-w-[580px] flex-col bg-panel shadow-[-24px_0_56px_-24px_rgba(16,24,40,.35)]" style={{ animation: "staff-drawer-in .2s cubic-bezier(.2,0,0,1) both" }}>
        {!detail ? (
          <>
            <div className="flex justify-end p-4">
              <button ref={closeRef} type="button" aria-label="Close" onClick={onClose} className="inline-flex h-10 w-10 items-center justify-center rounded-[10px] border border-line text-muted">
                <Icon name="x" size={16} strokeWidth={2} />
              </button>
            </div>
            <Spinner rows={4} />
          </>
        ) : (
          <>
            <div className="flex flex-col gap-3.5 border-b border-line px-4 pb-[18px] pt-5 sm:px-6 sm:pt-[22px]">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3.5">
                  <PersonTile name={nameOf(detail)} seed={detail.id} size={52} />
                  <div className="min-w-0">
                    <h2 id="person-h" className="truncate text-[22px] font-semibold tracking-[-0.01em]">
                      {nameOf(detail)}
                    </h2>
                    <div className="truncate text-[13.5px] text-muted">
                      @{detail.username} · {detail.email}
                    </div>
                  </div>
                </div>
                <button ref={closeRef} type="button" aria-label="Close" onClick={onClose} className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-line text-muted hover:bg-raised">
                  <Icon name="x" size={16} strokeWidth={2} />
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {detail.active ? (
                  <Pill tone="ok" strong>
                    <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-ok" />
                    Active
                  </Pill>
                ) : (
                  <Pill tone="bad" strong>
                    <span aria-hidden="true" className="h-[7px] w-[7px] rounded-[2px] bg-bad" />
                    Suspended
                  </Pill>
                )}
                <Pill tone={detail.setup_link === "waiting" ? "ask" : detail.joined_via === "invited" ? "brand" : "mute"}>{joinedLabel(detail)}</Pill>
              </div>
              <p className="flex items-start gap-2 rounded-[10px] bg-bg px-3 py-2.5 text-[12.5px] text-muted">
                <Icon name="lock" size={15} strokeWidth={2} className="mt-px text-accent-text" />
                You see counts and yes or no here. {person}'s chats, memory, tasks and keys stay private to them.
              </p>
            </div>

            <div className="flex flex-1 flex-col gap-[26px] overflow-y-auto px-4 py-5 sm:px-6">
              <section aria-labelledby="facts-h">
                <h3 id="facts-h" className="mb-2.5 text-[13px] font-semibold text-muted">
                  At a glance
                </h3>
                <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3">
                  <Fact label="Joined">{shortDate(detail.created_at)}</Fact>
                  <Fact label="Last active">{lastActive(detail)}</Fact>
                  <Fact label="Tasks done">{detail.task_count.toLocaleString("en-GB")}</Fact>
                  <Fact label="Agents">
                    {detail.agent_count}
                    {detail.scheduled_agent_count > 0 && <span className="text-[12.5px] font-medium text-muted"> · {detail.scheduled_agent_count} scheduled</span>}
                  </Fact>
                  <Fact label="Runs this week">{detail.runs_this_week.toLocaleString("en-GB")}</Fact>
                  <Fact label="How they joined">{detail.joined_via === "self" ? "Signed up" : "Invited"}</Fact>
                </dl>
              </section>

              <section aria-labelledby="ai-h">
                <div className="mb-2.5 flex items-baseline justify-between gap-2">
                  <h3 id="ai-h" className="text-[13px] font-semibold text-muted">
                    AI providers connected
                  </h3>
                  <span className="text-xs text-muted">Keys are never shown</span>
                </div>
                <ul className="flex flex-wrap gap-2">
                  {[...llm].sort((a, b) => Number(status.has(b.key)) - Number(status.has(a.key))).map((p) => (
                    <li key={p.key}>
                      <YesNoChip
                        name={p.display_name}
                        state={!status.has(p.key) ? "no" : status.get(p.key) === "failed" ? "warn" : "yes"}
                        tag={p.is_local ? "local" : p.free_tier ? "free" : "paid"}
                      />
                    </li>
                  ))}
                </ul>
              </section>

              <section aria-labelledby="apps-h">
                <h3 id="apps-h" className="mb-2.5 text-[13px] font-semibold text-muted">
                  Apps connected
                </h3>
                <ul className="flex flex-wrap gap-2">
                  {detail.apps.map((a) => (
                    <li key={a.kind}>
                      <YesNoChip name={APP_NAME[a.kind] ?? a.display_name} state={a.connected ? "yes" : "no"} />
                    </li>
                  ))}
                </ul>
              </section>

              <section aria-labelledby="ov-h">
                <div className="mb-1 flex items-baseline justify-between gap-2">
                  <h3 id="ov-h" className="text-[13px] font-semibold text-muted">
                    Access just for {person}
                  </h3>
                  <button type="button" onClick={onOpenAccess} className="text-[12.5px] font-medium text-accent-text hover:underline">
                    Everyone's settings
                  </button>
                </div>
                <p className="mb-2.5 text-[12.5px] text-muted">Leave on "Same as everyone" unless there's a reason. Add a note so the next person knows why.</p>
                {rows.length === 0 ? (
                  <Spinner rows={1} />
                ) : (
                  <div className="overflow-hidden rounded-xl border border-line">
                    {shown.map((row) => (
                      <Override key={row.key} row={row} person={person} />
                    ))}
                    {rows.length > shown.length || showAll ? (
                      <button type="button" onClick={() => setShowAll((v) => !v)} className="h-[42px] w-full text-[13px] font-semibold text-accent-text" style={{ background: "var(--staff-head)" }}>
                        {showAll ? "Show fewer" : `Show all ${rows.length} services`}
                      </button>
                    ) : null}
                  </div>
                )}
              </section>

              <section aria-labelledby="log-h">
                <h3 id="log-h" className="mb-2.5 text-[13px] font-semibold text-muted">
                  Staff actions on this account
                </h3>
                <ol className="flex flex-col">
                  {(log ?? []).map((e) => {
                    const line = auditLine({ ...e, target_label: e.target_label ? firstName({ full_name: e.target_label, username: "", email: "" }) : null });
                    return (
                      <li key={e.id} className="grid grid-cols-[112px_minmax(0,1fr)] gap-3 border-b border-raised py-2.5">
                        <span className="font-mono text-[12.5px] text-muted">
                          {dayAndTime(e.created_at)}
                        </span>
                        <span>
                          <strong className="font-semibold">{staffName(e.admin_email)}</strong> {line.what} {line.note && <span className="text-muted">"{line.note}"</span>}
                        </span>
                      </li>
                    );
                  })}
                  <li className="grid grid-cols-[112px_minmax(0,1fr)] gap-3 py-2.5">
                    <span className="font-mono text-[12.5px] text-muted">{dayAndTime(detail.created_at)}</span>
                    <span className="text-muted">{detail.joined_via === "self" ? `${person} signed up. No staff action.` : `${person}'s account was made by staff.`}</span>
                  </li>
                </ol>
                <button type="button" onClick={() => onOpenAudit(nameOf(detail))} className="mt-1.5 text-[13px] font-medium text-accent-text hover:underline">
                  See in the audit log
                </button>
              </section>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-line bg-panel px-4 py-3.5 sm:px-6">
              {detail.active ? (
                <>
                  <span className="min-w-[200px] flex-1 text-[12.5px] text-muted">Suspending stops them signing in until you restore them. Nothing is deleted.</span>
                  <button type="button" onClick={() => onSuspend(detail)} className="h-[42px] rounded-[10px] border bg-panel px-4 font-semibold text-bad-text hover:bg-bad-soft" style={{ borderColor: "color-mix(in srgb, var(--bad) 40%, transparent)" }}>
                    Suspend account
                  </button>
                </>
              ) : (
                <>
                  <span className="min-w-[200px] flex-1 text-[12.5px] text-muted">Suspended. They can't sign in. Nothing of theirs was deleted.</span>
                  <button type="button" onClick={() => onRestore(detail)} className="h-[42px] rounded-[10px] bg-ok px-4 font-semibold text-ok-on">
                    Restore account
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

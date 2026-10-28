import { useEffect, useMemo, useState } from "react";
import { Icon } from "../icons";
import { useToast } from "../ui";
import { EmptyCard, ScreenTitle } from "./bits";
import { call, type AuditEntry } from "./api";
import { AUDIT_GROUPS, GROUP_LABEL, TONE_STYLE, auditLine, clock, dayHeading, staffName, type AuditGroup } from "./format";

/**
 * Records: the audit log, grouped by day and written in plain English.
 *
 * Append-only in the database: the application has no right to change
 * or delete an entry, so a staff member cannot remove the record of
 * their own actions. This screen only reads it.
 */

const PAGE = 100;

export function AuditLog({ providers, initialSearch }: { providers: Record<string, string>; initialSearch: string }) {
  const toast = useToast();
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [more, setMore] = useState(true);
  const [busy, setBusy] = useState(false);
  const [staff, setStaff] = useState("anyone");
  const [what, setWhat] = useState<AuditGroup | "all">("all");
  const [search, setSearch] = useState(initialSearch);

  useEffect(() => setSearch(initialSearch), [initialSearch]);

  useEffect(() => {
    call<AuditEntry[]>(`/audit?limit=${PAGE}`)
      .then((rows) => {
        setEntries(rows);
        setMore(rows.length === PAGE);
      })
      .catch(() => toast("Could not load the audit log.", "bad"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function older() {
    if (!entries?.length) return;
    setBusy(true);
    try {
      const before = encodeURIComponent(entries[entries.length - 1].created_at);
      const rows = await call<AuditEntry[]>(`/audit?limit=${PAGE}&before=${before}`);
      setEntries([...entries, ...rows]);
      setMore(rows.length === PAGE);
    } catch {
      toast("Could not load older entries.", "bad");
    } finally {
      setBusy(false);
    }
  }

  const staffList = useMemo(() => [...new Set((entries ?? []).map((e) => e.admin_email ?? ""))].filter(Boolean).sort(), [entries]);

  const days = useMemo(() => {
    const term = search.trim().toLowerCase();
    const out: { label: string; items: { entry: AuditEntry; line: ReturnType<typeof auditLine> }[] }[] = [];
    for (const entry of entries ?? []) {
      const line = auditLine(entry, providers);
      if (staff !== "anyone" && entry.admin_email !== staff) continue;
      if (what !== "all" && line.group !== what) continue;
      if (term && ![entry.admin_email ?? "", line.what, line.note ?? "", entry.target_label ?? ""].some((v) => v.toLowerCase().includes(term))) continue;
      const label = dayHeading(entry.created_at);
      if (out.length === 0 || out[out.length - 1].label !== label) out.push({ label, items: [] });
      out[out.length - 1].items.push({ entry, line });
    }
    return out;
  }, [entries, staff, what, search, providers]);

  const select = "flex h-11 items-center gap-2 rounded-[10px] border border-line bg-panel px-3 text-[13px] text-muted sm:h-10";

  return (
    <div className="flex flex-col gap-5">
      <ScreenTitle
        title="Audit log"
        action={
          <span className="inline-flex h-[30px] items-center gap-1.5 rounded-full border border-line bg-panel px-3 text-[12.5px] text-muted">
            <Icon name="lock" size={14} strokeWidth={2} />
            Read only
          </span>
        }
      >
        Every staff sign-in and change, written by the server as it happens. Nobody can edit or delete an entry, staff included.
      </ScreenTitle>

      <div className="flex flex-col gap-2.5 sm:flex-row sm:flex-wrap sm:items-center">
        <label className={select}>
          Staff member
          <select value={staff} onChange={(e) => setStaff(e.target.value)} className="h-full min-w-0 flex-1 border-0 bg-transparent font-medium text-ink outline-none">
            <option value="anyone">Anyone</option>
            {staffList.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className={select}>
          What
          <select value={what} onChange={(e) => setWhat(e.target.value as AuditGroup | "all")} className="h-full min-w-0 flex-1 border-0 bg-transparent font-medium text-ink outline-none">
            {AUDIT_GROUPS.map((g) => (
              <option key={g.key} value={g.key}>
                {g.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex h-11 items-center gap-2 rounded-[10px] border border-line2 bg-panel px-3 text-dim focus-within:border-accent sm:h-10 sm:flex-[1_1_240px]">
          <Icon name="search" size={16} strokeWidth={2} />
          <span className="sr-only">Search the log</span>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by person or detail" className="min-w-0 flex-1 border-0 bg-transparent text-ink outline-none placeholder:text-dim" />
        </label>
      </div>

      <div className="overflow-hidden rounded-2xl border border-line bg-panel">
        {!entries ? (
          <div className="skeleton m-5 h-48" />
        ) : days.length === 0 ? (
          <EmptyCard icon="search" title={entries.length ? "Nothing matches" : "Nothing recorded yet"}>
            {entries.length ? "Try another staff member, kind of change or search." : "Every staff sign-in and change lands here as it happens."}
          </EmptyCard>
        ) : (
          days.map((day) => (
            <div key={day.label}>
              <div className="border-b border-line px-4 py-2.5 text-[12.5px] font-semibold text-muted sm:px-5" style={{ background: "var(--staff-head)" }}>
                {day.label}
              </div>
              {day.items.map(({ entry, line }) => {
                const tone = TONE_STYLE[line.tone];
                return (
                  <div key={entry.id} className="grid grid-cols-[48px_28px_minmax(0,1fr)] items-center gap-3 border-b border-raised px-4 py-3 sm:grid-cols-[64px_28px_minmax(0,1fr)_auto] sm:px-5">
                    <span className="font-mono text-[13px] text-muted">{clock(entry.created_at)}</span>
                    <span aria-hidden="true" className={`inline-flex h-7 w-7 items-center justify-center rounded-lg text-xs font-bold ${tone.className}`}>
                      {tone.mark}
                    </span>
                    <div className="min-w-0">
                      <strong className="font-semibold">{staffName(entry.admin_email)}</strong> {line.what} {line.note && <span className="text-muted">"{line.note}"</span>}
                    </div>
                    <span className="hidden whitespace-nowrap text-xs text-muted sm:inline">{line.group === "access" ? tone.label : GROUP_LABEL[line.group]}</span>
                  </div>
                );
              })}
            </div>
          ))
        )}
        {entries && more && (
          <div className="flex justify-center px-5 py-3">
            <button type="button" disabled={busy} onClick={() => void older()} className="h-11 rounded-[10px] border border-line bg-panel px-3.5 font-medium sm:h-9">
              {busy ? "Loading…" : "Show older entries"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

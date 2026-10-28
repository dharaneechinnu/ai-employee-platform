import { useEffect, useMemo, useState } from "react";
import { Icon } from "../icons";
import { EmptyCard, Pill, PersonTile, RowMenu, StatusText, type MenuItem } from "./bits";
import type { Person } from "./api";
import { expiresToday, joinedLabel, lastActive, linkNote, nameOf, shortDate } from "./format";

/**
 * The people list. A table on a wide screen, cards on a phone. Search
 * covers name, username and email; filters cover status (including
 * "setup link waiting") and how they joined.
 *
 * Row actions appear only when they apply: "Copy link" for a waiting
 * invite and "Restore" for a suspended account. Everything else,
 * including Suspend, waits under the ⋮ menu, so there is no red button
 * on every row to hit by mistake.
 */

type Status = "all" | "active" | "suspended" | "waiting";
type Joined = "any" | "self" | "invited";

const PAGE = 10;

export interface PeopleActions {
  open: (p: Person) => void;
  suspend: (p: Person) => void;
  restore: (p: Person) => void;
  /** Copy the setup link, making a new one if this session has not got it. */
  link: (p: Person) => void;
  invite: () => void;
}

function waiting(p: Person) {
  return p.setup_link === "waiting" || p.setup_link === "expired";
}

function JoinedPill({ p }: { p: Person }) {
  if (p.joined_via === "self") return <Pill>Signed up themselves</Pill>;
  if (p.setup_link === "used") return <Pill tone="brand">Invited · link used</Pill>;
  return (
    <div>
      <Pill tone="ask" strong>
        {p.setup_link === "expired" ? "Invited · link expired" : "Invited · link waiting"}
      </Pill>
      {p.setup_link === "waiting" && <div className="pt-[3px] text-xs text-ask-text">{linkNote(p)}</div>}
    </div>
  );
}

function menuFor(p: Person, act: PeopleActions, hasLink: boolean): MenuItem[] {
  const items: MenuItem[] = [{ label: "Open details", icon: "eye", onSelect: () => act.open(p) }];
  if (waiting(p)) items.push({ label: hasLink ? "Copy setup link" : "Make a new setup link", icon: "link", onSelect: () => act.link(p) });
  items.push(
    p.active
      ? { label: "Suspend account…", icon: "lock", danger: true, onSelect: () => act.suspend(p) }
      : { label: "Restore account", icon: "check", onSelect: () => act.restore(p) },
  );
  return items;
}

const SMALL_BUTTON = "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-panel px-2.5 text-[13px] transition-colors hover:bg-raised disabled:opacity-60";

export function PeopleSection({ people, act, links, busy }: { people: Person[]; act: PeopleActions; links: Set<string>; busy: string | null }) {
  const [status, setStatus] = useState<Status>("all");
  const [joined, setJoined] = useState<Joined>("any");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [phoneCount, setPhoneCount] = useState(PAGE);

  useEffect(() => {
    setPage(0);
    setPhoneCount(PAGE);
  }, [status, joined, search]);

  const counts = useMemo(
    () => ({
      all: people.length,
      active: people.filter((p) => p.active).length,
      suspended: people.filter((p) => !p.active).length,
      waiting: people.filter(waiting).length,
    }),
    [people],
  );

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase().replace(/^@/, "");
    return people.filter(
      (p) =>
        (status === "all" || (status === "active" ? p.active : status === "suspended" ? !p.active : waiting(p))) &&
        (joined === "any" || p.joined_via === joined) &&
        (!term || [p.full_name ?? "", p.username, p.email].some((v) => v.toLowerCase().includes(term))),
    );
  }, [people, status, joined, search]);

  const today = people.filter((p) => expiresToday(p));
  const pageRows = visible.slice(page * PAGE, page * PAGE + PAGE);

  const tabs: { key: Status; label: string; phone: string }[] = [
    { key: "all", label: "All", phone: "All" },
    { key: "active", label: "Active", phone: "Active" },
    { key: "suspended", label: "Suspended", phone: "Suspended" },
    { key: "waiting", label: "Setup link waiting", phone: "Link waiting" },
  ];

  const statusWord = { all: "everyone", active: "active people", suspended: "suspended people", waiting: "people with a setup link waiting" }[status];

  if (people.length === 0) {
    return (
      <section className="rounded-2xl border border-line bg-panel">
        <EmptyCard
          icon="people"
          tone="brand"
          title="No one has joined yet"
          actions={
            <button type="button" onClick={act.invite} className="h-10 rounded-[10px] bg-accent px-4 font-semibold text-accent-on">
              Invite someone
            </button>
          }
        >
          People can sign up themselves at /register, or you can invite someone and send them a one-time setup link.
        </EmptyCard>
      </section>
    );
  }

  return (
    <section aria-labelledby="people-h" className="flex flex-col gap-4 sm:gap-0 sm:overflow-hidden sm:rounded-2xl sm:border sm:border-line sm:bg-panel">
      <div className="flex flex-col gap-3.5 sm:border-b sm:border-line sm:px-5 sm:pb-3.5 sm:pt-[18px]">
        <div className="hidden flex-wrap items-baseline justify-between gap-2 sm:flex">
          <h2 id="people-h" className="text-[19px] font-semibold">
            People
          </h2>
          <span className="text-[12.5px] text-muted">Open a row to see their connections and access. Never their content.</span>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2.5">
          {/* A wide screen gets one segmented control; a phone gets chips that scroll sideways. */}
          <div role="tablist" aria-label="Filter by status" className="hidden flex-wrap gap-0.5 rounded-[10px] bg-raised p-[3px] sm:inline-flex">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={status === t.key}
                onClick={() => setStatus(t.key)}
                className={`h-[34px] rounded-lg px-3 transition-colors ${status === t.key ? "bg-panel font-semibold text-ink shadow-[0_1px_2px_rgba(16,24,40,.08)]" : "font-medium text-muted hover:text-ink"}`}
              >
                {t.label}{" "}
                <span className={t.key === "waiting" && counts.waiting > 0 ? "font-semibold text-ask-text" : "font-medium text-dim"}>{counts[t.key]}</span>
              </button>
            ))}
          </div>
          <label className="order-first flex h-11 items-center gap-2 rounded-[10px] border border-line2 bg-panel px-3 text-dim focus-within:border-accent sm:order-none sm:h-10 sm:flex-[1_1_260px]">
            <Icon name="search" size={16} strokeWidth={2} />
            <span className="sr-only">Search people</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, username or email"
              className="min-w-0 flex-1 border-0 bg-transparent text-ink outline-none placeholder:text-dim"
            />
          </label>
          <div role="tablist" aria-label="Filter by status" className="-mx-4 flex gap-2 overflow-x-auto px-4 sm:hidden">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={status === t.key}
                onClick={() => setStatus(t.key)}
                className={`h-11 shrink-0 rounded-full border px-3.5 text-[13px] ${status === t.key ? "border-accent-line bg-accent-soft font-semibold text-accent-text" : "border-line bg-panel text-muted"}`}
              >
                {t.phone} {counts[t.key]}
              </button>
            ))}
          </div>
          <label className="flex h-11 items-center gap-2 rounded-[10px] border border-line bg-panel px-3 text-[13px] text-muted sm:order-2 sm:h-10">
            How they joined
            <select value={joined} onChange={(e) => setJoined(e.target.value as Joined)} className="h-full flex-1 border-0 bg-transparent font-medium text-ink outline-none">
              <option value="any">Anyone</option>
              <option value="self">Signed up themselves</option>
              <option value="invited">Invited by staff</option>
            </select>
          </label>
        </div>
      </div>

      {today.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-[color:color-mix(in_srgb,var(--ask)_40%,transparent)] bg-ask-soft px-4 py-2.5 text-[13px] text-ask-text sm:rounded-none sm:border-0 sm:border-b sm:px-5">
          <span className="flex items-center gap-2">
            <Icon name="clock" size={15} strokeWidth={2} />
            {today.length === 1 ? (
              <span>
                <strong className="font-semibold">{nameOf(today[0])}'s setup link expires today.</strong> They haven't used it yet.
              </span>
            ) : (
              <span>
                <strong className="font-semibold">{today.length} setup links expire today.</strong> {today.map(nameOf).join(", ")}.
              </span>
            )}
          </span>
          {today.length === 1 ? (
            <button type="button" disabled={busy === today[0].id} onClick={() => act.link(today[0])} className="h-8 rounded-lg border border-[color:color-mix(in_srgb,var(--ask)_50%,transparent)] bg-[color:color-mix(in_srgb,var(--panel)_60%,transparent)] px-3 font-semibold">
              Send a new link
            </button>
          ) : (
            <button type="button" onClick={() => setStatus("waiting")} className="h-8 rounded-lg border border-[color:color-mix(in_srgb,var(--ask)_50%,transparent)] bg-[color:color-mix(in_srgb,var(--panel)_60%,transparent)] px-3 font-semibold">
              Show them
            </button>
          )}
        </div>
      )}

      {visible.length === 0 ? (
        <div className="rounded-2xl border border-line bg-panel sm:rounded-none sm:border-0">
          <EmptyCard
            icon="search"
            title={search.trim() ? `No one matches "${search.trim()}"` : "No one here"}
            actions={
              <>
                {(status !== "all" || joined !== "any") && (
                  <button
                    type="button"
                    onClick={() => {
                      setStatus("all");
                      setJoined("any");
                    }}
                    className="h-10 rounded-[10px] border border-line bg-panel px-3.5 font-medium"
                  >
                    Search everyone
                  </button>
                )}
                {search.trim() && (
                  <button type="button" onClick={() => setSearch("")} className="h-10 rounded-[10px] px-3.5 font-semibold text-accent-text">
                    Clear search
                  </button>
                )}
              </>
            }
          >
            {search.trim() ? `We looked at names, usernames and emails among ${statusWord}.` : `There are no ${statusWord} right now.`}
          </EmptyCard>
        </div>
      ) : (
        <>
          {/* Wide screens: the table. */}
          <div className="hidden overflow-x-auto sm:block">
            <div role="table" aria-label="People" className="min-w-[960px]">
              <div role="row" className="grid grid-cols-[minmax(0,2.3fr)_minmax(0,1.5fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_minmax(0,1fr)_170px] gap-3 border-b border-line px-5 py-2.5 text-xs font-semibold text-muted" style={{ background: "var(--staff-head)" }}>
                <div role="columnheader">Person</div>
                <div role="columnheader">How they joined</div>
                <div role="columnheader">Status</div>
                <div role="columnheader">Joined</div>
                <div role="columnheader">Last active</div>
                <div role="columnheader" className="text-right">
                  Actions
                </div>
              </div>
              {pageRows.map((p) => (
                <div key={p.id} role="row" className="grid min-h-[44px] grid-cols-[minmax(0,2.3fr)_minmax(0,1.5fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_minmax(0,1fr)_170px] items-center gap-3 border-b border-raised px-5 py-3 last:border-b-0 hover:bg-[color:var(--staff-head)]">
                  <div role="cell" className="flex min-w-0 items-center gap-3">
                    <PersonTile name={nameOf(p)} seed={p.id} />
                    <div className="min-w-0">
                      <button type="button" onClick={() => act.open(p)} className="font-semibold text-ink hover:text-accent-text hover:underline">
                        {nameOf(p)}
                      </button>{" "}
                      <span className="text-[13px] text-muted">@{p.username}</span>
                      <div className="truncate text-[12.5px] text-muted">{p.email}</div>
                    </div>
                  </div>
                  <div role="cell">
                    <JoinedPill p={p} />
                  </div>
                  <div role="cell">
                    <StatusText active={p.active} />
                  </div>
                  <div role="cell" className="text-[13px]">
                    {shortDate(p.created_at)}
                  </div>
                  <div role="cell" className="text-[13px] text-muted" title={p.last_active_at ? new Date(p.last_active_at).toLocaleString() : undefined}>
                    {lastActive(p)}
                  </div>
                  <div role="cell" className="flex items-center justify-end gap-1.5">
                    {waiting(p) && (
                      <button type="button" disabled={busy === p.id} onClick={() => act.link(p)} className={`${SMALL_BUTTON} border-line font-medium text-ink`}>
                        <Icon name="copy" size={14} strokeWidth={2} />
                        {links.has(p.id) ? "Copy link" : "New link"}
                      </button>
                    )}
                    {!p.active && (
                      <button type="button" disabled={busy === p.id} onClick={() => act.restore(p)} className={`${SMALL_BUTTON} border-[color:color-mix(in_srgb,var(--ok)_40%,transparent)] font-semibold text-ok-text`}>
                        Restore
                      </button>
                    )}
                    <RowMenu label={`More actions for ${nameOf(p)}`} items={menuFor(p, act, links.has(p.id))} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="hidden flex-wrap items-center justify-between gap-2.5 px-5 py-3 text-[13px] text-muted sm:flex">
            <span>
              Showing {page * PAGE + 1}–{Math.min(visible.length, page * PAGE + PAGE)} of {visible.length}
            </span>
            <div className="flex gap-1.5">
              <button type="button" disabled={page === 0} onClick={() => setPage((v) => v - 1)} className="h-[34px] rounded-lg border border-line bg-panel px-3 font-medium text-ink disabled:bg-transparent disabled:text-dim">
                Previous
              </button>
              <button type="button" disabled={(page + 1) * PAGE >= visible.length} onClick={() => setPage((v) => v + 1)} className="h-[34px] rounded-lg border border-line bg-panel px-3 font-medium text-ink disabled:bg-transparent disabled:text-dim">
                Next
              </button>
            </div>
          </div>

          {/* Phones: one card per person. */}
          <ul className="flex flex-col gap-2.5 sm:hidden">
            {visible.slice(0, phoneCount).map((p) => (
              <li key={p.id} className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-panel p-3.5">
                <div className="flex items-center gap-3">
                  <PersonTile name={nameOf(p)} seed={p.id} size={38} />
                  <div className="min-w-0 flex-1">
                    <button type="button" onClick={() => act.open(p)} className="text-left font-semibold text-ink">
                      {nameOf(p)}
                    </button>{" "}
                    <span className="text-[12.5px] text-muted">@{p.username}</span>
                    <div className="truncate text-[12.5px] text-muted">{p.email}</div>
                  </div>
                  <RowMenu label={`More actions for ${nameOf(p)}`} items={menuFor(p, act, links.has(p.id))} size={44} />
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  {p.active ? (
                    <span className="inline-flex h-6 items-center gap-[5px] rounded-full bg-ok-soft px-2 font-semibold text-ok-text">
                      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-ok" />
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex h-6 items-center gap-[5px] rounded-full bg-bad-soft px-2 font-semibold text-bad-text">
                      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-[1px] bg-bad" />
                      Suspended
                    </span>
                  )}
                  {p.joined_via === "self" ? (
                    <span className="inline-flex h-6 items-center rounded-full bg-raised px-2 text-muted">Signed up</span>
                  ) : waiting(p) ? (
                    <span className="inline-flex h-6 items-center rounded-full bg-ask-soft px-2 font-semibold text-ask-text">
                      Link {p.setup_link === "expired" ? "expired" : `waiting · ${linkNote(p).replace("Expires", "expires").replace(/, .*$/, "")}`}
                    </span>
                  ) : (
                    <span className="inline-flex h-6 items-center rounded-full bg-accent-soft px-2 text-accent-text">{joinedLabel(p)}</span>
                  )}
                  <span className="ml-auto text-dim">{p.last_active_at ? lastActive(p) : "Not signed in"}</span>
                </div>
                {waiting(p) && (
                  <button type="button" disabled={busy === p.id} onClick={() => act.link(p)} className="h-11 rounded-[10px] border border-line2 bg-raised font-medium">
                    {links.has(p.id) ? "Copy setup link" : "Make a new setup link"}
                  </button>
                )}
                {!p.active && (
                  <button type="button" disabled={busy === p.id} onClick={() => act.restore(p)} className="h-11 rounded-[10px] border border-[color:color-mix(in_srgb,var(--ok)_40%,transparent)] bg-ok-soft font-semibold text-ok-text">
                    Restore account
                  </button>
                )}
              </li>
            ))}
          </ul>
          {visible.length > phoneCount && (
            <button type="button" onClick={() => setPhoneCount((v) => v + PAGE)} className="h-11 rounded-[10px] border border-line bg-panel font-medium sm:hidden">
              Show more
            </button>
          )}
        </>
      )}
    </section>
  );
}

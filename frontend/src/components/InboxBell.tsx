import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Dock } from "../lib/dock";
import { useInbox } from "../lib/inbox";
import { Icon } from "./icons";
import { Button, relativeTime } from "./ui";

/**
 * What finished while you were away.
 *
 * A run takes minutes, so the product only works if you can walk off
 * and be told what happened when you come back. The count is the
 * whole feature: a number on a bell is the one thing people check
 * without being asked to.
 *
 * Read state is per device on purpose — "have I looked at this?" is a
 * fact about you at this screen, not about the task.
 */

const KIND = {
  finished: { icon: "check", tone: "var(--ok)", soft: "var(--ok-soft)", word: "finished" },
  failed: { icon: "warn", tone: "var(--bad)", soft: "var(--bad-soft)", word: "could not finish" },
  needs_you: { icon: "approvals", tone: "var(--ask)", soft: "var(--ask-soft)", word: "needs you" },
} as const;

export default function InboxBell({
  orgId,
  isAdmin,
  dock,
}: {
  orgId: string | undefined;
  isAdmin: boolean;
  dock: Dock;
}) {
  const { items, unread, markRead, markAllRead } = useInbox(orgId, isAdmin);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (!(e.target as HTMLElement).closest?.("[data-inbox]")) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const side =
    dock === "left" ? "rail-menu-left" : dock === "right" ? "rail-menu-right" : "rail-menu-bottom";

  return (
    <div className="relative" data-inbox>
      <button
        type="button"
        className="rail-link"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-rail-label={unread ? `${unread} new` : "Nothing new"}
      >
        <Icon name="bell" size={19} />
        <span className="sr-only">
          {unread ? `${unread} unread updates` : "Updates, nothing unread"}
        </span>
        {unread > 0 && (
          <b className="rail-count live-ask" aria-hidden="true">
            {unread > 9 ? "9+" : unread}
          </b>
        )}
      </button>

      {open && (
        <div role="dialog" aria-label="Updates" className={`rail-menu w-[330px] ${side}`}>
          <div className="flex items-center gap-2 px-2.5 pb-2 pt-1">
            <span className="font-display text-sm font-semibold">Updates</span>
            {unread > 0 && (
              <Button size="sm" variant="ghost" className="ml-auto" onClick={markAllRead}>
                Mark all read
              </Button>
            )}
          </div>

          {items.length === 0 ? (
            <p className="px-2.5 pb-2 text-[13px] text-dim">
              Nothing yet. Assign a task and the result turns up here.
            </p>
          ) : (
            <div className="flex max-h-[340px] flex-col gap-0.5 overflow-y-auto">
              {items.slice(0, 20).map((item) => {
                const kind = KIND[item.kind];
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`flex items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-raised ${
                      item.unread ? "" : "opacity-60"
                    }`}
                    onClick={() => {
                      markRead(item.id);
                      setOpen(false);
                      navigate(item.href);
                    }}
                  >
                    <span
                      className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                      style={{ background: kind.soft, color: kind.tone }}
                    >
                      <Icon name={kind.icon} size={13} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-[13px] font-medium">{item.title}</span>
                      <span className="text-xs text-dim">
                        {kind.word} · {relativeTime(item.at)}
                      </span>
                    </span>
                    {item.unread && (
                      <span
                        className="mt-2 h-[7px] w-[7px] shrink-0 rounded-full"
                        style={{ background: "var(--accent)" }}
                        aria-label="unread"
                      />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

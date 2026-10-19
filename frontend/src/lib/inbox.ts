import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Approval, type TaskListItem } from "./api";

/**
 * What happened while you were looking somewhere else.
 *
 * A run takes minutes, so nobody sits and watches it. The whole point
 * of an AI Employee is that you give it work and go away — which only
 * works if coming back tells you what finished.
 *
 * "Unread" is a per-device, per-person idea: whether *you* have looked
 * yet, not a fact about the task. So it lives in localStorage rather
 * than on the server, and your phone and your laptop each keep their
 * own view. Losing it costs one over-count, which is why a read that
 * throws is simply treated as "seen nothing yet".
 */

export interface InboxItem {
  id: string;
  kind: "finished" | "failed" | "needs_you";
  title: string;
  at: string;
  /** Where clicking it should go. */
  href: string;
  unread: boolean;
}

const SEEN_KEY = "ai-employees.inbox.seen";
const POLL_MS = 15_000;
const EVENT = "activity-changed";

function readSeen(orgId: string): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(`${SEEN_KEY}.${orgId}`);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeSeen(orgId: string, seen: Record<string, string>): void {
  try {
    // Only the last 200 matter; without a cap this grows forever on a
    // busy workspace and eventually throws on write.
    const trimmed = Object.fromEntries(Object.entries(seen).slice(-200));
    window.localStorage.setItem(`${SEEN_KEY}.${orgId}`, JSON.stringify(trimmed));
  } catch {
    // A workspace that cannot remember what you read is mildly
    // annoying; one that fails to render is not acceptable.
  }
}

export function useInbox(orgId: string | undefined, isAdmin: boolean) {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [seen, setSeen] = useState<Record<string, string>>({});

  useEffect(() => {
    if (orgId) setSeen(readSeen(orgId));
  }, [orgId]);

  useEffect(() => {
    if (!orgId) return;
    let cancelled = false;

    async function load() {
      try {
        const list = await api.get<TaskListItem[]>(`/orgs/${orgId}/tasks`);
        if (cancelled) return;
        setTasks(list);
        if (isAdmin) {
          const waiting = await api.get<Approval[]>(`/orgs/${orgId}/approvals`);
          if (!cancelled) setApprovals(waiting);
        } else {
          setApprovals([]);
        }
      } catch {
        // Keep whatever we had. A bell that empties itself on one
        // failed poll is worse than a slightly stale one.
      }
    }

    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    const onChange = () => void load();
    window.addEventListener(EVENT, onChange);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener(EVENT, onChange);
    };
  }, [orgId, isAdmin]);

  const items = useMemo<InboxItem[]>(() => {
    const out: InboxItem[] = [];

    for (const approval of approvals) {
      out.push({
        id: `approval:${approval.id}`,
        kind: "needs_you",
        title: `${approval.tool_name.replace(/_/g, " ")} is waiting for your decision`,
        at: approval.created_at,
        href: "/approvals",
        unread: !seen[`approval:${approval.id}`],
      });
    }

    for (const task of tasks) {
      if (task.status !== "completed" && task.status !== "failed") continue;
      out.push({
        id: `task:${task.id}:${task.status}`,
        kind: task.status === "completed" ? "finished" : "failed",
        title: task.title ?? "Untitled task",
        at: task.created_at,
        href: `/tasks?task=${task.id}`,
        unread: !seen[`task:${task.id}:${task.status}`],
      });
    }

    return out.sort((a, b) => (a.at < b.at ? 1 : -1));
  }, [tasks, approvals, seen]);

  const unread = items.filter((i) => i.unread).length;

  const markRead = useCallback(
    (id: string) => {
      if (!orgId) return;
      setSeen((current) => {
        const next = { ...current, [id]: new Date().toISOString() };
        writeSeen(orgId, next);
        return next;
      });
    },
    [orgId],
  );

  const markAllRead = useCallback(() => {
    if (!orgId) return;
    setSeen((current) => {
      const next = { ...current };
      const now = new Date().toISOString();
      for (const item of items) next[item.id] = now;
      writeSeen(orgId, next);
      return next;
    });
  }, [orgId, items]);

  return { items, unread, markRead, markAllRead };
}

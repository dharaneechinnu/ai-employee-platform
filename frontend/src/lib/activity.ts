import { useEffect, useState } from "react";
import { api, type Approval, type TaskListItem } from "./api";

/**
 * The two numbers the sidebar shows on every screen: how many runs are
 * going right now, and how many decisions are waiting for a person.
 *
 * Polled, because these change while you are looking at another page.
 * A screen that changes them (deciding an approval, assigning a task)
 * calls notifyActivity() so the sidebar updates at once instead of on
 * the next poll.
 */

const EVENT = "activity-changed";
const POLL_MS = 20_000;

export function notifyActivity(): void {
  window.dispatchEvent(new Event(EVENT));
}

export function useActivity(orgId: string | undefined, isAdmin: boolean) {
  const [running, setRunning] = useState(0);
  const [waiting, setWaiting] = useState(0);

  useEffect(() => {
    if (!orgId) return;
    let cancelled = false;

    async function load() {
      try {
        const tasks = await api.get<TaskListItem[]>(`/orgs/${orgId}/tasks`);
        if (cancelled) return;
        setRunning(tasks.filter((t) => t.status === "running" || t.status === "queued").length);
        if (isAdmin) {
          const approvals = await api.get<Approval[]>(`/orgs/${orgId}/approvals`);
          if (!cancelled) setWaiting(approvals.length);
        } else {
          setWaiting(0);
        }
      } catch {
        // The sidebar is a hint, not the source of truth: a failed poll
        // keeps the last numbers rather than flashing an error.
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

  return { running, waiting };
}

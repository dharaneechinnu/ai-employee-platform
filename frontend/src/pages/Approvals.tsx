import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/icons";
import ProposedAction from "../components/ProposedAction";
import {
  Button,
  Chip,
  Empty,
  HoldButton,
  PageBody,
  PageHeader,
  Spinner,
  relativeTime,
  statusTone,
  useToast,
} from "../components/ui";
import { effectLabel, formatDateTime, toolAction, toolLabel } from "../lib/labels";
import { notifyActivity } from "../lib/activity";
import { ApiError, api, type Approval } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Phase 5. The reviewer sees the full proposed action, never only a
 * summary: you cannot meaningfully approve what you cannot read. The
 * plain sentence on top helps you read it; it does not replace it.
 *
 * Anything destructive needs a one-second hold to approve, because a
 * sent email or a deleted row cannot be called back.
 */

const REFRESH_MS = 20_000;

export default function Approvals() {
  const { org } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState<Approval[] | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [, setNow] = useState(Date.now());

  async function load() {
    if (!org) return;
    setItems(await api.get<Approval[]>(`/orgs/${org.id}/approvals`));
  }

  useEffect(() => {
    void load();
    const poll = window.setInterval(() => void load(), REFRESH_MS);
    // Re-render each minute so "expires in" stays honest.
    const tick = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function decide(approval: Approval, approve: boolean) {
    if (!org) return;
    setDeciding(approval.id);
    try {
      await api.post(`/orgs/${org.id}/approvals/${approval.id}/${approve ? "approve" : "reject"}`);
      setItems((current) => current?.filter((a) => a.id !== approval.id) ?? null);
      toast(
        approve
          ? `Approved. The run carries on: ${toolAction(approval.tool_name)}.`
          : `Rejected. "${toolLabel(approval.tool_name)}" will not happen.`,
        approve ? "ok" : "info",
      );
      notifyActivity();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not record that.", "bad");
      await load();
    } finally {
      setDeciding(null);
    }
  }

  return (
    <>
      <PageHeader crumb="Work" title="Approvals">
        <span className="max-w-[360px] text-[13px] leading-snug text-muted">
          AI Employees stop here before anything they cannot undo.
        </span>
      </PageHeader>

      <PageBody className="max-w-[1040px]">
        {!items ? (
          <Spinner rows={2} />
        ) : items.length === 0 ? (
          <Empty
            message="Nothing is waiting for you"
            hint="When an AI Employee needs a decision, it appears here and the sidebar shows a count."
          />
        ) : (
          items.map((approval, i) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              index={i}
              busy={deciding === approval.id}
              onDecide={(approve) => void decide(approval, approve)}
            />
          ))
        )}
      </PageBody>
    </>
  );
}

function ApprovalCard({
  approval,
  index,
  busy,
  onDecide,
}: {
  approval: Approval;
  index: number;
  busy: boolean;
  onDecide: (approve: boolean) => void;
}) {
  const destructive = approval.side_effect === "destructive";
  const created = new Date(approval.created_at).getTime();
  const expires = new Date(approval.expires_at).getTime();
  const left = Math.max(0, Math.min(1, (expires - Date.now()) / Math.max(1, expires - created)));

  return (
    <article
      className="card rise relative overflow-hidden"
      style={{
        animationDelay: `${index * 0.08}s`,
        ...(destructive ? { borderColor: "var(--ask)" } : {}),
      }}
    >
      {destructive && <span aria-hidden="true" className="absolute inset-x-0 top-0 h-[3px] bg-ask" />}

      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-ask-soft text-ask-text">
          <Icon name="approvals" size={20} />
        </span>
        <div className="flex min-w-[220px] flex-1 flex-col gap-0.5">
          <span className="text-[15px] font-medium">
            Wants to <span className="text-ask-text">{toolAction(approval.tool_name)}</span>
          </span>
          {approval.task_title && (
            <span className="truncate text-[13px] text-muted">Task: {approval.task_title}</span>
          )}
        </div>
        <Chip tone={statusTone(approval.side_effect)}>{effectLabel(approval.side_effect)}</Chip>
        <span className="flex items-center gap-2" title={`Expires ${formatDateTime(approval.expires_at)}`}>
          <svg width="38" height="38" viewBox="0 0 40 40" aria-hidden="true" className="-rotate-90">
            <circle cx="20" cy="20" r="17" fill="none" stroke="var(--line2)" strokeWidth="3" />
            <circle
              cx="20"
              cy="20"
              r="17"
              fill="none"
              stroke="var(--ask)"
              strokeWidth="3"
              strokeLinecap="round"
              strokeDasharray={107}
              strokeDashoffset={107 * (1 - left)}
              style={{ transition: "stroke-dashoffset 1s" }}
            />
          </svg>
          <span className="flex flex-col text-xs text-dim">
            expires
            <b className="font-mono text-sm font-medium text-ask-text">{relativeTime(approval.expires_at)}</b>
          </span>
        </span>
      </div>

      <div className="flex flex-col gap-3.5 px-5 py-4">
        <div className={`flex items-start gap-3 rounded-[14px] px-4 py-3 text-sm leading-relaxed ${destructive ? "bg-ask-soft" : "bg-raised"}`}>
          <Icon name={destructive ? "warn" : "info"} size={20} className={destructive ? "text-ask-text" : "text-muted"} />
          <span>
            <b>If you approve:</b> {describe(approval)}
          </span>
        </div>

        <div data-coach="approval-action">
          <ProposedAction values={approval.proposed as Record<string, unknown>} />
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {destructive ? (
            <span data-coach="approval-approve" className="inline-flex">
              <HoldButton onConfirm={() => onDecide(true)}>{busy ? "Recording…" : "Hold to approve"}</HoldButton>
            </span>
          ) : (
            <Button variant="ok" icon="check" disabled={busy} onClick={() => onDecide(true)} data-coach="approval-approve">
              Approve
            </Button>
          )}
          <Button variant="danger-ghost" disabled={busy} onClick={() => onDecide(false)} data-coach="approval-reject">
            Reject
          </Button>
          <Link to="/tasks" className="btn btn-ghost">
            View tasks
          </Link>
          {destructive && <span className="text-xs text-dim">Hold for a second, or press Enter twice.</span>}
        </div>
      </div>
    </article>
  );
}

/** A plain sentence for the commonest actions; a generic one for the rest. */
function describe(approval: Approval): string {
  const p = approval.proposed as Record<string, unknown>;
  switch (approval.tool_name) {
    case "send_email":
    case "gmail_send":
    case "outlook_send":
      return `one email goes to ${String(p.to ?? "the recipient")} right away. A sent email cannot be recalled.`;
    case "save_draft":
    case "gmail_create_draft":
    case "outlook_create_draft":
      return `a draft to ${String(p.to ?? "the recipient")} is saved. Nothing is sent.`;
    case "get_webpage":
      return `one public page (${String(p.url ?? "a web address")}) is read. Nothing is changed or sent.`;
    case "delegate_to_specialist":
      return `${String(p.specialist_name ?? "a specialist")} is asked to do part of this task.`;
    case "remember":
      return "this is saved to memory, where other runs can recall it.";
    default:
      if (approval.side_effect === "destructive") return `it will ${toolAction(approval.tool_name)}, exactly as below. This can't be undone.`;
      if (approval.side_effect === "write") return `it will ${toolAction(approval.tool_name)}, exactly as below.`;
      return `it will ${toolAction(approval.tool_name)}. Nothing is changed.`;
  }
}

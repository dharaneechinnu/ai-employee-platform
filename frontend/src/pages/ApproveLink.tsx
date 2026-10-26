import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Icon } from "../components/icons";
import ProposedAction from "../components/ProposedAction";
import { BrandMark } from "../components/Layout";
import { Button, Chip, ErrorNote, HoldButton, Spinner, StatusChip, ThemeToggle, relativeTime, statusTone } from "../components/ui";
import { ApiError, api, type ApprovalLinkView } from "../lib/api";
import { useAuth } from "../lib/auth";
import { effectLabel, formatDateTime, toolAction } from "../lib/labels";

/**
 * Decide on a paused action from an email or Slack link.
 *
 * Opening the page never decides anything. A mail scanner or a link
 * preview may fetch this URL; only you pressing a button below
 * sends the decision. `?action=` merely highlights the button you
 * clicked in the message.
 */
export default function ApproveLink() {
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const intent = params.get("action");
  const { me } = useAuth();
  const [view, setView] = useState<ApprovalLinkView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);

  useEffect(() => {
    api
      .get<ApprovalLinkView>(`/approval-links/${encodeURIComponent(token)}`)
      .then(setView)
      .catch((err) => setError(err instanceof ApiError ? err.message : "This link could not be opened."));
  }, [token]);

  async function decide(approve: boolean) {
    setError(null);
    setBusy(approve ? "approve" : "reject");
    try {
      setView(await api.post<ApprovalLinkView>(`/approval-links/${encodeURIComponent(token)}/decide`, { approve }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not go through.");
    } finally {
      setBusy(null);
    }
  }

  const needsSignIn = view?.requires_sign_in && !me;
  const next = `/approve/${token}${intent ? `?action=${intent}` : ""}`;

  return (
    <div className="dot-grid flex min-h-screen flex-col items-center px-4 py-10">
      <header className="mb-8 flex w-full max-w-[640px] items-center gap-3">
        <BrandMark />
        <span className="flex-1 font-display font-semibold">Approval request</span>
        <ThemeToggle />
      </header>

      <main className="halo rise w-full max-w-[640px] rounded-3xl p-[1.5px]">
        <div className="flex flex-col gap-5 rounded-[23px] bg-panel p-6 sm:p-8">
          {!view && !error && <Spinner />}
          {!view && error && (
            <div className="flex flex-col items-start gap-4">
              <h1 className="font-display text-2xl font-semibold">This link does not work</h1>
              <ErrorNote message={error} />
              <p className="text-sm text-muted">It may have expired, or been decided already. Open the app to see pending approvals.</p>
              <Link className="btn btn-ghost" to="/approvals">Open approvals</Link>
            </div>
          )}

          {view && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={statusTone(view.side_effect)} dot={false}>{effectLabel(view.side_effect)}</Chip>
                <StatusChip status={view.status} />
                <span className="ml-auto text-xs text-dim">{view.owner_name}</span>
              </div>

              <div className="flex flex-col gap-1.5">
                <h1 className="font-display text-2xl font-semibold leading-tight">
                  Your assistant wants to {toolAction(view.tool_name)}
                </h1>
                {view.task_title && <p className="text-sm text-muted">From: {view.task_title}</p>}
              </div>

              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium uppercase tracking-wider text-dim">Exactly what it will do</span>
                <ProposedAction values={view.proposed as Record<string, unknown>} />
              </div>

              <ErrorNote message={error} />

              {view.status === "pending" ? (
                needsSignIn ? (
                  <div className="flex flex-col gap-3 rounded-xl bg-accent-soft p-4">
                    <p className="text-sm">This link came from Slack, so sign in to decide. The decision is recorded as yours.</p>
                    <Link className="btn btn-primary self-start" to={`/login?next=${encodeURIComponent(next)}`}>
                      <Icon name="lock" size={16} /> Sign in to decide
                    </Link>
                  </div>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-3">
                      {/* The same rule as in the app: anything that can't be
                          undone needs a one-second hold, not a single tap. */}
                      {view.side_effect === "destructive" ? (
                        <HoldButton
                          className={`flex-1 ${intent === "approve" ? "ring-2 ring-ok ring-offset-2 ring-offset-panel" : ""}`}
                          disabled={busy !== null}
                          onConfirm={() => void decide(true)}
                        >
                          {busy === "approve" ? "Approving…" : "Hold to approve"}
                        </HoldButton>
                      ) : (
                        <Button
                          variant="ok"
                          icon="check"
                          className={`flex-1 ${intent === "approve" ? "ring-2 ring-ok ring-offset-2 ring-offset-panel" : ""}`}
                          disabled={busy !== null}
                          onClick={() => void decide(true)}
                        >
                          {busy === "approve" ? "Approving…" : "Approve"}
                        </Button>
                      )}
                      <Button
                        variant="danger-ghost"
                        icon="x"
                        className={`flex-1 ${intent === "reject" ? "ring-2 ring-bad ring-offset-2 ring-offset-panel" : ""}`}
                        disabled={busy !== null}
                        onClick={() => void decide(false)}
                      >
                        {busy === "reject" ? "Rejecting…" : "Reject"}
                      </Button>
                    </div>
                    <p className="text-xs text-dim">
                      {view.acting_as ? `Deciding as ${view.acting_as}. ` : me ? `Deciding as ${me.email}. ` : ""}
                      Expires {relativeTime(view.expires_at)} ({formatDateTime(view.expires_at)}).
                      {view.side_effect === "destructive" && " Hold Approve for a second, or press Enter twice."}
                    </p>
                  </>
                )
              ) : (
                <div className="flex items-center gap-3 rounded-xl border border-line bg-raised p-4" style={{ animation: "pop .45s cubic-bezier(.16,1,.3,1) both" }}>
                  <span className={`flex h-10 w-10 items-center justify-center rounded-full ${view.status === "approved" ? "bg-ok text-ok-on" : "bg-bad text-white"}`}>
                    <Icon name={view.status === "approved" ? "check" : "x"} />
                  </span>
                  <div className="text-sm">
                    {view.status === "approved"
                      ? "Approved. The run has picked up where it paused."
                      : view.status === "rejected"
                        ? "Rejected. The run has stopped and nothing was done."
                        : "This request expired before you decided. Nothing was done."}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

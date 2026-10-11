import { useEffect, useState } from "react";
import { Badge, Button, Card, Empty, ErrorNote, Spinner } from "../components/ui";
import { ApiError, api, type Approval } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Phase 5. The reviewer sees the full proposed action, never a
 * summary: you cannot meaningfully approve what you cannot read.
 */
export default function Approvals() {
  const { org } = useAuth();
  const [items, setItems] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!org) return;
    setItems(await api.get<Approval[]>(`/orgs/${org.id}/approvals`));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function decide(id: string, approve: boolean) {
    if (!org) return;
    setError(null);
    try {
      await api.post(`/orgs/${org.id}/approvals/${id}/${approve ? "approve" : "reject"}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record that.");
    }
  }

  if (!items) return <Spinner />;

  return (
    <div className="space-y-4">
      <h1 className="text-lg">Approvals</h1>
      <ErrorNote message={error} />

      {items.length === 0 ? (
        <Empty
          message="Nothing is waiting for you."
          hint="An AI Employee pauses here before doing anything it cannot undo."
        />
      ) : (
        items.map((approval) => (
          <Card key={approval.id} className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge tone="amber">{approval.tool_name}</Badge>
              <Badge tone={approval.side_effect === "destructive" ? "red" : "gray"}>
                {approval.side_effect}
              </Badge>
              <span className="ml-auto text-xs text-neutral-500">
                expires {new Date(approval.expires_at).toLocaleString()}
              </span>
            </div>

            {approval.task_title && (
              <p className="text-xs text-neutral-500">Task: {approval.task_title}</p>
            )}

            <pre className="max-h-64 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-3 text-xs text-neutral-300">
              {JSON.stringify(approval.proposed, null, 2)}
            </pre>

            <div className="flex gap-2">
              <Button onClick={() => void decide(approval.id, true)}>Approve</Button>
              <Button variant="danger" onClick={() => void decide(approval.id, false)}>
                Reject
              </Button>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}

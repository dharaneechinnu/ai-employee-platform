import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNote, Spinner, statusTone } from "../components/ui";
import { ApiError, api, type PolicyRow, type ToolEntry } from "../lib/api";
import { useAuth } from "../lib/auth";

const SETTINGS = ["auto", "ask", "blocked"] as const;

/**
 * Phase 5. The platform sets a default; a company may move any action
 * looser or stricter. Only the catastrophic blocklist is fixed, and
 * the backend refuses to change it regardless of what this screen
 * sends.
 */
export default function Policies() {
  const { org } = useAuth();
  const [rows, setRows] = useState<PolicyRow[] | null>(null);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!org) return;
    setRows(await api.get<PolicyRow[]>(`/orgs/${org.id}/policies`));
    setTools(await api.get<ToolEntry[]>(`/orgs/${org.id}/tools`));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function setRule(row: PolicyRow, setting: string) {
    if (!org) return;
    setError(null);
    try {
      await api.put(`/orgs/${org.id}/policies`, {
        scope: row.scope,
        scope_value: row.scope_value,
        side_effect: row.side_effect,
        setting,
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    }
  }

  async function reset() {
    if (!org) return;
    await api.post(`/orgs/${org.id}/policies/reset`);
    await load();
  }

  if (!rows) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg">Permissions</h1>
        <div className="ml-auto">
          <Button variant="ghost" onClick={() => void reset()}>
            Reset to defaults
          </Button>
        </div>
      </div>

      <p className="text-xs text-neutral-500">
        Auto runs without asking. Ask pauses for a human. Blocked never runs.
      </p>

      <ErrorNote message={error} />

      <Card className="space-y-2">
        {rows.map((row) => (
          <div
            key={`${row.scope}-${row.scope_value}-${row.side_effect}`}
            className="flex items-center gap-3 border-b border-neutral-800 py-2 last:border-0"
          >
            <div className="w-48">
              <span className="text-sm">{row.scope_value}</span>
              {row.side_effect && (
                <span className="ml-2 text-xs text-neutral-500">{row.side_effect}</span>
              )}
            </div>

            {!row.is_default && <Badge tone="blue">changed</Badge>}

            <div className="ml-auto flex gap-1">
              {SETTINGS.map((setting) => (
                <button
                  key={setting}
                  onClick={() => void setRule(row, setting)}
                  className={`rounded px-2 py-1 text-xs transition ${
                    row.setting === setting
                      ? "bg-neutral-700 text-neutral-100"
                      : "text-neutral-500 hover:text-neutral-300"
                  }`}
                >
                  {setting}
                </button>
              ))}
            </div>
          </div>
        ))}
      </Card>

      <section>
        <h2 className="mb-2 text-sm text-neutral-400">Tools, and what applies to each</h2>
        <Card className="space-y-1.5">
          {tools.map((tool) => (
            <div key={tool.name} className="flex items-center gap-2 text-xs">
              <span className="w-44 truncate">{tool.name}</span>
              <Badge tone={statusTone(tool.side_effect)}>{tool.side_effect}</Badge>
              <Badge tone={statusTone(tool.effective_setting)}>{tool.effective_setting}</Badge>
              {tool.permanently_blocked && <Badge tone="red">never allowed</Badge>}
              <span className="ml-auto truncate text-neutral-600">{tool.reason}</span>
            </div>
          ))}
        </Card>
      </section>
    </div>
  );
}

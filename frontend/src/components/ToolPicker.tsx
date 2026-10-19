import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ConnectionItem, type ToolEntry } from "../lib/api";
import { Icon, type IconName } from "./icons";
import { effectLabel, learnToolLabels, packLabel, toolLabel } from "../lib/labels";
import PermissionChoice from "./PermissionChoice";
import { Chip, statusTone } from "./ui";

/**
 * Choose which tools an AI Employee may use.
 *
 * A tool left unticked is not described to the model at all, so it
 * cannot be talked into using it. Each tool shows what your
 * Permissions say about it, and tools that need an app nobody has
 * connected yet say so here rather than failing mid-run.
 */

const PACKS: Record<string, { label: string; icon: IconName }> = {
  google: { label: "Google Workspace", icon: "mail" },
  microsoft: { label: "Microsoft 365", icon: "mail" },
  email: { label: "Mailbox (IMAP)", icon: "mail" },
  database: { label: "Database", icon: "database" },
  web: { label: "Web", icon: "search" },
  memory: { label: "Memory", icon: "memory" },
  delegation: { label: "Teamwork", icon: "tree" },
};


export function ToolPicker({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [tools, setTools] = useState<ToolEntry[] | null>(null);
  const [connected, setConnected] = useState<Set<string>>(new Set());

  useEffect(() => {
    void Promise.all([
      api.get<ToolEntry[]>(`/me/tools`),
      api.get<ConnectionItem[]>(`/me/connections`).catch(() => [] as ConnectionItem[]),
    ]).then(([catalogue, connections]) => {
      learnToolLabels(catalogue);
      setTools(catalogue.filter((t) => !t.permanently_blocked));
      setConnected(new Set(connections.filter((c) => c.enabled && c.status !== "needs_reconnect").map((c) => c.kind)));
    });
  }, ["me"]);

  if (!tools) return <div className="skeleton h-24 rounded-xl" />;

  const chosen = new Set(value);
  const packs = [...new Set(tools.map((t) => t.pack))];

  function toggle(names: string[], on: boolean) {
    const next = new Set(chosen);
    for (const n of names) {
      if (on) next.add(n);
      else next.delete(n);
    }
    onChange([...next]);
  }

  return (
    <div className="flex flex-col gap-2.5">
      {packs.map((pack) => {
        const inPack = tools.filter((t) => t.pack === pack);
        const meta = PACKS[pack] ?? {
          label: packLabel(pack),
          icon: (pack.startsWith("mcp__") ? "link" : "sparkle") as IconName,
        };
        const needs = inPack.find((t) => t.requires_connection)?.requires_connection;
        const missing = needs && !connected.has(needs);
        const all = inPack.every((t) => chosen.has(t.name));
        return (
          <details key={pack} className="group rounded-xl border border-line bg-raised" open={inPack.some((t) => chosen.has(t.name))}>
            <summary className="flex cursor-pointer list-none items-center gap-2.5 px-3.5 py-2.5">
              <Icon name={meta.icon} size={16} className="text-accent-text" />
              <span className="flex-1 text-sm font-medium">{meta.label}</span>
              {missing && <Chip tone="ask" dot={false}>not connected</Chip>}
              <span className="font-mono text-xs text-dim">
                {inPack.filter((t) => chosen.has(t.name)).length}/{inPack.length}
              </span>
              <Icon name="chevrons" size={14} className="text-dim" />
            </summary>
            <div className="flex flex-col gap-1 border-t border-line px-2 py-2">
              {missing && (
                <p className="px-1.5 pb-1 text-xs text-ask-text">
                  These tools will report "not connected" until an admin connects it on the{" "}
                  <Link to="/connections" className="underline">Connections</Link> page.
                </p>
              )}
              <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-1.5 py-1 text-xs text-muted hover:bg-panel">
                <input type="checkbox" className="accent-[var(--accent)]" checked={all} onChange={(e) => toggle(inPack.map((t) => t.name), e.target.checked)} />
                Select all
              </label>
              {inPack.map((tool) => (
                <div key={tool.name} className="flex flex-col gap-2 rounded-lg px-1.5 py-1.5 hover:bg-panel">
                  <label className="flex cursor-pointer items-start gap-2.5">
                    <input
                      type="checkbox"
                      className="mt-1 accent-[var(--accent)]"
                      checked={chosen.has(tool.name)}
                      onChange={(e) => toggle([tool.name], e.target.checked)}
                    />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[13px] font-medium text-ink" title={tool.name}>{toolLabel(tool.name)}</span>
                        {tool.side_effect !== "read" && (
                          <Chip tone={statusTone(tool.side_effect)} dot={false}>{effectLabel(tool.side_effect)}</Chip>
                        )}
                      </span>
                      <span className="text-xs leading-snug text-dim">{tool.description}</span>
                    </span>
                  </label>
                  {/* The permission for this tool, right where it is chosen.
                      It is a company-wide rule, so it is only offered for
                      tools that are ticked, to keep the list calm. */}
                  {chosen.has(tool.name) && (
                    <div className="pl-[26px]">
                      <PermissionChoice
                        tool={tool}
                        size="sm"
                        onSaved={(setting) =>
                          setTools((current) => current?.map((t) => (t.name === tool.name ? { ...t, effective_setting: setting } : t)) ?? null)
                        }
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </details>
        );
      })}
    </div>
  );
}

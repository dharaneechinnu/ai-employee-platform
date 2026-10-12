import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Chip,
  Empty,
  ErrorNote,
  PageBody,
  PageHeader,
  SearchBox,
  Spinner,
  Tabs,
  statusTone,
  useToast,
} from "../components/ui";
import { ApiError, api, type PolicyRow, type ToolEntry } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Phase 5. The platform sets a default; a company may move any action
 * looser or stricter, per tool or per pack. Only the catastrophic
 * blocklist is fixed, and the backend refuses to change it whatever
 * this screen sends.
 */

type Setting = "auto" | "ask" | "blocked";

const SETTINGS: { key: Setting; label: string }[] = [
  { key: "auto", label: "Auto" },
  { key: "ask", label: "Ask" },
  { key: "blocked", label: "Blocked" },
];

const SELECTED: Record<Setting, string> = {
  auto: "bg-ok-soft text-ok-text shadow-[inset_0_0_0_1px_var(--ok)] font-semibold",
  ask: "bg-ask-soft text-ask-text shadow-[inset_0_0_0_1px_var(--ask)] font-semibold",
  blocked: "bg-bad-soft text-bad-text shadow-[inset_0_0_0_1px_var(--bad)] font-semibold",
};

function Segmented({
  value,
  onChange,
  label,
  disabled,
}: {
  value: Setting;
  onChange: (next: Setting) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <span role="radiogroup" aria-label={label} className="inline-flex rounded-[11px] border border-line bg-sunken p-[3px]">
      {SETTINGS.map((setting) => {
        const on = setting.key === value;
        return (
          <button
            key={setting.key}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => !on && onChange(setting.key)}
            className={`h-[34px] rounded-lg px-3 text-[13px] transition-[background-color,color,box-shadow] duration-200 disabled:cursor-not-allowed ${
              on ? SELECTED[setting.key] : "font-medium text-muted hover:text-ink disabled:hover:text-muted"
            }`}
          >
            {setting.label}
          </button>
        );
      })}
    </span>
  );
}

export default function Policies() {
  const { org } = useAuth();
  const toast = useToast();
  const [rows, setRows] = useState<PolicyRow[] | null>(null);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [pack, setPack] = useState("all");
  const [search, setSearch] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
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

  async function save(
    rule: { scope: "pack" | "tool"; scope_value: string; side_effect: string | null },
    setting: Setting,
    label: string,
  ) {
    if (!org) return;
    setError(null);
    try {
      await api.put(`/orgs/${org.id}/policies`, { ...rule, setting });
      setFlash(label);
      window.setTimeout(() => setFlash((current) => (current === label ? null : current)), 1200);
      toast(`${label} set to ${setting}.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    }
  }

  async function reset() {
    if (!org) return;
    await api.post(`/orgs/${org.id}/policies/reset`);
    toast("Permissions reset to the platform defaults.", "info");
    await load();
  }

  const packs = useMemo(() => Array.from(new Set(tools.map((t) => t.pack))).sort(), [tools]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return tools.filter(
      (tool) =>
        (pack === "all" || tool.pack === pack) &&
        (!term || tool.name.toLowerCase().includes(term) || tool.description.toLowerCase().includes(term)),
    );
  }, [tools, pack, search]);

  if (!rows) {
    return (
      <>
        <PageHeader crumb="Settings" title="Permissions" />
        <Spinner />
      </>
    );
  }

  const packRules = rows.filter((row) => row.scope === "pack");

  return (
    <>
      <PageHeader crumb="Settings" title="Permissions">
        <div className="hidden flex-wrap gap-3.5 text-[13px] text-muted md:flex">
          <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px] bg-ok" />Auto</span>
          <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px] bg-ask" />Ask first</span>
          <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px] bg-bad" />Blocked</span>
        </div>
        <Button variant="ghost" onClick={() => void reset()}>
          Reset to defaults
        </Button>
      </PageHeader>

      <PageBody>
        <p className="rise max-w-3xl text-sm leading-relaxed text-muted">
          New tools start safe: reading runs on its own, writing asks first, anything destructive is blocked until
          you choose otherwise. A rule for one tool beats the rule for its pack. Changes save as you click.
        </p>

        <ErrorNote message={error} />

        <div className="flex flex-wrap items-center gap-2.5">
          <Tabs
            label="Tool pack"
            value={pack}
            onChange={setPack}
            items={[
              { key: "all", label: "All", count: tools.length },
              ...packs.map((p) => ({
                key: p,
                label: p.charAt(0).toUpperCase() + p.slice(1),
                count: tools.filter((t) => t.pack === p).length,
              })),
            ]}
          />
          <SearchBox value={search} onChange={setSearch} placeholder="Search tools" label="Search tools" />
        </div>

        <section className="card rise overflow-hidden">
          <div className="overflow-x-auto">
            <div className="min-w-[860px]">
              <div className="grid grid-cols-[minmax(200px,1.2fr)_110px_120px_250px_minmax(180px,1fr)] items-center gap-3 border-b border-line px-5 py-3 font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
                <span>Tool</span>
                <span>Pack</span>
                <span>Effect</span>
                <span>Setting</span>
                <span>Why</span>
              </div>
              {visible.length === 0 ? (
                <div className="p-6">
                  <Empty message="No tools match" hint="Try another pack or search term." />
                </div>
              ) : (
                visible.map((tool, i) => (
                  <div
                    key={tool.name}
                    className="slide-in grid grid-cols-[minmax(200px,1.2fr)_110px_120px_250px_minmax(180px,1fr)] items-center gap-3 border-b border-line px-5 py-2.5 text-sm transition-colors last:border-0 hover:bg-raised"
                    style={{
                      animationDelay: `${Math.min(i, 12) * 0.03}s`,
                      background: flash === tool.name ? "var(--accent-soft)" : undefined,
                    }}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-mono">{tool.name}</span>
                      <span className="block truncate text-xs text-dim" title={tool.description}>
                        {tool.description}
                      </span>
                    </span>
                    <span className="text-muted">{tool.pack}</span>
                    <span>
                      <Chip tone={statusTone(tool.side_effect)} dot={false}>
                        {tool.side_effect}
                      </Chip>
                    </span>
                    <span>
                      {tool.permanently_blocked ? (
                        <Chip tone="bad">never allowed</Chip>
                      ) : (
                        <Segmented
                          value={tool.effective_setting}
                          label={`${tool.name} setting`}
                          onChange={(setting) =>
                            void save({ scope: "tool", scope_value: tool.name, side_effect: null }, setting, tool.name)
                          }
                        />
                      )}
                    </span>
                    <span className="text-[13px] text-dim">{tool.reason}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>

        {packRules.length > 0 && (
          <section className="flex flex-col gap-3">
            <h2 className="font-display text-[17px] font-semibold">Pack rules</h2>
            <p className="text-[13px] text-muted">Apply to every tool in a pack with that effect, unless a tool has its own rule above.</p>
            <div className="card overflow-hidden">
              {packRules.map((row) => {
                const label = `${row.scope_value}${row.side_effect ? ` · ${row.side_effect}` : ""}`;
                return (
                  <div
                    key={`${row.scope_value}-${row.side_effect}`}
                    className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3 transition-colors last:border-0 hover:bg-raised"
                    style={{ background: flash === label ? "var(--accent-soft)" : undefined }}
                  >
                    <span className="min-w-[180px] flex-1 text-sm">
                      <span className="font-mono">{row.scope_value}</span>
                      {row.side_effect && <span className="ml-2 text-xs text-dim">{row.side_effect}</span>}
                    </span>
                    {!row.is_default && <Chip tone="brand">changed</Chip>}
                    <Segmented
                      value={row.setting}
                      label={`${label} setting`}
                      onChange={(setting) =>
                        void save({ scope: "pack", scope_value: row.scope_value, side_effect: row.side_effect }, setting, label)
                      }
                    />
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </PageBody>
    </>
  );
}

import { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/icons";
import PermissionChoice, { PERMISSION_OPTIONS } from "../components/PermissionChoice";
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
import { effectLabel, learnToolLabels, packLabel, plainReason, toolLabel } from "../lib/labels";

/**
 * Phase 5. The platform sets a default; you may move any action
 * looser or stricter, per tool or per pack. Only the catastrophic
 * blocklist is fixed, and the backend refuses to change it whatever
 * this screen sends.
 */

type Setting = "auto" | "ask" | "blocked";

// The same words as the switch on Connections and in the tool picker.
const SETTINGS = PERMISSION_OPTIONS;

const SETTING_LABEL: Record<Setting, string> = { auto: "always allow", ask: "ask me first", blocked: "blocked" };

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
            className={`seg-btn h-9 rounded-lg px-3 text-[13px] transition-[background-color,color,box-shadow] duration-200 disabled:cursor-not-allowed ${
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
  const toast = useToast();
  const [rows, setRows] = useState<PolicyRow[] | null>(null);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [pack, setPack] = useState("all");
  const [search, setSearch] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setRows(await api.get<PolicyRow[]>(`/me/policies`));
    const catalogue = await api.get<ToolEntry[]>(`/me/tools`);
    learnToolLabels(catalogue);
    setTools(catalogue);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, ["me"]);

  async function save(
    rule: { scope: "pack" | "tool"; scope_value: string; side_effect: string | null },
    setting: Setting,
    label: string,
  ) {
    setError(null);
    try {
      await api.put(`/me/policies`, { ...rule, setting });
      setFlash(label);
      window.setTimeout(() => setFlash((current) => (current === label ? null : current)), 1200);
      toast(`${label}: ${SETTING_LABEL[setting]}.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    }
  }

  async function reset() {
    await api.post(`/me/policies/reset`);
    toast("Permissions reset to the platform defaults.", "info");
    await load();
  }

  const packs = useMemo(() => Array.from(new Set(tools.map((t) => t.pack))).sort(), [tools]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return tools.filter(
      (tool) =>
        (pack === "all" || tool.pack === pack) &&
        (!term ||
          tool.name.toLowerCase().includes(term) ||
          toolLabel(tool.name).toLowerCase().includes(term) ||
          tool.description.toLowerCase().includes(term)),
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

  // Only rules for apps that have tools: a rule for an app with nothing
  // in it is a setting that does nothing.
  const packRules = rows.filter((row) => row.scope === "pack" && packs.includes(row.scope_value));
  const groups = packs
    .map((p) => ({ pack: p, tools: visible.filter((t) => t.pack === p) }))
    .filter((g) => g.tools.length > 0);

  return (
    <>
      <PageHeader crumb="Settings" title="Permissions">
        <Button variant="ghost" onClick={() => void reset()}>
          Reset to defaults
        </Button>
      </PageHeader>

      <PageBody>
        <p className="rise max-w-3xl text-sm leading-relaxed text-muted">
          For every tool, choose <b>Always allow</b> (it runs with no approval), <b>Ask me first</b> (you approve
          each time) or <b>Blocked</b> (it never runs). By default, reading is allowed and sending asks first. Changes
          save as you click.
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
                label: packLabel(p),
                count: tools.filter((t) => t.pack === p).length,
              })),
            ]}
          />
          <SearchBox value={search} onChange={setSearch} placeholder="Search tools" label="Search tools" />
        </div>

        {groups.length === 0 ? (
          <Empty message="No tools match" hint="Try another app or search term." />
        ) : (
          groups.map((group) => (
            <section key={group.pack} className="card rise overflow-hidden" aria-label={packLabel(group.pack)}>
              <h2 className="border-b border-line px-5 py-3 font-display text-[15px] font-semibold">
                {packLabel(group.pack)}
              </h2>
              {group.tools.map((tool) => (
                <div
                  key={tool.name}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2.5 border-b border-line px-5 py-3 transition-colors last:border-0 hover:bg-raised"
                  style={{ background: flash === toolLabel(tool.name) ? "var(--accent-soft)" : undefined }}
                >
                  <div className="flex min-w-[220px] flex-1 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium" title={tool.name}>{toolLabel(tool.name)}</span>
                      {tool.side_effect !== "read" && (
                        <Chip tone={statusTone(tool.side_effect)} dot={false}>
                          {effectLabel(tool.side_effect)}
                        </Chip>
                      )}
                    </span>
                    <span className="text-[13px] leading-snug text-muted">{tool.description}</span>
                    {/* Only worth a line when it is not the default: the tag already says what the default means. */}
                    {!/^platform default/i.test(tool.reason) && (
                      <span className="text-xs text-accent-text">
                        {/^set by (your company|you)\b/i.test(tool.reason) ? "Changed by you" : plainReason(tool.reason)}
                      </span>
                    )}
                  </div>
                  {(
                    <PermissionChoice
                      key={`${tool.name}-${tool.effective_setting}`}
                      tool={tool}
                      onSaved={() => void load()}
                    />
                  )}
                </div>
              ))}
            </section>
          ))
        )}

        {packRules.length > 0 && (
          <details className="group flex flex-col gap-3" data-coach="policy-advanced">
            <summary className="flex cursor-pointer list-none items-center gap-2 font-display text-[15px] font-semibold text-muted hover:text-ink">
              <Icon name="chevrons" size={16} />
              Advanced: rules for a whole app
            </summary>
            <p className="mb-3 mt-2 text-[13px] text-muted">
              One switch for every action of a kind in an app, like "everything Google can't undo". A choice for a single
              action above always wins.
            </p>
            <div className="card overflow-hidden">
              {packRules.map((row) => {
                const label = `${packLabel(row.scope_value)}${row.side_effect ? ` · ${effectLabel(row.side_effect).toLowerCase()}` : ""}`;
                return (
                  <div
                    key={`${row.scope_value}-${row.side_effect}`}
                    className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3 transition-colors last:border-0 hover:bg-raised"
                    style={{ background: flash === label ? "var(--accent-soft)" : undefined }}
                  >
                    <span className="min-w-[180px] flex-1 text-sm">
                      <span className="font-medium">{packLabel(row.scope_value)}</span>
                      {row.side_effect && <span className="ml-2 text-xs text-dim">{effectLabel(row.side_effect)}</span>}
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
          </details>
        )}
      </PageBody>
    </>
  );
}

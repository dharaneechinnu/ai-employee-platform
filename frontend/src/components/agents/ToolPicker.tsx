import { useMemo, useState } from "react";
import type { AgentToolInfo } from "../../lib/api";
import {
  EFFECTS,
  type Effect,
  groupKey,
  groupTitle,
  packLabel,
  packOrder,
  toolBlurb,
  toolLabel,
} from "../../lib/labels";
import { SearchBox, Switch } from "../ui";

const TONE: Record<"ok" | "brand" | "bad", string> = {
  ok: "text-ok-text",
  brand: "text-accent-text",
  bad: "text-bad-text",
};

/**
 * What an agent may do, as switches in plain words. Each line says in
 * one sentence what it lets the agent do, and whether that only looks,
 * changes something, or cannot be undone. `null` means "everything the
 * person already allows" (the old "Everything you allow" chip).
 */
export default function ToolPicker({
  tools,
  value,
  onChange,
  seed,
}: {
  tools: AgentToolInfo[];
  value: string[] | null;
  onChange: (next: string[] | null) => void;
  /** What to start from when automatic is switched off: the tools it has now. */
  seed?: string[];
}) {
  const [query, setQuery] = useState("");
  const all = value === null;
  const on = useMemo(() => new Set(value ?? []), [value]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const map = new Map<string, AgentToolInfo[]>();
    for (const t of tools) {
      const text = `${toolLabel(t.name)} ${toolBlurb(t.name, t.description)} ${t.name}`.toLowerCase();
      if (q && !text.includes(q)) continue;
      const key = groupKey(t.pack);
      map.set(key, [...(map.get(key) ?? []), t]);
    }
    return [...map.entries()].sort(
      ([, a], [, b]) => packOrder(a[0].pack) - packOrder(b[0].pack),
    );
  }, [tools, query]);

  function set(names: string[], enable: boolean) {
    const next = new Set(on);
    for (const n of names) enable ? next.add(n) : next.delete(n);
    onChange(tools.map((t) => t.name).filter((n) => next.has(n)));
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-3 rounded-xl border border-line bg-panel px-3 py-2.5">
          <Switch
            checked={all}
            label="Choose what it can do from its instructions"
            onChange={(next) => onChange(next ? null : [...(seed ?? [])])}
          />
          <div className="min-w-0">
            <p className="text-[14px] font-medium">Choose automatically</p>
            <p className="text-[13px] text-muted">
              {all
                ? "It gets what its instructions call for, like searching the web or updating a sheet. Turn this off to pick by hand."
                : "Off: it can only do what you switch on below."}
            </p>
          </div>
        </div>
      </div>

      {!all && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[13px] text-muted">
              {on.size === 0 ? "Nothing is on yet." : `${on.size} thing${on.size === 1 ? "" : "s"} switched on.`}
            </p>
            <div className="w-full sm:w-64">
              <SearchBox
                value={query}
                onChange={setQuery}
                label="Search the things it may do"
                placeholder="Search, for example sheet or email"
              />
            </div>
          </div>

          {groups.length === 0 && <p className="text-[13.5px] text-muted">Nothing matches “{query}”.</p>}

          <div className="flex flex-col gap-3">
            {groups.map(([key, list]) => {
              const names = list.map((t) => t.name);
              const count = names.filter((n) => on.has(n)).length;
              const app = list.find((t) => t.needs_app)?.needs_app ?? null;
              return (
                <section key={key} className="rounded-xl border border-line">
                  <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
                    <h4 className="font-display text-[14px] font-semibold">{groupTitle(key)}</h4>
                    {app && <span className="text-[12px] text-dim">Needs {packLabel(app)} connected</span>}
                    <span className="ml-auto text-[12.5px] text-dim">
                      {count} of {names.length} on
                    </span>
                    <button
                      type="button"
                      className="text-[12.5px] text-accent-text underline-offset-2 hover:underline"
                      onClick={() => set(names, count !== names.length)}
                    >
                      {count === names.length ? "Turn all off" : "Turn all on"}
                    </button>
                  </header>
                  <ul className="flex flex-col">
                    {list.map((t) => {
                      const effect = (t.side_effect in EFFECTS ? t.side_effect : "write") as Effect;
                      const meta = EFFECTS[effect];
                      const checked = on.has(t.name);
                      return (
                        <li
                          key={t.name}
                          className="flex items-start gap-3 border-b border-line px-3 py-2.5 last:border-b-0"
                        >
                          <Switch
                            checked={checked}
                            label={toolLabel(t.name)}
                            onChange={(next) => set([t.name], next)}
                          />
                          <button
                            type="button"
                            tabIndex={-1}
                            className="min-w-0 flex-1 cursor-pointer text-left"
                            onClick={() => set([t.name], !checked)}
                          >
                            <span className="flex flex-wrap items-baseline gap-x-2">
                              <span className="text-[14px] font-medium">{toolLabel(t.name)}</span>
                              <span className={`text-[12px] ${TONE[meta.tone]}`} title={meta.hint}>
                                {meta.label}
                              </span>
                            </span>
                            <span className="block text-[13px] text-muted">{toolBlurb(t.name, t.description)}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { COMMANDS, PAGE_SHORTCUTS, isTyping, keysFor, type Command } from "../lib/commands";
import { Icon } from "./icons";

/**
 * The keyboard layer: Ctrl/Cmd+K opens a palette, "?" opens the sheet of
 * every shortcut, "G" then a letter jumps to a screen, "N" starts a new
 * chat and "/" goes to the page's search box.
 *
 * Single keys stay quiet while someone is typing in a box, and while a
 * dialog is open, so typing "n" into a message never leaves the page.
 * Ctrl/Cmd+K is the one exception: it works from inside a box too.
 */
type View = "none" | "palette" | "sheet";

const GO_WINDOW_MS = 1200;

export default function CommandPalette() {
  const navigate = useNavigate();
  const [view, setView] = useState<View>("none");
  const awaitingGo = useRef<number | null>(null);

  useEffect(() => {
    function clearGo() {
      if (awaitingGo.current !== null) window.clearTimeout(awaitingGo.current);
      awaitingGo.current = null;
    }

    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        clearGo();
        setView((v) => (v === "palette" ? "none" : "palette"));
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      if (isTyping(e.target) || view !== "none") return;
      // Another dialog (a modal, a coach tip) owns the keyboard.
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;

      const k = e.key.toLowerCase();

      if (awaitingGo.current !== null) {
        clearGo();
        const hit = COMMANDS.find((c) => c.go === k);
        if (hit) {
          e.preventDefault();
          navigate(hit.to);
        }
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setView("sheet");
      } else if (k === "g") {
        awaitingGo.current = window.setTimeout(clearGo, GO_WINDOW_MS);
      } else if (e.key === "/") {
        const box = document.querySelector<HTMLInputElement>("[data-search]");
        if (box) {
          e.preventDefault();
          box.focus();
        }
      } else {
        const hit = COMMANDS.find((c) => c.key === k);
        if (hit) {
          e.preventDefault();
          navigate(hit.to);
        }
      }
    }

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearGo();
    };
  }, [navigate, view]);

  if (view === "palette") {
    return (
      <Palette
        onClose={() => setView("none")}
        onPick={(c) => {
          setView("none");
          navigate(c.to);
        }}
      />
    );
  }
  if (view === "sheet") return <Sheet onClose={() => setView("none")} />;
  return null;
}

function Keys({ keys }: { keys: string[] }) {
  return (
    <span className="ml-auto flex shrink-0 gap-1">
      {keys.map((k, i) => (
        <kbd key={`${k}-${i}`} className="kbd">
          {k}
        </kbd>
      ))}
    </span>
  );
}

function Backdrop({ onClose, children, label }: { onClose: () => void; children: React.ReactNode; label: string }) {
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    return () => before?.focus?.();
  }, []);

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/50 px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div role="dialog" aria-modal="true" aria-label={label} className="float-surface w-full max-w-[600px] overflow-hidden">
        {children}
      </div>
    </div>
  );
}

function Palette({ onClose, onPick }: { onClose: () => void; onPick: (c: Command) => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? COMMANDS.filter((c) => c.label.toLowerCase().includes(q)) : COMMANDS;
  }, [query]);

  const active = Math.min(index, Math.max(matches.length - 1, 0));

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex(matches.length ? (active + 1) % matches.length : 0);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex(matches.length ? (active - 1 + matches.length) % matches.length : 0);
    } else if (e.key === "Enter" && matches[active]) {
      e.preventDefault();
      onPick(matches[active]);
    }
  }

  const groups = (["Actions", "Go to"] as const)
    .map((g) => ({ g, items: matches.filter((c) => c.group === g) }))
    .filter((x) => x.items.length > 0);

  return (
    <Backdrop onClose={onClose} label="Command palette">
      <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
        <Icon name="search" size={18} className="text-dim" />
        <input
          ref={input}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={matches[active] ? `cmd-${matches[active].id}` : undefined}
          aria-label="Search actions and screens"
          placeholder="Search actions and screens"
          className="min-w-0 flex-1 border-0 bg-transparent text-[16px] text-ink outline-none placeholder:text-dim"
        />
        <kbd className="kbd">Esc</kbd>
      </div>

      <div id="palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
        {groups.length === 0 && <p className="px-3 py-6 text-center text-sm text-dim">Nothing matches “{query}”.</p>}
        {groups.map(({ g, items }) => (
          <div key={g}>
            <div className="px-3 pb-1 pt-2 text-[11.5px] font-medium uppercase tracking-[0.08em] text-dim">{g}</div>
            {items.map((c) => {
              const on = matches[active]?.id === c.id;
              return (
                <div
                  key={c.id}
                  id={`cmd-${c.id}`}
                  role="option"
                  aria-selected={on}
                  onMouseEnter={() => setIndex(matches.indexOf(c))}
                  onClick={() => onPick(c)}
                  className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-[14.5px] ${on ? "card-on" : ""}`}
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-raised text-ink">
                    <Icon name={c.icon} size={15} />
                  </span>
                  {c.label}
                  <Keys keys={keysFor(c)} />
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="flex gap-4 border-t border-line px-4 py-2.5 text-[12.5px] text-dim">
        <span>
          <kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> move
        </span>
        <span>
          <kbd className="kbd">Enter</kbd> open
        </span>
        <span className="ml-auto">
          <kbd className="kbd">?</kbd> all shortcuts
        </span>
      </div>
    </Backdrop>
  );
}

function Sheet({ onClose }: { onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" || e.key === "?") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = [
    ...PAGE_SHORTCUTS,
    ...COMMANDS.filter((c) => keysFor(c).length > 0).map((c) => ({
      label: c.group === "Go to" ? `Go to ${c.label}` : c.label,
      keys: keysFor(c),
    })),
  ];

  return (
    <Backdrop onClose={onClose} label="Keyboard shortcuts">
      <div ref={panel} tabIndex={-1} className="max-h-[70vh] overflow-y-auto p-5 outline-none">
        <h2 className="font-display text-xl font-semibold">Keyboard shortcuts</h2>
        <p className="mb-3 mt-1 text-[13px] text-dim">Single keys pause while you type in a box.</p>
        <ul className="stagger">
          {rows.map((r) => (
            <li key={r.label} className="flex items-center gap-3 border-t border-line py-2 text-sm">
              {r.label}
              <Keys keys={r.keys} />
            </li>
          ))}
        </ul>
      </div>
    </Backdrop>
  );
}

import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { DOCKS, DOCK_LABEL, type Dock, dockForPoint } from "../lib/dock";
import { useAuth } from "../lib/auth";
import { BrandMark, type BrandState } from "./BrandMark";
import { Icon, type IconName } from "./icons";
import InboxBell from "./InboxBell";
import { Avatar } from "./ui";

/**
 * Written out in full, never built with a template string.
 *
 * Tailwind scans the source for literal class names and tree-shakes
 * any rule in @layer components it cannot find used. `rail-menu-${dock}`
 * is invisible to that scan, so the rule is dropped and the menu lands
 * at its static position — off the bottom of the screen.
 */
const MENU_SIDE: Record<Dock, string> = {
  left: "rail-menu-left",
  right: "rail-menu-right",
  bottom: "rail-menu-bottom",
};

const ZONE_SIDE: Record<Dock, string> = {
  left: "drop-zone-left",
  right: "drop-zone-right",
  bottom: "drop-zone-bottom",
};

const DOCK_GLYPH: Record<Dock, string> = {
  left: "dock-glyph-left",
  right: "dock-glyph-right",
  bottom: "dock-glyph-bottom",
};

interface RailItem {
  to: string;
  label: string;
  icon: IconName;
  /** Starts a new visual group above this item. */
  startsGroup?: boolean;
}

// One person owns everything, so every item is shown to everyone.
const ITEMS: RailItem[] = [
  { to: "/chat", label: "Chat", icon: "chat" },
  { to: "/agents", label: "AI Agents", icon: "employees" },
  { to: "/approvals", label: "Approvals", icon: "approvals" },

  { to: "/memory", label: "Memory", icon: "memory", startsGroup: true },
  { to: "/agents?tab=cost", label: "Models and cost", icon: "wallet" },

  { to: "/connections", label: "Connections", icon: "link", startsGroup: true },
  { to: "/providers", label: "AI keys", icon: "providers" },
  { to: "/policies", label: "Permissions", icon: "lock" },
  { to: "/notifications", label: "Notifications", icon: "bell" },
];

/** AI Agents and Models and cost share a page: the tab decides which one is lit. */
function itemActive(to: string, isActive: boolean, pathname: string, search: string): boolean {
  const onCost = pathname === "/agents" && new URLSearchParams(search).get("tab") === "cost";
  if (to === "/agents?tab=cost") return onCost;
  if (to === "/agents") return isActive && !onCost;
  return isActive;
}

export default function Rail({
  dock,
  setDock,
  running,
  waiting,
}: {
  dock: Dock;
  setDock: (next: Dock) => void;
  running: number;
  waiting: number;
}) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();

  const [dragging, setDragging] = useState(false);
  const [target, setTarget] = useState<Dock>(dock);
  const [menuOpen, setMenuOpen] = useState(false);
  const moved = useRef(false);

  const horizontal = dock === "bottom";

  const state: BrandState = waiting > 0 ? "waiting" : running > 0 ? "running" : "idle";

  // Dragging the mark moves the rail. There is no separate grip icon:
  // one more icon in a column of icons reads as another destination,
  // and it was the first thing to be mistaken for a button.
  function onPointerDown(e: React.PointerEvent) {
    if (e.button !== 0) return;
    moved.current = false;
    const startX = e.clientX;
    const startY = e.clientY;
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);

    const onMove = (move: PointerEvent) => {
      if (!moved.current && Math.hypot(move.clientX - startX, move.clientY - startY) < 6) return;
      // Below six pixels this is still a click, not a drag. Without the
      // threshold a slightly shaky press on the mark would throw the
      // menu across the screen instead of going home.
      moved.current = true;
      setDragging(true);
      setTarget(dockForPoint(move.clientX, move.clientY));
    };

    const onUp = (up: PointerEvent) => {
      el.releasePointerCapture(up.pointerId);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      if (moved.current) setDock(dockForPoint(up.clientX, up.clientY));
      else navigate("/chat");
      setDragging(false);
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
  }

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: Event) => {
      if (!(e.target as HTMLElement).closest?.("[data-rail-menu]")) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <>
      {/* The drop zones only exist mid-drag, so they never sit in front
          of the page catching stray clicks. */}
      {dragging && (
        <div className="pointer-events-none fixed inset-0 z-[60]">
          {DOCKS.map((zone) => (
            <div
              key={zone}
              className={`drop-zone ${ZONE_SIDE[zone]} ${target === zone ? "is-on" : ""}`}
            >
              <span className="drop-zone-label">{DOCK_LABEL[zone]}</span>
            </div>
          ))}
        </div>
      )}

      <nav
        aria-label="Main menu"
        data-dock={dock}
        className={`rail ${dragging ? "is-dragging" : ""}`}
      >
        <button
          type="button"
          onPointerDown={onPointerDown}
          onContextMenu={(e) => {
            e.preventDefault();
            setMenuOpen(true);
          }}
          className="rail-grip"
          aria-label="Home. Drag to move this menu."
          title="Drag to move this menu"
        >
          <BrandMark size={horizontal ? 26 : 28} state={state} />
        </button>

        <button
          type="button"
          className="rail-new"
          onClick={() => navigate("/chat")}
          data-rail-label="New chat"
        >
          <Icon name="plus" size={18} strokeWidth={2.6} />
          <span className="sr-only">New chat</span>
        </button>

        <div className="rail-items">
          {ITEMS.map((item) => (
            <div key={item.to} className="contents">
              {item.startsGroup && <span className="rail-divider" aria-hidden="true" />}
              <NavLink
                to={item.to}
                className={({ isActive }) => `rail-link ${itemActive(item.to, isActive, pathname, search) ? "active" : ""}`}
                data-rail-label={item.label}
                data-coach={item.to === "/approvals" ? "nav-approvals" : undefined}
              >
                <Icon name={item.icon} size={19} />
                <span className="sr-only">{item.label}</span>
                {item.to === "/chat" && running > 0 && (
                  <span className="rail-dot live-run" aria-label={`${running} running`} />
                )}
                {item.to === "/approvals" && waiting > 0 && (
                  <b className="rail-count live-ask">{waiting}</b>
                )}
              </NavLink>
            </div>
          ))}
        </div>

        <div className="rail-end" data-rail-menu>
          {/* Before the account button, because it is the thing people
              come back to the screen to check. */}
          <InboxBell dock={dock} />

          <button
            type="button"
            className="rail-link"
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            data-rail-label={me?.username ? `@${me.username}` : (me?.email ?? "Account")}
          >
            <Avatar name={me?.full_name || me?.username || me?.email || "?"} size={26} />
            <span className="sr-only">Account and menu position</span>
          </button>

          {menuOpen && (
            <div role="menu" className={`rail-menu ${MENU_SIDE[dock]}`}>
              {/* No company to switch between: the account is the
                  scope. What used to be a switcher is simply who you
                  are signed in as. */}
              {me && (
                <div className="rail-menu-org">
                  <Avatar name={me.full_name || me.username || me.email} size={28} rounded="rounded-[9px]" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium">
                      {me.full_name || me.username || me.email}
                    </span>
                    <span className="text-xs text-muted">{me.username ? `@${me.username}` : me.email}</span>
                  </span>
                </div>
              )}

              {/* Dragging is the quick way; this is the one that works
                  with a keyboard, and the only way to discover that the
                  menu moves at all. */}
              <div className="rail-menu-section">Menu position</div>
              {DOCKS.map((zone) => (
                <button
                  key={zone}
                  type="button"
                  role="menuitemradio"
                  aria-checked={dock === zone}
                  className={`rail-menu-item ${dock === zone ? "is-on" : ""}`}
                  onClick={() => {
                    setDock(zone);
                    setMenuOpen(false);
                  }}
                >
                  <span className={`dock-glyph ${DOCK_GLYPH[zone]}`} aria-hidden="true" />
                  {DOCK_LABEL[zone]}
                  {dock === zone && <Icon name="check" size={15} className="ml-auto" />}
                </button>
              ))}

              <span className="rail-menu-rule" />
              <div className="rail-menu-who">{me?.email}</div>
              <button type="button" className="rail-menu-item" onClick={() => void logout()}>
                <Icon name="out" size={16} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </nav>
    </>
  );
}

import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useActivity } from "../lib/activity";
import { useAuth, useIsAdmin } from "../lib/auth";
import { Icon, type IconName } from "./icons";
import { Avatar } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  adminOnly: boolean;
}

/**
 * Navigation grouped by job. "Settings" is labelled admin, so a member
 * who does not see it knows why rather than wondering what is missing.
 */
const SECTIONS: { title: string; note?: string; items: NavItem[] }[] = [
  {
    title: "Work",
    items: [
      { to: "/tasks", label: "Tasks", icon: "tasks", adminOnly: false },
      { to: "/employees", label: "AI Employees", icon: "employees", adminOnly: false },
      { to: "/approvals", label: "Approvals", icon: "approvals", adminOnly: true },
    ],
  },
  {
    title: "Team",
    items: [
      { to: "/memory", label: "Memory", icon: "memory", adminOnly: false },
      { to: "/members", label: "Members", icon: "members", adminOnly: false },
    ],
  },
  {
    title: "Settings",
    note: "admin",
    items: [
      { to: "/connections", label: "Connections", icon: "link", adminOnly: true },
      { to: "/providers", label: "Providers", icon: "providers", adminOnly: true },
      { to: "/policies", label: "Permissions", icon: "lock", adminOnly: true },
      { to: "/notifications", label: "Notifications", icon: "bell", adminOnly: true },
    ],
  },
];

export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="relative inline-flex shrink-0 items-center justify-center rounded-[10px]"
      style={{
        width: size,
        height: size,
        background: "linear-gradient(135deg,var(--accent),var(--accent2) 60%,var(--spark))",
        boxShadow: "0 8px 20px -10px var(--glow)",
      }}
    >
      <span className="orbit absolute -inset-1.5">
        <span
          className="absolute left-1/2 top-0 h-[5px] w-[5px] -translate-x-1/2 rounded-full"
          style={{ background: "var(--spark)", boxShadow: "0 0 8px var(--spark)" }}
        />
      </span>
      <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: "var(--on-accent)" }} />
    </span>
  );
}

export default function Layout() {
  const { me, org, logout, switchOrg } = useAuth();
  const isAdmin = useIsAdmin();
  const navigate = useNavigate();
  const { running, waiting } = useActivity(org?.id, isAdmin);
  const location = useLocation();

  // On phones the menu is a drawer. It closes on every navigation, on
  // Escape and on a tap outside, and the page behind it cannot scroll.
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [location.pathname, location.search]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [menuOpen]);

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* Phones and small tablets: a slim bar instead of the full menu,
          so every page starts with its own content. */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2.5 border-b border-line bg-side px-4 lg:hidden">
        <Link to="/tasks" className="flex h-11 items-center gap-2.5 text-ink no-underline">
          <BrandMark size={28} />
          <span className="font-display text-[15px] font-semibold">AI Employees</span>
        </Link>
        <span className="flex-1" />
        {isAdmin && waiting > 0 && (
          <Link
            to="/approvals"
            className="live-ask flex h-11 items-center gap-1.5 rounded-full bg-ask px-3.5 text-[13px] font-semibold text-ask-on no-underline"
          >
            <Icon name="approvals" size={16} />
            {waiting} waiting
          </Link>
        )}
        <button
          type="button"
          className="icon-btn"
          aria-label="Open menu"
          aria-expanded={menuOpen}
          aria-controls="app-menu"
          onClick={() => setMenuOpen(true)}
        >
          <Icon name="menu" />
        </button>
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px] lg:hidden" aria-hidden="true" onClick={() => setMenuOpen(false)} />
      )}

      <aside
        id="app-menu"
        aria-label="Menu"
        className={`fixed inset-y-0 left-0 z-50 flex w-[min(300px,86vw)] flex-col gap-1 overflow-y-auto border-r border-line bg-side px-3 py-[18px] transition-[transform,background-color] duration-300 lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:w-[248px] lg:shrink-0 lg:translate-x-0 ${
          menuOpen ? "translate-x-0 shadow-2xl" : "-translate-x-full max-lg:invisible"
        }`}
      >
        <div className="flex items-center gap-2.5 px-2 pb-3.5 pt-1">
          <BrandMark />
          <span className="flex-1 font-display text-base font-semibold">AI Employees</span>
          <button type="button" className="icon-btn lg:hidden" aria-label="Close menu" onClick={() => setMenuOpen(false)}>
            <Icon name="x" />
          </button>
        </div>

        {me && org && (
          <label className="relative flex items-center gap-2.5 rounded-xl border border-line bg-panel px-2.5 py-2 transition-colors hover:border-accent-line">
            <Avatar name={org.name} size={30} rounded="rounded-[9px]" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-sm font-medium">{org.name}</span>
              <span className="text-xs capitalize text-accent-text">{org.role}</span>
            </span>
            {me.organizations.length > 1 && <Icon name="chevrons" size={16} className="text-muted" />}
            {/* The native select sits on top, invisible, so switching
                companies keeps full keyboard and screen-reader support. */}
            <select
              aria-label="Switch company"
              value={org.id}
              onChange={(e) => switchOrg(e.target.value)}
              disabled={me.organizations.length < 2}
              className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-default"
            >
              {me.organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <button type="button" className="btn btn-primary mb-0.5 mt-2.5 w-full" onClick={() => navigate("/tasks?new=1")}>
          <Icon name="plus" size={16} strokeWidth={2.4} />
          New task
        </button>

        <nav aria-label="Workspace" className="flex flex-col gap-0.5">
          {SECTIONS.map((section) => {
            const items = section.items.filter((item) => isAdmin || !item.adminOnly);
            if (!items.length) return null;
            return (
              <div key={section.title} className="flex flex-col gap-0.5">
                <div className="flex justify-between px-3 pb-1.5 pt-4 font-mono text-xs uppercase tracking-[0.12em] text-dim">
                  {section.title}
                  {section.note && <span>{section.note}</span>}
                </div>
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                  >
                    <Icon name={item.icon} />
                    <span className="flex-1">{item.label}</span>
                    {item.to === "/tasks" && running > 0 && (
                      <span className="live-run h-[7px] w-[7px] rounded-full bg-run" aria-label={`${running} running`} />
                    )}
                    {item.to === "/approvals" && waiting > 0 && (
                      <b className="live-ask flex h-5 min-w-[22px] items-center justify-center rounded-full bg-ask px-1.5 font-mono text-xs font-semibold text-ask-on">
                        {waiting}
                      </b>
                    )}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="mt-auto flex items-center gap-2.5 border-t border-line px-1.5 pt-3 lg:mt-auto">
          <Avatar name={me?.full_name || me?.email || "?"} size={32} />
          <span className="min-w-0 flex-1 truncate text-[13px] text-muted">{me?.email}</span>
          <button
            type="button"
            onClick={() => void logout()}
            aria-label="Sign out"
            title="Sign out"
            className="nav-link w-11 justify-center px-0"
          >
            <Icon name="out" />
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col" style={{ background: "var(--hero)" }}>
        <Outlet />
      </main>
    </div>
  );
}

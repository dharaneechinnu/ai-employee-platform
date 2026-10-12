import { NavLink, Outlet, useNavigate } from "react-router-dom";
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
      { to: "/providers", label: "Providers", icon: "providers", adminOnly: true },
      { to: "/policies", label: "Permissions", icon: "lock", adminOnly: true },
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
        background: "linear-gradient(135deg,var(--accent),var(--accent2))",
        boxShadow: "0 8px 20px -10px var(--glow)",
      }}
    >
      <span className="orbit absolute -inset-1.5">
        <span
          className="absolute left-1/2 top-0 h-[5px] w-[5px] -translate-x-1/2 rounded-full"
          style={{ background: "var(--accent2)", boxShadow: "0 0 8px var(--accent2)" }}
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

  return (
    <div className="flex min-h-screen flex-wrap">
      <aside className="flex w-full flex-col gap-1 border-b border-line bg-side px-3 py-[18px] transition-colors duration-500 lg:sticky lg:top-0 lg:h-screen lg:w-[248px] lg:shrink-0 lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5 px-2 pb-3.5 pt-1">
          <BrandMark />
          <span className="font-display text-base font-semibold">AI Employees</span>
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

        <button type="button" className="btn btn-gold mb-0.5 mt-2.5 w-full" onClick={() => navigate("/tasks?new=1")}>
          <Icon name="plus" size={16} strokeWidth={2.4} />
          New task
        </button>

        <nav aria-label="Workspace" className="flex flex-col gap-0.5">
          {SECTIONS.map((section) => {
            const items = section.items.filter((item) => isAdmin || !item.adminOnly);
            if (!items.length) return null;
            return (
              <div key={section.title} className="flex flex-col gap-0.5">
                <div className="flex justify-between px-3 pb-1.5 pt-4 font-mono text-[11px] uppercase tracking-[0.12em] text-dim">
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
            className="nav-link w-10 justify-center px-0"
          >
            <Icon name="out" />
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-[999_1_560px] flex-col" style={{ background: "var(--hero)" }}>
        <Outlet />
      </main>
    </div>
  );
}

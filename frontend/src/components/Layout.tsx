import { NavLink, Outlet } from "react-router-dom";
import { useAuth, useIsAdmin } from "../lib/auth";
import { Badge } from "./ui";

/** Nav entries an admin sees but a member does not. */
const NAV = [
  { to: "/tasks", label: "Tasks", adminOnly: false },
  { to: "/employees", label: "AI Employees", adminOnly: false },
  { to: "/approvals", label: "Approvals", adminOnly: true },
  { to: "/memory", label: "Memory", adminOnly: false },
  { to: "/providers", label: "Providers", adminOnly: true },
  { to: "/policies", label: "Permissions", adminOnly: true },
  { to: "/members", label: "Members", adminOnly: false },
];

export default function Layout() {
  const { me, org, logout, switchOrg } = useAuth();
  const isAdmin = useIsAdmin();

  return (
    <div className="min-h-screen">
      <header className="border-b border-neutral-800 bg-neutral-900">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <span className="text-sm font-medium">AI Employees</span>

          {me && me.organizations.length > 0 && (
            <select
              value={org?.id ?? ""}
              onChange={(e) => switchOrg(e.target.value)}
              className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs"
            >
              {me.organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          )}

          {org && <Badge tone={isAdmin ? "blue" : "gray"}>{org.role}</Badge>}

          <div className="ml-auto flex items-center gap-3 text-xs text-neutral-400">
            <span>{me?.email}</span>
            <button onClick={() => void logout()} className="hover:text-neutral-200">
              Sign out
            </button>
          </div>
        </div>

        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-2">
          {NAV.filter((item) => isAdmin || !item.adminOnly).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `whitespace-nowrap rounded px-3 py-1 text-sm transition ${
                  isActive
                    ? "bg-neutral-800 text-neutral-100"
                    : "text-neutral-400 hover:text-neutral-200"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}

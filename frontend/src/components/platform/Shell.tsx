import { useEffect, useState, type ReactNode } from "react";
import { useTheme } from "../../lib/theme";
import { Icon, type IconName } from "../icons";
import { StaffBadge, StaffLogo } from "./bits";

/**
 * The frame around every staff screen: the strip that says who is
 * signed in and that changes are logged, the header, and the side menu
 * (a drop-down on a phone).
 */

export type View = "overview" | "signin" | "access" | "audit";

const NAV: { heading?: string; items: { key: View; label: string; icon: IconName | "sliders" | "signin" }[] }[] = [
  { items: [{ key: "overview", label: "Overview and people", icon: "people" }] },
  {
    heading: "Settings",
    items: [
      { key: "signin", label: "Sign-in and AI", icon: "signin" },
      { key: "access", label: "Service access", icon: "sliders" },
    ],
  },
  { heading: "Records", items: [{ key: "audit", label: "Audit log", icon: "tasks" }] },
];

function NavIcon({ name }: { name: IconName | "sliders" | "signin" }) {
  if (name === "signin") {
    return (
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3" />
      </svg>
    );
  }
  if (name === "sliders") {
    return (
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12" />
        <circle cx="16" cy="6" r="2" />
        <circle cx="10" cy="12" r="2" />
        <circle cx="18" cy="18" r="2" />
      </svg>
    );
  }
  if (name === "tasks") {
    return (
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />
      </svg>
    );
  }
  return <Icon name={name} size={17} strokeWidth={2} />;
}

const LOG_ICON = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />
  </svg>
);

/** The one thing the customer app never has: who is signed in, and that it is all logged. */
function StaffStrip({ email }: { email: string | null }) {
  return (
    <div className="flex min-h-[30px] flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 text-xs sm:min-h-9 sm:px-6 sm:text-[12.5px]" style={{ background: "var(--strip-bg)", color: "var(--strip-text)" }}>
      <div className="flex min-w-0 items-center gap-2">
        <Icon name="shield" size={14} strokeWidth={2} className="text-[color:var(--strip-icon)]" />
        <span className="font-semibold tracking-[0.02em]">Staff console</span>
        {email && (
          <span className="hidden min-w-0 truncate sm:inline" style={{ color: "var(--strip-muted)" }}>
            <span aria-hidden="true" className="mr-2 opacity-70">·</span>
            Signed in as {email}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2" style={{ color: "var(--strip-muted)" }}>
        <span className="hidden sm:inline">{LOG_ICON}</span>
        <span className="sm:hidden">Changes are logged</span>
        <span className="hidden sm:inline">Everything you change here is written to the audit log</span>
      </div>
    </div>
  );
}

function ThemeButton({ wide = false }: { wide?: boolean }) {
  const { theme, toggle } = useTheme();
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return wide ? (
    <button type="button" onClick={toggle} className="flex h-11 items-center gap-2.5 rounded-[10px] px-3 text-left font-medium text-muted hover:bg-raised">
      <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
      {label}
    </button>
  ) : (
    <button type="button" onClick={toggle} aria-label={label} title={label} className="inline-flex h-10 w-10 items-center justify-center rounded-[10px] border border-line bg-panel text-muted hover:bg-raised">
      <Icon name={theme === "dark" ? "sun" : "moon"} size={17} strokeWidth={2} />
    </button>
  );
}

function NavList({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) {
  return (
    <>
      {NAV.map((group, i) => (
        <div key={i} className="flex flex-col gap-0.5">
          {group.heading && <div className="px-3 pb-1.5 text-xs font-semibold text-dim">{group.heading}</div>}
          {group.items.map((item) => (
            <a
              key={item.key}
              href={`#${item.key}`}
              aria-current={view === item.key ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                onNavigate(item.key);
              }}
              className={`flex h-11 items-center gap-2.5 rounded-[10px] px-3 no-underline transition-colors lg:h-10 ${view === item.key ? "bg-accent-soft font-semibold text-accent-text" : "font-medium text-muted hover:bg-raised hover:text-ink"}`}
            >
              <NavIcon name={item.icon} />
              {item.label}
            </a>
          ))}
        </div>
      ))}
    </>
  );
}

export function StaffShell({
  email,
  view,
  onNavigate,
  onSignOut,
  children,
}: {
  email: string | null;
  view: View;
  onNavigate: (v: View) => void;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menu]);

  return (
    <>
      <StaffStrip email={email} />
      <header className="relative flex h-[60px] items-center justify-between gap-4 border-b border-line bg-panel px-4 sm:h-16 sm:px-6">
        <div className="flex items-center gap-2.5 sm:gap-3">
          <StaffLogo size={28} />
          <span className="text-base font-semibold sm:text-[17px]">Baton</span>
          <StaffBadge />
        </div>
        <div className="hidden items-center gap-2 lg:flex">
          <ThemeButton />
          <button type="button" onClick={onSignOut} className="h-10 rounded-[10px] border border-line bg-panel px-3.5 font-medium text-ink hover:bg-raised">
            Sign out
          </button>
        </div>
        <button
          type="button"
          aria-label={menu ? "Close menu" : "Open menu"}
          aria-expanded={menu}
          onClick={() => setMenu((v) => !v)}
          className="inline-flex h-11 w-11 items-center justify-center rounded-[10px] border border-line bg-raised text-ink lg:hidden"
        >
          <Icon name={menu ? "x" : "menu"} size={18} strokeWidth={2} />
        </button>
        {menu && (
          <div className="absolute inset-x-0 top-full z-40 flex flex-col gap-4 border-b border-line bg-panel p-4 shadow-lift lg:hidden">
            <NavList
              view={view}
              onNavigate={(v) => {
                setMenu(false);
                onNavigate(v);
              }}
            />
            <div className="flex flex-col gap-0.5 border-t border-line pt-3">
              {email && <div className="px-3 pb-1 text-xs text-dim">Signed in as {email}</div>}
              <ThemeButton wide />
              <button type="button" onClick={onSignOut} className="flex h-11 items-center gap-2.5 rounded-[10px] px-3 text-left font-medium text-muted hover:bg-raised">
                <Icon name="out" size={17} />
                Sign out
              </button>
            </div>
          </div>
        )}
      </header>

      <div className="mx-auto flex max-w-[1392px] gap-8 px-4 pb-12 pt-[18px] sm:px-6 sm:pt-7">
        <nav aria-label="Staff console" className="hidden w-[232px] shrink-0 flex-col gap-5 lg:flex">
          <NavList view={view} onNavigate={onNavigate} />
          <div className="mt-2 flex flex-col gap-2 rounded-xl border border-line bg-panel p-3.5">
            <div className="flex items-center gap-2 text-[13px] font-semibold">
              <Icon name="lock" size={15} strokeWidth={2} className="text-accent-text" />
              Private by design
            </div>
            <p className="text-[12.5px] leading-normal text-muted">
              Chats, memory, tasks, AI keys and sign-in tokens never reach this console. You see counts and yes or no only.
            </p>
          </div>
        </nav>
        <main className="flex min-w-0 flex-1 flex-col gap-6">{children}</main>
      </div>
    </>
  );
}

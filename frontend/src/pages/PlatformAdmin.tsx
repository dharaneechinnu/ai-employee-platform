import { useCallback, useEffect, useMemo, useState } from "react";
import { InviteDialog, LinkDialog, SuspendDialog } from "../components/platform/Dialogs";
import { ActivityRow, HeadlineCards } from "../components/platform/Overview";
import { PeopleSection, type PeopleActions } from "../components/platform/People";
import { PersonDrawer } from "../components/platform/PersonDrawer";
import { AuditLog } from "../components/platform/AuditLog";
import { ScreenTitle, useCopy } from "../components/platform/bits";
import { ServiceAccess } from "../components/platform/ServiceAccess";
import { StaffShell, type View } from "../components/platform/Shell";
import { StaffSignIn } from "../components/platform/SignIn";
import { SignInAndAI } from "../components/platform/SignInAndAI";
import { call, setPlatformToken, setupLinkFor, type OAuthApp, type Overview, type Person, type Provider, type StaffMe } from "../components/platform/api";
import { expiresToday, longDay, nameOf } from "../components/platform/format";
import { Icon } from "../components/icons";
import { useToast } from "../components/ui";
import { ApiError } from "../lib/api";

/**
 * The staff console ("Platform Admin").
 *
 * Kept entirely separate from the customer app: a different token type,
 * its own sign-in, and no shared session. A customer's token is rejected
 * here, whoever holds it. The dark strip at the very top says who is
 * signed in and that every change is logged.
 *
 * Note what is absent. There is no way to read a customer's chats,
 * memory, tasks, credentials or API keys, because no endpoint returns
 * them. These screens only ever show counts, dates and yes or no.
 */

const VIEWS: View[] = ["overview", "signin", "access", "audit"];

function viewFromHash(): View {
  const hash = window.location.hash.replace("#", "") as View;
  return VIEWS.includes(hash) ? hash : "overview";
}

export default function PlatformAdmin() {
  const [signedIn, setSignedIn] = useState(false);

  return (
    <div className="staff min-h-screen bg-bg text-[14px] leading-[1.45] text-ink">
      {signedIn ? (
        <Console
          onSignOut={() => {
            setPlatformToken(null);
            setSignedIn(false);
          }}
        />
      ) : (
        <StaffSignIn onSignedIn={() => setSignedIn(true)} />
      )}
    </div>
  );
}

function Console({ onSignOut }: { onSignOut: () => void }) {
  const toast = useToast();
  const copy = useCopy();
  const [view, setView] = useState<View>(viewFromHash);
  const [me, setMe] = useState<StaffMe | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [apps, setApps] = useState<OAuthApp[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Setup links made in this visit. Only a link's fingerprint is stored
  // on the server, so once this tab closes a lost link means a new one.
  const [links, setLinks] = useState<Map<string, string>>(new Map());
  const [busy, setBusy] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [shownLink, setShownLink] = useState<{ name: string; link: string } | null>(null);
  const [suspending, setSuspending] = useState<Person | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [drawerVersion, setDrawerVersion] = useState(0);
  const [auditSearch, setAuditSearch] = useState("");

  const refresh = useCallback(async () => {
    const [o, p] = await Promise.all([call<Overview>("/overview"), call<Person[]>("/people")]);
    setOverview(o);
    // Newest first: the people who just joined are the ones staff look for.
    setPeople([...p].reverse());
  }, []);

  const loadProviders = useCallback(async () => setProviders(await call<Provider[]>("/providers")), []);

  useEffect(() => {
    call<StaffMe>("/me").then(setMe).catch(() => onSignOut());
    refresh().catch(() => setError("Could not load people. Check the server and try again."));
    loadProviders().catch(() => toast("Could not load the AI providers.", "bad"));
    call<OAuthApp[]>("/oauth-apps").then(setApps).catch(() => toast("Could not load the sign-in apps.", "bad"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function navigate(next: View) {
    window.history.replaceState(null, "", next === "overview" ? window.location.pathname : `#${next}`);
    setView(next);
    setOpenId(null);
    window.scrollTo(0, 0);
  }

  async function makeLink(p: Person) {
    const known = links.get(p.id);
    if (known) {
      await copy(known, "Setup link copied.");
      return;
    }
    setBusy(p.id);
    try {
      const made = await call<{ setup_token: string }>(`/people/${p.id}/setup-link`, {});
      const link = setupLinkFor(made.setup_token);
      setLinks(new Map(links).set(p.id, link));
      setShownLink({ name: nameOf(p), link });
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not make a new link.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function restore(p: Person) {
    setBusy(p.id);
    try {
      await call(`/people/${p.id}/restore`, {});
      toast(`${nameOf(p)} restored. They can sign in again.`);
      await refresh();
      setDrawerVersion((v) => v + 1);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not restore the account.", "bad");
    } finally {
      setBusy(null);
    }
  }

  const act: PeopleActions = {
    open: (p) => setOpenId(p.id),
    suspend: setSuspending,
    restore: (p) => void restore(p),
    link: (p) => void makeLink(p),
    invite: () => setInviting(true),
  };

  const providerNames = useMemo(() => Object.fromEntries((providers ?? []).map((p) => [p.key, p.display_name])), [providers]);
  const expiringToday = (people ?? []).filter((p) => expiresToday(p)).length;

  const invite = (
    <button type="button" onClick={() => setInviting(true)} className="inline-flex h-11 items-center gap-2 rounded-[10px] bg-accent px-4 font-semibold text-accent-on transition-opacity hover:opacity-90 sm:h-[42px]">
      <Icon name="plus" size={16} strokeWidth={2.2} />
      Invite someone
    </button>
  );

  return (
    <StaffShell email={me?.email ?? null} view={view} onNavigate={navigate} onSignOut={onSignOut}>
      {view === "overview" && (
        <>
          <div className="hidden sm:block">
            <ScreenTitle title="Overview" action={invite}>
              How Baton is doing today, {longDay(new Date())}. Counts only.
            </ScreenTitle>
          </div>
          <div className="flex items-end justify-between gap-3 sm:hidden">
            <div>
              <h1 className="text-[26px] font-semibold tracking-[-0.02em]">People</h1>
              <p className="mt-1 text-[13px] text-muted">Counts and yes or no only. Never their content.</p>
            </div>
            <button type="button" aria-label="Invite someone" onClick={() => setInviting(true)} className="inline-flex h-11 w-11 items-center justify-center rounded-[10px] bg-accent text-accent-on">
              <Icon name="plus" size={18} strokeWidth={2.2} />
            </button>
          </div>
          {error && <p className="rounded-xl bg-bad-soft px-4 py-3 text-bad-text">{error}</p>}
          {overview ? (
            <>
              <HeadlineCards data={overview} expiringToday={expiringToday} />
              <ActivityRow data={overview} providers={providers} apps={apps} onOpenSettings={() => navigate("signin")} />
            </>
          ) : (
            !error && <div className="skeleton h-[140px] rounded-[14px]" />
          )}
          {people ? <PeopleSection people={people} act={act} links={new Set(links.keys())} busy={busy} /> : !error && <div className="skeleton h-[420px] rounded-2xl" />}
        </>
      )}

      {view === "signin" && <SignInAndAI apps={apps} providers={providers} onApps={setApps} onProviders={loadProviders} />}
      {view === "access" && <ServiceAccess onOpenSignIn={() => navigate("signin")} />}
      {view === "audit" && <AuditLog providers={providerNames} initialSearch={auditSearch} />}

      {openId && (
        <PersonDrawer
          personId={openId}
          providers={providers}
          version={drawerVersion}
          onClose={() => setOpenId(null)}
          onSuspend={setSuspending}
          onRestore={(p) => void restore(p)}
          onOpenAccess={() => navigate("access")}
          onOpenAudit={(search) => {
            setAuditSearch(search);
            navigate("audit");
          }}
        />
      )}

      {inviting && (
        <InviteDialog
          onClose={() => setInviting(false)}
          onCreated={(made) => {
            setInviting(false);
            setLinks(new Map(links).set(made.id, made.link));
            setShownLink({ name: made.name, link: made.link });
            void refresh();
          }}
        />
      )}
      {shownLink && <LinkDialog name={shownLink.name} link={shownLink.link} onClose={() => setShownLink(null)} />}
      {suspending && (
        <SuspendDialog
          person={suspending}
          onClose={() => setSuspending(null)}
          onDone={(updated) => {
            setSuspending(null);
            toast(`${nameOf(updated)} suspended. Nothing of theirs was deleted.`, "info");
            void refresh();
            setDrawerVersion((v) => v + 1);
          }}
        />
      )}
    </StaffShell>
  );
}

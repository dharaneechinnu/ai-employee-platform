import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, onSessionExpired, refresh, setAccessToken, type Me, type Org } from "./api";

interface AuthState {
  me: Me | null;
  org: Org | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  acceptInvite: (token: string, password: string, fullName?: string) => Promise<void>;
  logout: () => Promise<void>;
  switchOrg: (orgId: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

const ORG_KEY = "active_org_id";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [orgId, setOrgId] = useState<string | null>(() => localStorage.getItem(ORG_KEY));
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    const profile = await api.get<Me>("/auth/me");
    setMe(profile);

    // Fall back to the first company if the remembered one is gone:
    // membership can be revoked between sessions.
    const stored = localStorage.getItem(ORG_KEY);
    const valid = profile.organizations.find((o) => o.id === stored);
    const next = valid?.id ?? profile.organizations[0]?.id ?? null;
    setOrgId(next);
    if (next) localStorage.setItem(ORG_KEY, next);
  }, []);

  useEffect(() => {
    // On a cold load the access token is gone (it was only in memory),
    // but the refresh cookie may still be valid, so try to resume.
    void (async () => {
      if (await refresh()) {
        try {
          await loadMe();
        } catch {
          setMe(null);
        }
      }
      setLoading(false);
    })();

    onSessionExpired(() => {
      setMe(null);
      setAccessToken(null);
    });
  }, [loadMe]);

  const login = useCallback(
    async (email: string, password: string) => {
      const body = await api.post<{ access_token: string }>("/auth/login", { email, password });
      setAccessToken(body.access_token);
      await loadMe();
    },
    [loadMe],
  );

  const acceptInvite = useCallback(
    async (token: string, password: string, fullName?: string) => {
      const body = await api.post<{ access_token: string }>("/auth/accept-invite", {
        token,
        password,
        full_name: fullName || null,
      });
      setAccessToken(body.access_token);
      await loadMe();
    },
    [loadMe],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setAccessToken(null);
      setMe(null);
      localStorage.removeItem(ORG_KEY);
    }
  }, []);

  const switchOrg = useCallback((next: string) => {
    setOrgId(next);
    localStorage.setItem(ORG_KEY, next);
  }, []);

  const org = useMemo(
    () => me?.organizations.find((o) => o.id === orgId) ?? null,
    [me, orgId],
  );

  const value = useMemo(
    () => ({ me, org, loading, login, acceptInvite, logout, switchOrg }),
    [me, org, loading, login, acceptInvite, logout, switchOrg],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/** True when the signed-in user is an admin of the active company. */
export function useIsAdmin(): boolean {
  return useAuth().org?.role === "admin";
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, onSessionExpired, refresh, setAccessToken, type Me } from "./api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  /** `identifier` is an email address or a username. */
  login: (identifier: string, password: string) => Promise<void>;
  /** Create an account; the person is signed in at once. */
  register: (input: { username: string; email: string; password: string; full_name?: string }) => Promise<void>;
  /** Set a password from the link that created this account. */
  completeSetup: (token: string, password: string, fullName?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    setMe(await api.get<Me>("/auth/me"));
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
    async (identifier: string, password: string) => {
      const body = await api.post<{ access_token: string }>("/auth/login", { identifier, password });
      setAccessToken(body.access_token);
      await loadMe();
    },
    [loadMe],
  );

  const register = useCallback(
    async (input: { username: string; email: string; password: string; full_name?: string }) => {
      const body = await api.post<{ access_token: string }>("/auth/register", {
        ...input,
        full_name: input.full_name || undefined,
      });
      setAccessToken(body.access_token);
      await loadMe();
    },
    [loadMe],
  );

  const completeSetup = useCallback(
    async (token: string, password: string, fullName?: string) => {
      const body = await api.post<{ access_token: string }>("/auth/setup", {
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
    }
  }, []);

  const value = useMemo(
    () => ({ me, loading, login, register, completeSetup, logout }),
    [me, loading, login, register, completeSetup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

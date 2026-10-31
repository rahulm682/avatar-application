import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

import {
  api,
  clearAccessToken,
  refreshSession,
  setSessionExpiredHandler,
} from "./api";
import type { Profile } from "./api";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthValue {
  status: Status;
  user: Profile | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => void;
  setUser: (user: Profile) => void;
  reloadUser: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUserState] = useState<Profile | null>(null);

  const clearSession = useCallback(() => {
    clearAccessToken();
    setUserState(null);
    setStatus("anonymous");
    queryClient.clear();
  }, [queryClient]);

  // When the page opens there is no access token yet, only (maybe) the refresh cookie.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!(await refreshSession())) {
        if (!cancelled) setStatus("anonymous");
        return;
      }
      try {
        const me = await api.getMe();
        if (!cancelled) {
          setUserState(me);
          setStatus("authenticated");
        }
      } catch {
        if (!cancelled) setStatus("anonymous");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(clearSession);
    return () => setSessionExpiredHandler(null);
  }, [clearSession]);

  const login = useCallback(async (email: string, password: string) => {
    const profile = await api.login(email, password);
    setUserState(profile);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const reloadUser = useCallback(async () => {
    setUserState(await api.getMe());
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      status,
      user,
      login,
      logout,
      clearSession,
      setUser: setUserState,
      reloadUser,
    }),
    [status, user, login, logout, clearSession, reloadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (value === null)
    throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError, setCsrfToken } from '../api/client';
import type { Me } from '../api/types';

interface AuthState {
  me: Me | null;
  loading: boolean;
  /** Why the bootstrap probe failed, when it failed for a reason worth showing: a Google
   *  account Cloudflare Access let through but the household does not know. */
  error: string | null;
  /** The local admin password. Reachable only on the LAN — the tunnel's front door
   *  refuses this path outright (see docs/remote-access.md). */
  breakGlassLogin: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

interface LogoutResult {
  access_logout_url: string | null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((m: Me | null) => {
    setMe(m);
    setCsrfToken(m?.csrf_token ?? '');
  }, []);

  // Behind Cloudflare Access this probe *is* the sign-in: the edge has already proved the
  // visitor owns a Google address, so /auth/me answers with a session rather than a form.
  const probe = useCallback(async () => {
    try {
      apply(await api.get<Me>('/auth/me'));
      setError(null);
    } catch (e) {
      apply(null);
      // 401 is just "not signed in" — silent. A 403 means Access vouched for an address
      // the household has never heard of, and the message names it, which is the one
      // thing that lets the parent fix it.
      setError(e instanceof ApiError && e.status === 403 ? e.message : null);
    }
  }, [apply]);

  useEffect(() => {
    void probe().finally(() => setLoading(false));
  }, [probe]);

  const breakGlassLogin = useCallback(
    async (username: string, password: string) => {
      apply(await api.post<Me>('/auth/login', { username, password }));
      setError(null);
    },
    [apply],
  );

  const logout = useCallback(async () => {
    let accessLogout: string | null = null;
    try {
      accessLogout = (await api.post<LogoutResult>('/auth/logout')).access_logout_url;
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
    apply(null);
    // Dropping our own cookie is not a sign-out while the edge session stands; the next
    // page load would sign the same Google account straight back in.
    if (accessLogout) window.location.href = accessLogout;
  }, [apply]);

  const value = useMemo(
    () => ({ me, loading, error, breakGlassLogin, logout, refresh: probe }),
    [me, loading, error, breakGlassLogin, logout, probe],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError, NetworkError, setCsrfToken } from '../api/client';
import type { DevUser, Me } from '../api/types';

interface AuthState {
  me: Me | null;
  loading: boolean;
  /** Why the bootstrap probe failed, when it failed for a reason worth showing. */
  error: string | null;
  /** True only when Access vouched for a Google account the household does not know —
   *  the one case where ending the edge session and picking another account helps. A
   *  network failure also sets `error`, and offering it there would just fail again. */
  canSwitchAccount: boolean;
  /** The probe never got an HTTP status back. Retrying it as another `fetch` cannot help:
   *  the usual cause is the edge redirecting to Google, and only a top-level navigation
   *  can complete that round trip. The Login screen offers one instead of a retry. */
  unreachable: boolean;
  /** The household, when the dev stack's passwordless sign-in is on; null in every
   *  deployed configuration, where the route does not exist. */
  devUsers: DevUser[] | null;
  /** The local admin password. Reachable only on the LAN — the tunnel's front door
   *  refuses this path outright (see docs/remote-access.md). */
  breakGlassLogin: (username: string, password: string) => Promise<void>;
  /** Become the named user, no password. Dev stack only. */
  devLogin: (userId: string) => Promise<void>;
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
  const [canSwitchAccount, setCanSwitch] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const [devUsers, setDevUsers] = useState<DevUser[] | null>(null);

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
      setCanSwitch(false);
      setUnreachable(false);
    } catch (e) {
      apply(null);
      // 401 is just "not signed in" — silent. A 403 means Access vouched for an address
      // the household has never heard of, and the message names it, which is the one
      // thing that lets the parent fix it. A NetworkError produced no status at all, so
      // saying "not signed in" would be a guess — and was, when a stale service worker
      // served the shell offline and every call died on a cross-origin redirect.
      const notAMember = e instanceof ApiError && e.status === 403;
      setCanSwitch(notAMember);
      setUnreachable(e instanceof NetworkError);
      if (e instanceof NetworkError) {
        setError('Could not reach ChoreKeeper. Check your connection, then try again.');
      } else {
        setError(notAMember ? e.message : null);
      }
      // Is this the dev stack? Asking the route is the whole test — it 404s unless DEV_AUTH
      // is on, so no separate mode endpoint has to exist (and be kept honest) in production.
      try {
        setDevUsers(await api.get<DevUser[]>('/auth/dev/users'));
      } catch {
        setDevUsers(null);
      }
    }
  }, [apply]);

  useEffect(() => {
    void probe().finally(() => setLoading(false));
  }, [probe]);

  const breakGlassLogin = useCallback(
    async (username: string, password: string) => {
      apply(await api.post<Me>('/auth/login', { username, password }));
      setError(null);
      setCanSwitch(false);
      setUnreachable(false);
    },
    [apply],
  );

  const devLogin = useCallback(
    async (userId: string) => {
      apply(await api.post<Me>('/auth/dev/login', { user_id: userId }));
      setError(null);
      setCanSwitch(false);
      setUnreachable(false);
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
    () => ({
      me,
      loading,
      error,
      canSwitchAccount,
      unreachable,
      devUsers,
      breakGlassLogin,
      devLogin,
      logout,
      refresh: probe,
    }),
    [
      me,
      loading,
      error,
      canSwitchAccount,
      unreachable,
      devUsers,
      breakGlassLogin,
      devLogin,
      logout,
      probe,
    ],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError, setCsrfToken } from '../api/client';
import type { Me } from '../api/types';

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string, totp?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((m: Me | null) => {
    setMe(m);
    setCsrfToken(m?.csrf_token ?? '');
  }, []);

  useEffect(() => {
    api
      .get<Me>('/auth/me')
      .then(apply)
      .catch(() => apply(null))
      .finally(() => setLoading(false));
  }, [apply]);

  const login = useCallback(
    async (username: string, password: string, totp?: string) => {
      const m = await api.post<Me>('/auth/login', {
        username,
        password,
        totp_code: totp || undefined,
      });
      apply(m);
    },
    [apply],
  );

  const refresh = useCallback(async () => {
    try {
      apply(await api.get<Me>('/auth/me'));
    } catch {
      apply(null);
    }
  }, [apply]);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
    apply(null);
  }, [apply]);

  const value = useMemo(
    () => ({ me, loading, login, logout, refresh }),
    [me, loading, login, logout, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}

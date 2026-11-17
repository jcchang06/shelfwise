import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import * as authApi from '../api/auth';
import { setSessionExpiredHandler } from '../api/client';
import { AuthContext, type AuthState, type AuthStatus } from './AuthContext';

/**
 * Owns "who is logged in". On first load it restores a stored session (refresh token ->
 * access token -> /auth/me/) before protected pages render.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>(() =>
    authApi.hasStoredSession() ? 'checking' : 'anonymous',
  );
  const [user, setUser] = useState<authApi.User | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const endSession = useCallback(
    (expired: boolean) => {
      authApi.logout();
      queryClient.clear(); // never show one session's cached data to the next
      setUser(null);
      setStatus('anonymous');
      setSessionExpired(expired);
    },
    [queryClient],
  );

  useEffect(() => {
    setSessionExpiredHandler(() => endSession(true));
    return () => setSessionExpiredHandler(null);
  }, [endSession]);

  useEffect(() => {
    if (status !== 'checking') return;
    let cancelled = false;
    authApi
      .fetchCurrentUser()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus('authenticated');
      })
      .catch(() => {
        // Expired tokens already ran the session-expired handler. For anything else
        // (e.g. the server is down) fall back to the login page, which shows the error
        // on the next attempt.
        if (!cancelled) setStatus((current) => (current === 'checking' ? 'anonymous' : current));
      });
    return () => {
      cancelled = true;
    };
  }, [status]);

  const login = useCallback(async (email: string, password: string) => {
    await authApi.login(email, password);
    const me = await authApi.fetchCurrentUser();
    setUser(me);
    setSessionExpired(false);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(() => endSession(false), [endSession]);

  const value = useMemo<AuthState>(
    () => ({ status, user, sessionExpired, login, logout }),
    [status, user, sessionExpired, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

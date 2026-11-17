/**
 * Where the JWTs live (see docs/implementation-notes.md, T-1).
 *
 * - The access token is kept in memory only, so it never touches storage and is gone when
 *   the tab closes.
 * - The refresh token is kept in localStorage so a session survives reloads. httpOnly
 *   cookies aren't an option while the frontend and API are on different onrender.com
 *   subdomains (onrender.com is a public suffix, so the cookie would be third-party).
 *   XSS exposure is limited by a strict CSP, no third-party scripts and React escaping.
 *
 * Storage access is wrapped in try/catch: it can throw in private windows or when site
 * data is blocked, and the app must still work (it just won't remember the session).
 */

const REFRESH_KEY = 'shelfwise.refreshToken';

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getRefreshToken(): string | null {
  try {
    return window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setRefreshToken(token: string): void {
  try {
    window.localStorage.setItem(REFRESH_KEY, token);
  } catch {
    // Storage unavailable: the session lasts until the tab closes.
  }
}

export function clearTokens(): void {
  accessToken = null;
  try {
    window.localStorage.removeItem(REFRESH_KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}

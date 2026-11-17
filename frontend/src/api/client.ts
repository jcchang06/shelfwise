/**
 * Single entry point for HTTP calls to the Shelfwise API. Every request in the app goes
 * through here (CLAUDE.md), so the base URL, auth header, token refresh, timeout and error
 * shape live in one place.
 *
 * Auth flow:
 * - Requests carry the in-memory access token.
 * - On a 401, one shared refresh runs (concurrent requests wait for the same one), the
 *   rotated refresh token is saved, and the request is retried once.
 * - If the refresh fails, tokens are cleared and the session-expired handler runs (the
 *   AuthProvider sends the user to /login with a message).
 */

import { trackRequest } from './serverWaking';
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from './tokens';

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api';

/** Long enough to ride out a free-tier cold start (~1 minute). */
export const REQUEST_TIMEOUT_MS = 90_000;

export type ApiErrorKind = 'http' | 'network' | 'timeout';

export class ApiError extends Error {
  readonly status: number; // 0 for network failures and timeouts
  readonly body: unknown;
  readonly kind: ApiErrorKind;

  constructor(status: number, body: unknown, kind: ApiErrorKind = 'http') {
    super(kind === 'http' ? `API request failed with status ${status}` : `API request ${kind}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.kind = kind;
  }
}

export interface RequestOptions {
  /** Send the access token and refresh on 401. False for login and refresh itself. */
  auth?: boolean;
  timeoutMs?: number;
}

let onSessionExpired: (() => void) | null = null;

/** The AuthProvider registers this to react when a session can't be refreshed. */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

async function rawFetch<T>(path: string, init: RequestInit, timeoutMs: number): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await trackRequest(
      fetch(`${API_BASE_URL}${path}`, { ...init, headers, signal: controller.signal }),
    );
  } catch {
    throw new ApiError(0, null, controller.signal.aborted ? 'timeout' : 'network');
  } finally {
    clearTimeout(timer);
  }

  const isJson = response.headers.get('Content-Type')?.includes('application/json') ?? false;
  const body: unknown = isJson ? await response.json() : null;
  if (!response.ok) {
    throw new ApiError(response.status, body);
  }
  return body as T;
}

interface RefreshResponse {
  access: string;
  refresh?: string; // present because refresh tokens rotate
}

let refreshInFlight: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  try {
    const tokens = await rawFetch<RefreshResponse>(
      '/auth/token/refresh/',
      { method: 'POST', body: JSON.stringify({ refresh }) },
      REQUEST_TIMEOUT_MS,
    );
    setAccessToken(tokens.access);
    if (tokens.refresh) setRefreshToken(tokens.refresh);
    return tokens.access;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 400 || error.status === 401)) {
      clearTokens(); // expired or invalid: this session is over
      return null;
    }
    throw error; // network trouble: keep the tokens and let the caller show an error
  }
}

/** One refresh at a time; everyone waiting gets the same result. Null = session is gone. */
export function refreshAccessToken(): Promise<string | null> {
  // The reset is chained with .finally() rather than a finally block inside doRefresh:
  // when there's no refresh token, doRefresh finishes synchronously, and an inner
  // finally would clear refreshInFlight *before* this assignment, leaving a settled
  // promise cached forever. A chained .finally always runs after the assignment.
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function withAuth(init: RequestInit): RequestInit {
  const token = getAccessToken();
  if (!token) return init;
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  return { ...init, headers };
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  { auth = true, timeoutMs = REQUEST_TIMEOUT_MS }: RequestOptions = {},
): Promise<T> {
  if (!auth) return rawFetch<T>(path, init, timeoutMs);

  // After a reload there's no access token yet; refresh first rather than spending a
  // round trip (possibly a cold start) on a request that's sure to 401.
  if (!getAccessToken() && getRefreshToken()) {
    await refreshAccessToken();
  }

  try {
    return await rawFetch<T>(path, withAuth(init), timeoutMs);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error;
    const token = await refreshAccessToken();
    if (!token) {
      onSessionExpired?.();
      throw error;
    }
    try {
      return await rawFetch<T>(path, withAuth(init), timeoutMs);
    } catch (retryError) {
      if (retryError instanceof ApiError && retryError.status === 401) {
        clearTokens();
        onSessionExpired?.();
      }
      throw retryError;
    }
  }
}

export function apiGet<T>(path: string, options?: RequestOptions): Promise<T> {
  return apiFetch<T>(path, { method: 'GET' }, options);
}

export function apiPost<T>(path: string, data: unknown, options?: RequestOptions): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: JSON.stringify(data) }, options);
}

export function apiPatch<T>(path: string, data: unknown, options?: RequestOptions): Promise<T> {
  return apiFetch<T>(path, { method: 'PATCH', body: JSON.stringify(data) }, options);
}

export function apiDelete(path: string, options?: RequestOptions): Promise<null> {
  return apiFetch<null>(path, { method: 'DELETE' }, options);
}

export interface HealthResponse {
  status: 'ok';
}

export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/health/', { auth: false });
}

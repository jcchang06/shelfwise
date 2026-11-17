import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

import { API_BASE_URL } from '../api/client';

/** Mock API for tests. Unhandled requests fail the test (see setup.ts). */
export const server = setupServer();

export const api = (path: string) => `${API_BASE_URL}${path}`;

export const ME = { id: 1, email: 'reader@example.com', date_joined: '2026-11-16T00:00:00Z' };

/** Handlers for a working login: token pair, refresh (rotating) and /me. */
export function authHandlers() {
  return [
    http.post(api('/auth/token/'), () =>
      HttpResponse.json({ access: 'access-1', refresh: 'refresh-1' }),
    ),
    http.post(api('/auth/token/refresh/'), () =>
      HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' }),
    ),
    http.get(api('/auth/me/'), () => HttpResponse.json(ME)),
  ];
}

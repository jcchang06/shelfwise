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

export const EMPTY_STATS = {
  year: new Date().getFullYear(),
  totals: { pages: 0, finished: 0, dnf: 0, average_rating: null },
  pages_per_month: Array.from({ length: 12 }, (_, i) => ({
    month: `${new Date().getFullYear()}-${String(i + 1).padStart(2, '0')}`,
    pages: 0,
    dnf_pages: 0,
  })),
  books_per_year: [],
  genre_mix: [],
  rating_distribution: [1, 2, 3, 4, 5].map((stars) => ({ stars, books: 0 })),
};

const emptyPage = { count: 0, next: null, previous: null, results: [] };

/**
 * An empty dashboard (nothing being read, no logs, zero stats) for tests that land on
 * /dashboard without caring about it. Kept separate from authHandlers so tests that
 * mock /api/shelf/ themselves aren't shadowed.
 */
export function dashboardHandlers() {
  return [
    http.get(api('/shelf/'), () => HttpResponse.json(emptyPage)),
    http.get(api('/logs/'), () => HttpResponse.json(emptyPage)),
    http.get(api('/stats/'), () => HttpResponse.json(EMPTY_STATS)),
  ];
}

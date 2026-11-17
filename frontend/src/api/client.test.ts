import { delay, http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import { api, server } from '../test/server';
import { ApiError, apiFetch, apiGet, apiPost, setSessionExpiredHandler } from './client';
import { getAccessToken, getRefreshToken, setAccessToken, setRefreshToken } from './tokens';

describe('apiFetch basics', () => {
  it('prefixes the base URL and parses JSON', async () => {
    server.use(http.get(api('/health/'), () => HttpResponse.json({ status: 'ok' })));
    await expect(apiGet('/health/', { auth: false })).resolves.toEqual({ status: 'ok' });
  });

  it('throws ApiError with status and body on non-2xx', async () => {
    server.use(
      http.post(api('/shelf/'), () => HttpResponse.json({ rating: ['Nope.'] }, { status: 400 })),
    );
    const error = await apiPost('/shelf/', {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, kind: 'http', body: { rating: ['Nope.'] } });
  });

  it('handles empty 204 bodies', async () => {
    server.use(http.delete(api('/logs/1/'), () => new HttpResponse(null, { status: 204 })));
    await expect(apiFetch('/logs/1/', { method: 'DELETE' })).resolves.toBeNull();
  });

  it('reports network failures as kind "network"', async () => {
    server.use(http.get(api('/health/'), () => HttpResponse.error()));
    const error = await apiGet('/health/', { auth: false }).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 0, kind: 'network' });
  });

  it('reports slow responses past the timeout as kind "timeout"', async () => {
    server.use(
      http.get(api('/health/'), async () => {
        await delay(200);
        return HttpResponse.json({ status: 'ok' });
      }),
    );
    const error = await apiGet('/health/', { auth: false, timeoutMs: 20 }).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 0, kind: 'timeout' });
  });
});

describe('auth and refresh', () => {
  it('sends the access token', async () => {
    setAccessToken('access-1');
    server.use(
      http.get(api('/auth/me/'), ({ request }) =>
        request.headers.get('Authorization') === 'Bearer access-1'
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({}, { status: 401 }),
      ),
    );
    await expect(apiGet('/auth/me/')).resolves.toEqual({ ok: true });
  });

  it('refreshes on 401, saves the rotated refresh token and retries once', async () => {
    setAccessToken('expired');
    setRefreshToken('refresh-1');
    server.use(
      http.post(api('/auth/token/refresh/'), async ({ request }) => {
        expect(await request.json()).toEqual({ refresh: 'refresh-1' });
        return HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' });
      }),
      http.get(api('/shelf/'), ({ request }) =>
        request.headers.get('Authorization') === 'Bearer access-2'
          ? HttpResponse.json({ results: [] })
          : HttpResponse.json({ detail: 'expired' }, { status: 401 }),
      ),
    );

    await expect(apiGet('/shelf/')).resolves.toEqual({ results: [] });
    expect(getAccessToken()).toBe('access-2');
    expect(getRefreshToken()).toBe('refresh-2');
  });

  it('shares one refresh between concurrent 401s', async () => {
    setAccessToken('expired');
    setRefreshToken('refresh-1');
    const refresh = vi.fn(() => HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' }));
    server.use(
      http.post(api('/auth/token/refresh/'), async () => {
        await delay(20);
        return refresh();
      }),
      http.get(api('/shelf/'), ({ request }) =>
        request.headers.get('Authorization') === 'Bearer access-2'
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({}, { status: 401 }),
      ),
    );

    await Promise.all([apiGet('/shelf/'), apiGet('/shelf/'), apiGet('/shelf/')]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('refreshes before the first request after a reload (no access token yet)', async () => {
    setRefreshToken('refresh-1');
    const seen: (string | null)[] = [];
    server.use(
      http.post(api('/auth/token/refresh/'), () =>
        HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' }),
      ),
      http.get(api('/auth/me/'), ({ request }) => {
        seen.push(request.headers.get('Authorization'));
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiGet('/auth/me/');
    expect(seen).toEqual(['Bearer access-2']); // no wasted 401 round trip
  });

  it('ends the session when the refresh token is rejected', async () => {
    setAccessToken('expired');
    setRefreshToken('refresh-old');
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    server.use(
      http.post(api('/auth/token/refresh/'), () =>
        HttpResponse.json({ detail: 'Token is invalid or expired' }, { status: 401 }),
      ),
      http.get(api('/shelf/'), () => HttpResponse.json({}, { status: 401 })),
    );

    const error = await apiGet('/shelf/').catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });

  it('keeps the tokens when the refresh fails for network reasons', async () => {
    setAccessToken('expired');
    setRefreshToken('refresh-1');
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    server.use(
      http.post(api('/auth/token/refresh/'), () => HttpResponse.error()),
      http.get(api('/shelf/'), () => HttpResponse.json({}, { status: 401 })),
    );

    const error = await apiGet('/shelf/').catch((e: unknown) => e);
    expect(error).toMatchObject({ kind: 'network' });
    expect(expired).not.toHaveBeenCalled();
    expect(getRefreshToken()).toBe('refresh-1');
  });

  it('does not refresh for unauthenticated requests', async () => {
    const refresh = vi.fn(() => HttpResponse.json({}));
    server.use(
      http.post(api('/auth/token/refresh/'), refresh),
      http.post(api('/auth/token/'), () =>
        HttpResponse.json({ detail: 'No active account' }, { status: 401 }),
      ),
    );
    await expect(apiPost('/auth/token/', {}, { auth: false })).rejects.toMatchObject({
      status: 401,
    });
    expect(refresh).not.toHaveBeenCalled();
  });

  it('a refresh with no stored token resolves null and later refreshes still run', async () => {
    // Regression: an early-return refresh must not leave a settled promise cached.
    const { refreshAccessToken } = await import('./client');
    await expect(refreshAccessToken()).resolves.toBeNull();

    setRefreshToken('refresh-1');
    server.use(
      http.post(api('/auth/token/refresh/'), () =>
        HttpResponse.json({ access: 'access-9', refresh: 'refresh-9' }),
      ),
    );
    await expect(refreshAccessToken()).resolves.toBe('access-9');
  });
});

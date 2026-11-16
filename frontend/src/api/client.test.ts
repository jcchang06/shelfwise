import { afterEach, describe, expect, it, vi } from 'vitest';

import { API_BASE_URL, ApiError, apiFetch } from './client';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('prefixes the base URL and parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiFetch('/health/')).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/health/`, expect.any(Object));
  });

  it('throws ApiError with status and body on non-2xx', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'nope' })));

    const error = await apiFetch('/secret/').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 401, body: { detail: 'nope' } });
  });
});

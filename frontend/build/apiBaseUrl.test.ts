import { describe, expect, it } from 'vitest';

import { checkApiBaseUrl, LIVE_API_EXAMPLE } from './apiBaseUrl';

describe('checkApiBaseUrl', () => {
  it('accepts the live https API for production', () => {
    expect(checkApiBaseUrl(LIVE_API_EXAMPLE, 'production')).toBeNull();
  });

  it.each([
    [undefined, /not set/],
    ['', /not set/],
    ['http://localhost:8000/api', /only works on your machine/],
    ['https://127.0.0.1/api', /only works on your machine/],
    ['http://shelfwise-api-et8p.onrender.com/api', /must use https/],
    ['shelfwise-api-et8p.onrender.com/api', /not a valid URL/],
  ])('rejects %s for production', (url, message) => {
    const problem = checkApiBaseUrl(url, 'production');
    expect(problem).toMatch(message);
    expect(problem).toContain('VITE_API_BASE_URL=https://'); // tells you how to fix it
  });

  it.each(['development', 'test'])('allows anything (incl. missing) in %s mode', (mode) => {
    expect(checkApiBaseUrl(undefined, mode)).toBeNull();
    expect(checkApiBaseUrl('http://localhost:8000/api', mode)).toBeNull();
  });
});

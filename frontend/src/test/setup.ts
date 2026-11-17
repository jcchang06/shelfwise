import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { setSessionExpiredHandler } from '../api/client';
import { resetServerWaking } from '../api/serverWaking';
import { clearTokens } from '../api/tokens';
import { server } from './server';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  clearTokens();
  setSessionExpiredHandler(null);
  resetServerWaking();
});

afterAll(() => server.close());

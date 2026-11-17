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

// jsdom doesn't implement <dialog> modality. A minimal stand-in so ConfirmDialog can open
// and close in tests (real browsers handle focus trapping and inertness themselves).
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute('open');
    this.dispatchEvent(new Event('close'));
  };
}

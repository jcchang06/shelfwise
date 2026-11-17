import { afterEach, describe, expect, it, vi } from 'vitest';

import { isServerWaking, SLOW_REQUEST_MS, subscribe, trackRequest } from './serverWaking';

describe('trackRequest', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('flags a request as waking only after SLOW_REQUEST_MS, and clears it when done', async () => {
    vi.useFakeTimers();
    let finish!: () => void;
    const pending = trackRequest(new Promise<void>((resolve) => (finish = resolve)));
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);

    vi.advanceTimersByTime(SLOW_REQUEST_MS - 1);
    expect(isServerWaking()).toBe(false);
    vi.advanceTimersByTime(1);
    expect(isServerWaking()).toBe(true);

    finish();
    await pending;
    expect(isServerWaking()).toBe(false);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it('never flags fast requests', async () => {
    vi.useFakeTimers();
    await trackRequest(Promise.resolve('fast'));
    vi.advanceTimersByTime(SLOW_REQUEST_MS * 2);
    expect(isServerWaking()).toBe(false);
  });

  it('clears the flag when a slow request fails', async () => {
    vi.useFakeTimers();
    let fail!: (reason: Error) => void;
    const pending = trackRequest(new Promise<void>((_, reject) => (fail = reject)));
    vi.advanceTimersByTime(SLOW_REQUEST_MS);
    expect(isServerWaking()).toBe(true);
    fail(new Error('down'));
    await pending.catch(() => undefined);
    expect(isServerWaking()).toBe(false);
  });
});

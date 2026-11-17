/**
 * Tracks requests that are taking a while, so the UI can explain a free-tier cold start
 * ("Waking up the server…") instead of looking frozen. Render's free API sleeps after
 * 15 idle minutes and the first request afterwards can take about a minute.
 *
 * A tiny external store (subscribe + snapshot) for useSyncExternalStore.
 */

export const SLOW_REQUEST_MS = 3000;

let slowCount = 0;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isServerWaking(): boolean {
  return slowCount > 0;
}

/** Counts `promise` as slow once it has been pending for SLOW_REQUEST_MS. */
export function trackRequest<T>(promise: Promise<T>): Promise<T> {
  let slow = false;
  const timer = setTimeout(() => {
    slow = true;
    slowCount += 1;
    emit();
  }, SLOW_REQUEST_MS);
  return promise.finally(() => {
    clearTimeout(timer);
    if (slow) {
      slowCount -= 1;
      emit();
    }
  });
}

/** Test helper: forget any in-flight slow requests. */
export function resetServerWaking(): void {
  slowCount = 0;
  emit();
}

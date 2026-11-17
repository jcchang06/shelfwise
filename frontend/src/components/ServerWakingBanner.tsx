import { useSyncExternalStore } from 'react';

import { isServerWaking, subscribe } from '../api/serverWaking';

/**
 * Shown on every page, including /login, while any request has been pending for 3+
 * seconds: the free-tier API sleeps when idle and takes up to a minute to wake.
 */
export function ServerWakingBanner() {
  const waking = useSyncExternalStore(subscribe, isServerWaking, () => false);
  return (
    <div className="server-waking" role="status" aria-live="polite">
      {waking ? 'Waking up the server — this can take up to a minute.' : null}
    </div>
  );
}

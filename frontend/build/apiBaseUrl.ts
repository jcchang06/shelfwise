/**
 * Build-time guard for VITE_API_BASE_URL. Vite inlines the value into the bundle, so a
 * production build made without it (or with a local URL left over from .env or the
 * shell) would ship a site that quietly talks to localhost. Production builds fail instead.
 */

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0', '[::1]']);

export const LIVE_API_EXAMPLE = 'https://shelfwise-api-et8p.onrender.com/api';

/** An error message, or null if `url` is fine for a build in `mode`. */
export function checkApiBaseUrl(url: string | undefined, mode: string): string | null {
  if (mode !== 'production') return null;

  const fix = `Set it for the build, e.g. VITE_API_BASE_URL=${LIVE_API_EXAMPLE} npm run build`;
  if (!url) {
    return `VITE_API_BASE_URL is not set, so the site wouldn't know where the API is. ${fix}`;
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return `VITE_API_BASE_URL is not a valid URL: "${url}". ${fix}`;
  }
  if (LOCAL_HOSTS.has(parsed.hostname)) {
    return `VITE_API_BASE_URL points at ${parsed.host}, which only works on your machine. ${fix}`;
  }
  if (parsed.protocol !== 'https:') {
    return `VITE_API_BASE_URL must use https:// in production (got "${url}"). ${fix}`;
  }
  return null;
}

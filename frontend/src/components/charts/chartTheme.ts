import { useSyncExternalStore } from 'react';

/**
 * Chart colors come from the CSS tokens (index.css), so light and dark mode each use
 * their own validated steps. Chart.js draws on a canvas and can't read CSS variables
 * itself, so they're read here and re-read when the system theme changes.
 */
export interface ChartTheme {
  series1: string;
  series2: string;
  grid: string;
  text: string;
  surface: string;
}

const DARK_QUERY = '(prefers-color-scheme: dark)';

function subscribe(onChange: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined;
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function isDark(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.(DARK_QUERY).matches;
}

function readTheme(): ChartTheme {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    series1: v('--series-1', '#2a78d6'),
    series2: v('--series-2', '#eb6834'),
    grid: v('--chart-grid', '#e7e5e4'),
    text: v('--text-muted', '#57534e'),
    surface: v('--bg', '#ffffff'),
  };
}

export function useChartTheme(): ChartTheme {
  // The snapshot is the mode; the theme is derived from it, so a switch re-renders.
  const dark = useSyncExternalStore(subscribe, isDark, () => false);
  void dark;
  return readTheme();
}

import { SHELF_STATUS_LABELS, type ShelfStatus } from './api/types';

/** The shelves in the order they're shown (shelf bar and shelf page). */
export const SHELVES: ShelfStatus[] = ['reading', 'want_to_read', 'finished', 'dnf'];

/** Shelf bar labels: "DNF" keeps the bar to one row on most phones. */
export const SHELF_BAR_LABELS: Record<ShelfStatus, string> = {
  ...SHELF_STATUS_LABELS,
  dnf: 'DNF',
};

export function isShelf(value: string | null): value is ShelfStatus {
  return value !== null && (SHELVES as string[]).includes(value);
}

/** The shelf page's URL for a shelf, keeping a sort order when there is one. */
export function shelfPath(status: ShelfStatus, sort?: string | null): string {
  const params = new URLSearchParams({ status });
  if (sort) params.set('sort', sort);
  return `/shelf?${params}`;
}

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

/** The shelf page's options that live in the URL besides the shelf itself. */
export interface ShelfViewParams {
  sort?: string | null;
  author?: number | null;
  rating?: string | null;
}

/** The shelf page's URL for a shelf, keeping any sort order and filters given. */
export function shelfPath(status: ShelfStatus, view: ShelfViewParams = {}): string {
  const params = new URLSearchParams({ status });
  if (view.sort) params.set('sort', view.sort);
  if (view.author) params.set('author', String(view.author));
  if (view.rating) params.set('rating', view.rating);
  return `/shelf?${params}`;
}

/** An author id from the URL: a positive whole number, or null. */
export function parseAuthorParam(value: string | null): number | null {
  return value && /^\d+$/.test(value) && Number(value) > 0 ? Number(value) : null;
}

import { apiDelete, apiGet, apiPatch, apiPost } from './client';
import type { BookSource, DnfReason, Paginated, ShelfEntry, ShelfStatus } from './types';

/** Which book to add: a catalog book, or a search result to save to the catalog first. */
export type BookReference = { book_id: number } | { source: BookSource; source_id: string };

/** POST /api/shelf/. Send only editable fields (the API rejects anything else). */
export type AddToShelfPayload = BookReference & {
  status: ShelfStatus;
  finished_at?: string;
};

/** PATCH /api/shelf/{id}/ — only the fields being changed. */
export interface ShelfChanges {
  status?: ShelfStatus;
  rating?: number | null;
  review?: string;
  started_at?: string | null;
  finished_at?: string | null;
  dnf_page?: number | null;
  dnf_at?: string | null;
  dnf_reason?: DnfReason | '';
  dnf_note?: string;
}

/** Shelf sort options, keyed by the URL value; values are the API's `ordering`. */
export const SHELF_SORTS = {
  updated: { ordering: '-updated_at', label: 'Recently updated' },
  title: { ordering: 'title', label: 'Title' },
  finished: { ordering: '-finished_at', label: 'Finished date' },
  added: { ordering: '-created_at', label: 'Date added' },
} as const;

export type ShelfSort = keyof typeof SHELF_SORTS;

export function addToShelf(payload: AddToShelfPayload): Promise<ShelfEntry> {
  return apiPost<ShelfEntry>('/shelf/', payload);
}

export function listShelf(
  status: ShelfStatus,
  sort: ShelfSort,
  page = 1,
): Promise<Paginated<ShelfEntry>> {
  const params = new URLSearchParams({
    status,
    ordering: SHELF_SORTS[sort].ordering,
    page: String(page),
  });
  return apiGet<Paginated<ShelfEntry>>(`/shelf/?${params}`);
}

/** The caller's entry for a catalog book, or null if it isn't on their shelf. */
export async function getShelfEntryForBook(bookId: number): Promise<ShelfEntry | null> {
  const page = await apiGet<Paginated<ShelfEntry>>(`/shelf/?book=${bookId}`);
  return page.results[0] ?? null;
}

export function updateShelfEntry(id: number, changes: ShelfChanges): Promise<ShelfEntry> {
  return apiPatch<ShelfEntry>(`/shelf/${id}/`, changes);
}

export function removeShelfEntry(id: number): Promise<null> {
  return apiDelete(`/shelf/${id}/`);
}

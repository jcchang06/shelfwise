import { apiPost } from './client';
import type { BookSource, ShelfEntry, ShelfStatus } from './types';

/** POST /api/shelf/. Send only editable fields (the API rejects anything else). */
export type AddToShelfPayload = (
  { book_id: number } | { source: BookSource; source_id: string }
) & {
  status: ShelfStatus;
  finished_at?: string;
};

export function addToShelf(payload: AddToShelfPayload): Promise<ShelfEntry> {
  return apiPost<ShelfEntry>('/shelf/', payload);
}

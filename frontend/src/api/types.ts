/** Hand-written mirrors of the backend serializers. Keep in step with the API. */

export type ShelfStatus = 'want_to_read' | 'reading' | 'finished' | 'dnf';

export const SHELF_STATUS_LABELS: Record<ShelfStatus, string> = {
  want_to_read: 'Want to read',
  reading: 'Reading',
  finished: 'Finished',
  dnf: 'Did not finish',
};

export type BookSource = 'google_books' | 'open_library';

/** GET /api/books/search/ — one result. */
export interface SearchResult {
  source: BookSource;
  source_id: string;
  title: string;
  authors: string[];
  description: string;
  genres: string[];
  page_count: number | null;
  published_date: string; // partial: "2014", "2014-03" or "2014-03-05"
  isbn_13: string;
  cover_url: string;
  book_id: number | null; // catalog book it would save to
  shelf: { id: number; status: ShelfStatus } | null; // the caller's entry
}

export interface SearchResponse {
  source: BookSource;
  page: number;
  next_page: number | null;
  results: SearchResult[];
}

/** The compact book on a shelf entry. */
export interface ShelfBook {
  id: number;
  title: string;
  authors: string[];
  cover_url: string;
  page_count: number | null;
}

/** /api/shelf/ entry. */
export interface ShelfEntry {
  id: number;
  book: ShelfBook;
  status: ShelfStatus;
  rating: number | null;
  review: string;
  started_at: string | null;
  finished_at: string | null;
  dnf_page: number | null;
  dnf_at: string | null;
  dnf_reason: string;
  dnf_note: string;
  pages_logged: number;
  reading_log_count: number;
  created_at: string;
  updated_at: string;
}

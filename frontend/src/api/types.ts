/** Hand-written mirrors of the backend serializers. Keep in step with the API. */

export type ShelfStatus = 'want_to_read' | 'reading' | 'finished' | 'dnf';

export const SHELF_STATUS_LABELS: Record<ShelfStatus, string> = {
  want_to_read: 'Want to read',
  reading: 'Reading',
  finished: 'Finished',
  dnf: 'Did not finish',
};

export type DnfReason =
  'writing_style' | 'pacing' | 'content' | 'not_my_genre' | 'not_in_the_mood' | 'other';

export const DNF_REASON_LABELS: Record<DnfReason, string> = {
  writing_style: 'Writing style',
  pacing: 'Pacing',
  content: 'Content',
  not_my_genre: 'Not my genre',
  not_in_the_mood: 'Not in the mood',
  other: 'Other',
};

export type BookSource = 'google_books' | 'open_library';

/** DRF page-number pagination. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** GET /api/books/{id}/ */
export interface BookDetail {
  id: number;
  title: string;
  authors: { id: number; name: string }[];
  description: string;
  genres: string[];
  page_count: number | null;
  published_date: string; // display form: "2014", "2014-03" or "2014-03-05"
  isbn_13: string;
  cover_url: string;
  series_name: string;
  series_number: string | null;
  google_books_id: string | null;
  open_library_key: string | null;
}

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
  dnf_reason: DnfReason | '';
  dnf_note: string;
  pages_logged: number;
  reading_log_count: number;
  created_at: string;
  updated_at: string;
}

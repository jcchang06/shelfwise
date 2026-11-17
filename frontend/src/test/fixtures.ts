import type { BookDetail, ShelfEntry } from '../api/types';

export function bookDetail(overrides: Partial<BookDetail> = {}): BookDetail {
  return {
    id: 42,
    title: 'Project Hail Mary',
    authors: [{ id: 1, name: 'Andy Weir' }],
    description: 'A lone astronaut must save the earth.\n\nExcept he can’t remember his name.',
    genres: ['Science Fiction', 'Thrillers'],
    page_count: 496,
    published_date: '2021-05-04',
    isbn_13: '9780593135204',
    cover_url: '',
    series_name: '',
    series_number: null,
    google_books_id: 'vol1',
    open_library_key: null,
    ...overrides,
  };
}

export function shelfEntry(overrides: Partial<ShelfEntry> = {}): ShelfEntry {
  return {
    id: 7,
    book: {
      id: 42,
      title: 'Project Hail Mary',
      authors: ['Andy Weir'],
      cover_url: '',
      page_count: 496,
    },
    status: 'want_to_read',
    rating: null,
    review: '',
    started_at: null,
    finished_at: null,
    dnf_page: null,
    dnf_at: null,
    dnf_reason: '',
    dnf_note: '',
    pages_logged: 0,
    reading_log_count: 0,
    created_at: '2026-11-16T18:00:00Z',
    updated_at: '2026-11-16T18:00:00Z',
    ...overrides,
  };
}

export function page<T>(results: T[], next: string | null = null) {
  return { count: results.length, next, previous: null, results };
}

import { apiGet } from './client';
import type { SearchResponse, SearchResult } from './types';

/** Searches submit-only (never per keystroke) to protect the Google Books quota. */
export const MIN_QUERY_LENGTH = 2;

export function searchBooks(q: string, page = 1): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, page: String(page) });
  return apiGet<SearchResponse>(`/books/search/?${params}`);
}

/**
 * The book's page at its source. Google's branding rules require a prominent link to the
 * Google Books page for every result; Open Library gets the same courtesy.
 */
export function sourcePageUrl(result: Pick<SearchResult, 'source' | 'source_id'>): string {
  return result.source === 'google_books'
    ? `https://books.google.com/books?id=${encodeURIComponent(result.source_id)}`
    : `https://openlibrary.org/works/${encodeURIComponent(result.source_id)}`;
}

import { apiGet } from './client';
import type { ShelfStatus } from './types';

/** A book on a pick or a "more like this" list, with the caller's shelf entry. */
export interface SuggestedBook {
  id: number;
  title: string;
  author_links?: { id: number; name: string }[]; // optional: frontends can deploy first
  cover_url: string;
  page_count: number | null;
  published_date: string; // display form: "2014", "2014-03" or "2014-03-05"
  shelf?: { id: number; status: ShelfStatus } | null;
}

/** GET /api/recommendations/ (R-2). computed_at is null before the first nightly run. */
export interface RecommendationsResponse {
  computed_at: string | null;
  results: {
    rank: number;
    book: SuggestedBook;
    because_of?: { id: number; title: string } | null; // shown by R-4 later
  }[];
}

export function getRecommendations(): Promise<RecommendationsResponse> {
  return apiGet<RecommendationsResponse>('/recommendations/');
}

/** GET /api/books/{id}/similar/ (R-3). */
export function getSimilarBooks(bookId: number, limit = 6): Promise<{ results: SuggestedBook[] }> {
  return apiGet<{ results: SuggestedBook[] }>(`/books/${bookId}/similar/?limit=${limit}`);
}

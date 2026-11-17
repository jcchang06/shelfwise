import { apiGet } from './client';

/** GET /api/stats/?year= — every dashboard section in one response (T-5). */
export interface Stats {
  year: number;
  totals: { pages: number; finished: number; dnf: number; average_rating: number | null };
  pages_per_month: { month: string; pages: number; dnf_pages: number }[]; // "2026-01", 12 rows
  books_per_year: { year: number | null; finished: number; dnf: number }[]; // null = date unknown
  genre_mix: { genre: string; finished: number; dnf: number }[]; // top 8 + "Other"
  rating_distribution: { stars: number; books: number }[]; // 1..5
}

export function getStats(year: number): Promise<Stats> {
  return apiGet<Stats>(`/stats/?year=${year}`);
}

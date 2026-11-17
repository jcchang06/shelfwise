import { apiGet } from './client';
import type { ShelfStatus } from './types';

/** One work on an author page: from Open Library, the catalog, or both. */
export interface AuthorWork {
  title: string;
  work_key: string | null; // Open Library work; null for a catalog-only book
  first_publish_year: number | null;
  cover_url: string;
  book_id: number | null; // the catalog book, if it's in the catalog
  series_name: string | null;
  series_number: string | null; // "2.0"
  shelf: { id: number; status: ShelfStatus } | null; // the caller's entry
}

/** GET /api/authors/{id}/ (C-5) */
export interface AuthorDetail {
  id: number;
  name: string;
  open_library_key: string | null;
  open_library_url: string | null;
  works_unavailable: boolean; // Open Library unreachable: catalog books only
  groups: { series_name: string | null; works: AuthorWork[] }[];
}

export function getAuthor(id: number): Promise<AuthorDetail> {
  return apiGet<AuthorDetail>(`/authors/${id}/`);
}

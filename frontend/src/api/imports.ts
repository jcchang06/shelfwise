import { apiGet, apiPost, apiPostForm } from './client';
import type { BookReference } from './shelf';
import type { Paginated, ShelfStatus } from './types';

export type ImportStatus = 'pending' | 'running' | 'paused' | 'done' | 'failed';

/** /api/imports/ */
export interface GoodreadsImport {
  id: number;
  status: ImportStatus;
  total_rows: number;
  processed_rows: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  unmatched_count: number;
  failed_count: number;
  placeholder_dnf_count: number; // imported DNFs whose reason is still not_specified
  error: string;
  created_at: string;
  finished_at: string | null;
}

export type ImportRowState = 'unmatched' | 'failed';

export interface ImportRow {
  id: number;
  row_number: number;
  title: string;
  author: string;
  additional_authors: string;
  isbn_13: string;
  year_published: number | null;
  status: ShelfStatus;
  rating: number | null;
  date_read: string | null;
  state: string;
  note: string;
  search_query: string; // "title first-author", to pre-fill the search box
}

export interface RowResult {
  row: { id: number; state: string; note: string };
  book_id: number | null;
  user_book_id: number | null;
  import: GoodreadsImport;
}

/** Matches the backend's IMPORT_MAX_FILE_BYTES; checked here too for a fast error. */
export const MAX_IMPORT_BYTES = 5 * 1024 * 1024;

export function listImports(): Promise<Paginated<GoodreadsImport>> {
  return apiGet<Paginated<GoodreadsImport>>('/imports/');
}

export function getImport(id: number): Promise<GoodreadsImport> {
  return apiGet<GoodreadsImport>(`/imports/${id}/`);
}

export function uploadImport(file: File): Promise<GoodreadsImport> {
  const form = new FormData();
  form.append('file', file);
  return apiPostForm<GoodreadsImport>('/imports/', form);
}

/** Run one ~20s batch. 409 means another batch (nightly job, local worker) is running. */
export function processImport(id: number): Promise<GoodreadsImport> {
  return apiPost<GoodreadsImport>(`/imports/${id}/process/`, {});
}

export function listImportRows(
  id: number,
  state: ImportRowState,
  page = 1,
): Promise<Paginated<ImportRow>> {
  const params = new URLSearchParams({ state, page: String(page) });
  return apiGet<Paginated<ImportRow>>(`/imports/${id}/rows/?${params}`);
}

export function resolveImportRow(
  id: number,
  rowId: number,
  book: BookReference,
): Promise<RowResult> {
  return apiPost<RowResult>(`/imports/${id}/rows/${rowId}/resolve/`, book);
}

export function dismissImportRow(id: number, rowId: number): Promise<RowResult> {
  return apiPost<RowResult>(`/imports/${id}/rows/${rowId}/dismiss/`, {});
}

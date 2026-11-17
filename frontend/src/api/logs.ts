import { apiDelete, apiGet, apiPatch, apiPost } from './client';
import type { Paginated, ShelfStatus } from './types';

/** /api/logs/ row (T-3). One per user, book and day. */
export interface ReadingLog {
  id: number;
  book_id: number;
  log_date: string; // YYYY-MM-DD
  pages_read: number;
  created_at: string;
  updated_at: string;
}

/** What a log write can change on the shelf entry, returned with POST and PATCH. */
export interface LogShelfEntry {
  id: number;
  status: ShelfStatus;
  started_at: string | null;
  pages_logged: number;
}

export interface LogWriteResponse extends ReadingLog {
  shelf_entry: LogShelfEntry | null;
}

export interface LogPagesPayload {
  book_id: number;
  pages_read: number;
  log_date?: string; // defaults to today on the server
}

export interface LogChanges {
  pages_read?: number;
  log_date?: string;
}

/** The caller's logs for one day (any book). First page only: one row per book per day. */
export function listLogsOn(date: string): Promise<Paginated<ReadingLog>> {
  const params = new URLSearchParams({ from: date, to: date });
  return apiGet<Paginated<ReadingLog>>(`/logs/?${params}`);
}

export function listLogs(bookId: number, page = 1): Promise<Paginated<ReadingLog>> {
  const params = new URLSearchParams({ book: String(bookId), page: String(page) });
  return apiGet<Paginated<ReadingLog>>(`/logs/?${params}`);
}

/** POST: a second log for the same book and day *adds* to it (201 new day, 200 added). */
export function logPages(payload: LogPagesPayload): Promise<LogWriteResponse> {
  return apiPost<LogWriteResponse>('/logs/', payload);
}

/** PATCH *sets* the day's total, or moves the log to another (free) day. */
export function updateLog(id: number, changes: LogChanges): Promise<LogWriteResponse> {
  return apiPatch<LogWriteResponse>(`/logs/${id}/`, changes);
}

export function deleteLog(id: number): Promise<null> {
  return apiDelete(`/logs/${id}/`);
}

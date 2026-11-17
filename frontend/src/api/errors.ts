/**
 * Turns API errors into what forms show. The backend's 400s are always
 * `{field: ["message", ...]}` (DRF field errors and our rule errors share that shape),
 * plus `detail` / `non_field_errors` for form-level problems and `id` / `conflict_id`
 * when something already exists.
 */

import { ApiError } from './client';

const NON_FIELD_KEYS = new Set(['detail', 'non_field_errors', 'conflict_id', 'id']);

export type FieldErrors = Record<string, string>;

function asObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function joinMessages(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const messages = value.filter((item): item is string => typeof item === 'string');
    return messages.length ? messages.join(' ') : null;
  }
  return null;
}

/** One message per field, for showing next to inputs. Empty for non-400 errors. */
export function fieldErrors(error: unknown): FieldErrors {
  if (!(error instanceof ApiError) || error.status !== 400) return {};
  const body = asObject(error.body);
  if (!body) return {};
  const result: FieldErrors = {};
  for (const [field, value] of Object.entries(body)) {
    if (NON_FIELD_KEYS.has(field)) continue;
    const message = joinMessages(value);
    if (message) result[field] = message;
  }
  return result;
}

/**
 * A form-level message, or null when the error is fully explained by field errors.
 * Covers network failures, timeouts, rate limits, server errors and `detail`.
 */
export function formError(error: unknown): string | null {
  if (!(error instanceof ApiError)) {
    return error ? 'Something went wrong. Please try again.' : null;
  }
  if (error.kind === 'timeout') {
    return 'The server took too long to respond. Please try again.';
  }
  if (error.kind === 'network') {
    return "Couldn't reach the server. Check your connection and try again.";
  }

  const body = asObject(error.body);
  const detail = joinMessages(body?.detail) ?? joinMessages(body?.non_field_errors);
  if (error.status === 429) {
    return detail ?? 'Too many attempts. Please wait a minute and try again.';
  }
  if (error.status === 400 && !detail && Object.keys(fieldErrors(error)).length > 0) {
    return null;
  }
  if (detail) return detail;
  if (error.status >= 500) {
    return 'Something went wrong on the server. Please try again in a moment.';
  }
  return 'Something went wrong. Please try again.';
}

/** The id of the existing thing on a 409 (shelf) or a taken day (`conflict_id`, logs). */
export function conflictId(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const body = asObject(error.body);
  const value = body?.conflict_id ?? (error.status === 409 ? body?.id : undefined);
  return typeof value === 'number' ? value : null;
}

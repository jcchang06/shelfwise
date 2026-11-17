import { describe, expect, it } from 'vitest';

import { ApiError } from './client';
import { conflictId, fieldErrors, formError } from './errors';

const http = (status: number, body: unknown) => new ApiError(status, body);

describe('fieldErrors', () => {
  it('maps {field: [messages]} to one message per field', () => {
    const error = http(400, {
      rating: ["You can rate a book only when it's finished."],
      dnf_reason: ['Choose why you stopped reading.', 'Second message.'],
    });
    expect(fieldErrors(error)).toEqual({
      rating: "You can rate a book only when it's finished.",
      dnf_reason: 'Choose why you stopped reading. Second message.',
    });
  });

  it('skips form-level keys and non-400s', () => {
    expect(
      fieldErrors(http(400, { detail: 'x', non_field_errors: ['y'], conflict_id: 3 })),
    ).toEqual({});
    expect(fieldErrors(http(409, { id: 3 }))).toEqual({});
    expect(fieldErrors(new Error('boom'))).toEqual({});
  });

  it('accepts plain string messages too', () => {
    expect(fieldErrors(http(400, { year: 'Must be a year.' }))).toEqual({
      year: 'Must be a year.',
    });
  });
});

describe('formError', () => {
  it('is null when field errors explain everything', () => {
    expect(formError(http(400, { email: ['Enter a valid email address.'] }))).toBeNull();
  });

  it('uses detail and non_field_errors', () => {
    expect(formError(http(401, { detail: 'No active account found' }))).toBe(
      'No active account found',
    );
    expect(formError(http(400, { non_field_errors: ['Send either book_id or source.'] }))).toBe(
      'Send either book_id or source.',
    );
  });

  it('explains network failures, timeouts, rate limits and server errors', () => {
    expect(formError(new ApiError(0, null, 'network'))).toMatch(/couldn't reach the server/i);
    expect(formError(new ApiError(0, null, 'timeout'))).toMatch(/too long/i);
    expect(formError(http(429, {}))).toMatch(/too many attempts/i);
    expect(formError(http(500, null))).toMatch(/server/i);
    expect(formError(http(503, { detail: 'Book search is temporarily unavailable.' }))).toBe(
      'Book search is temporarily unavailable.',
    );
  });

  it('handles non-API errors and no error', () => {
    expect(formError(new Error('boom'))).toMatch(/something went wrong/i);
    expect(formError(null)).toBeNull();
  });
});

describe('conflictId', () => {
  it('reads the 409 id and the log conflict_id', () => {
    expect(conflictId(http(409, { detail: 'Already on your shelf.', id: 12 }))).toBe(12);
    expect(conflictId(http(400, { log_date: ['Taken.'], conflict_id: 34 }))).toBe(34);
  });

  it('ignores ids on other statuses and non-numbers', () => {
    expect(conflictId(http(400, { id: 12 }))).toBeNull();
    expect(conflictId(http(409, { id: '12' }))).toBeNull();
    expect(conflictId(new Error('x'))).toBeNull();
  });
});

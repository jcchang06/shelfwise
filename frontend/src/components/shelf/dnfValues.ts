import type { ShelfChanges } from '../../api/shelf';
import type { DnfReason } from '../../api/types';

/** The DNF fields as typed: every one optional (T-6, T-7). */
export interface DnfValues {
  reason: DnfReason | '';
  page: string;
  at: string;
  note: string;
}

export const DNF_FIELD_NAMES = ['dnf_reason', 'dnf_page', 'dnf_at', 'dnf_note'] as const;

export function initialDnfValues(today: string, page = ''): DnfValues {
  return { reason: '', page, at: today, note: '' };
}

/**
 * The request fields for a book becoming DNF, plus any problems found. Blank fields are
 * left out (T-8): the API then saves reason not_specified, today's date and the logged page.
 */
export function dnfChanges(
  values: DnfValues,
  today: string,
): {
  changes: Pick<ShelfChanges, 'dnf_reason' | 'dnf_page' | 'dnf_at' | 'dnf_note'>;
  problems: Record<string, string>;
} {
  const changes: Pick<ShelfChanges, 'dnf_reason' | 'dnf_page' | 'dnf_at' | 'dnf_note'> = {};
  const problems: Record<string, string> = {};
  if (values.reason) changes.dnf_reason = values.reason;
  if (values.page !== '') {
    if (!/^\d+$/.test(values.page.trim())) problems.dnf_page = 'Enter a whole page number.';
    else changes.dnf_page = Number(values.page);
  }
  if (values.at) {
    if (values.at > today) problems.dnf_at = "This date can't be in the future.";
    changes.dnf_at = values.at;
  }
  if (values.note.trim()) changes.dnf_note = values.note.trim();
  return { changes, problems };
}

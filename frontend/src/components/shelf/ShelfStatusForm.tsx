import { useId, useState, type FormEvent } from 'react';

import type { ShelfChanges } from '../../api/shelf';
import {
  DNF_REASON_LABELS,
  SHELF_STATUS_LABELS,
  type DnfReason,
  type ShelfEntry,
  type ShelfStatus,
} from '../../api/types';
import { localDateISO } from '../../dates';
import { useUpdateShelfEntry } from '../../hooks/useShelf';
import { describeError } from './useFormErrors';

const STATUSES: ShelfStatus[] = ['want_to_read', 'reading', 'finished', 'dnf'];
const FIELDS = ['status', 'finished_at', 'dnf_reason', 'dnf_page', 'dnf_at', 'dnf_note'] as const;

interface ShelfStatusFormProps {
  entry: ShelfEntry;
  onSaved: (message: string) => void;
}

/**
 * Change shelf status, with the fields the new status needs (finish date; DNF reason,
 * page, date, note). Explicit Save: moving out of DNF clears data, so nothing changes on
 * select alone. Only the fields being changed are sent.
 */
export function ShelfStatusForm({ entry, onSaved }: ShelfStatusFormProps) {
  const id = useId();
  const today = localDateISO();
  const update = useUpdateShelfEntry();
  const loggedDefault =
    entry.pages_logged > 0
      ? String(
          entry.book.page_count
            ? Math.min(entry.pages_logged, entry.book.page_count)
            : entry.pages_logged,
        )
      : '';

  const [status, setStatus] = useState<ShelfStatus>(entry.status);
  const [finishedOn, setFinishedOn] = useState(today);
  const [dnfReason, setDnfReason] = useState<DnfReason | ''>('');
  const [dnfPage, setDnfPage] = useState(loggedDefault);
  const [dnfAt, setDnfAt] = useState(today);
  const [dnfNote, setDnfNote] = useState('');
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const changed = status !== entry.status;
  const server = describeError(update.error, FIELDS);
  const errors = { ...server.fields, ...clientErrors };

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!changed) return;
    const problems: Record<string, string> = {};
    const changes: ShelfChanges = { status };
    if (status === 'finished' && finishedOn) {
      if (finishedOn > today) problems.finished_at = "The finish date can't be in the future.";
      changes.finished_at = finishedOn;
    }
    if (status === 'dnf') {
      if (!dnfReason) problems.dnf_reason = 'Choose why you stopped reading.';
      else changes.dnf_reason = dnfReason;
      if (dnfPage !== '') changes.dnf_page = Number(dnfPage);
      if (dnfAt) {
        if (dnfAt > today) problems.dnf_at = "This date can't be in the future.";
        changes.dnf_at = dnfAt;
      }
      if (dnfNote.trim()) changes.dnf_note = dnfNote.trim();
    }
    setClientErrors(problems);
    if (Object.keys(problems).length) return;
    // mutateAsync, not mutate callbacks: saving re-keys (remounts) this form, and TanStack
    // skips per-call callbacks once a component unmounts. onSaved lives on the page.
    update
      .mutateAsync({ entry, changes })
      .then((saved) => onSaved(`Moved to ${SHELF_STATUS_LABELS[saved.status]}.`))
      .catch(() => undefined); // shown from update.error
  }

  const describedBy = (field: string) => (errors[field] ? `${id}-${field}-error` : undefined);
  const fieldError = (field: string) =>
    errors[field] ? (
      <p id={`${id}-${field}-error`} className="field-error">
        {errors[field]}
      </p>
    ) : null;

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Status</h2>
      <div className="form-field">
        <label htmlFor={`${id}-status`}>Shelf</label>
        <select
          id={`${id}-status`}
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as ShelfStatus);
            setClientErrors({});
          }}
        >
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {SHELF_STATUS_LABELS[value]}
            </option>
          ))}
        </select>
      </div>

      {changed && entry.status === 'dnf' ? (
        <p className="notice">
          Resuming clears the DNF details (reason, page, date and note). Your reading logs stay.
        </p>
      ) : null}
      {changed && entry.status === 'finished' && status === 'reading' ? (
        <p className="notice">Re-reading: your rating stays, and the start date becomes today.</p>
      ) : null}

      {changed && status === 'finished' ? (
        <div className="form-field">
          <label htmlFor={`${id}-finished`}>Finished on</label>
          <input
            id={`${id}-finished`}
            type="date"
            value={finishedOn}
            max={today}
            onChange={(event) => setFinishedOn(event.target.value)}
            aria-invalid={errors.finished_at ? true : undefined}
            aria-describedby={describedBy('finished_at')}
          />
          {fieldError('finished_at')}
        </div>
      ) : null}

      {changed && status === 'dnf' ? (
        <>
          <div className="form-field">
            <label htmlFor={`${id}-reason`}>Why did you stop?</label>
            <select
              id={`${id}-reason`}
              value={dnfReason}
              onChange={(event) => setDnfReason(event.target.value as DnfReason | '')}
              aria-invalid={errors.dnf_reason ? true : undefined}
              aria-describedby={describedBy('dnf_reason')}
            >
              <option value="">Choose a reason</option>
              {(Object.keys(DNF_REASON_LABELS) as DnfReason[]).map((value) => (
                <option key={value} value={value}>
                  {DNF_REASON_LABELS[value]}
                </option>
              ))}
            </select>
            {fieldError('dnf_reason')}
          </div>
          <div className="form-field">
            <label htmlFor={`${id}-page`}>Stopped at page</label>
            <input
              id={`${id}-page`}
              type="number"
              inputMode="numeric"
              min={0}
              max={entry.book.page_count ?? undefined}
              value={dnfPage}
              onChange={(event) => setDnfPage(event.target.value)}
              aria-invalid={errors.dnf_page ? true : undefined}
              aria-describedby={describedBy('dnf_page')}
            />
            {fieldError('dnf_page')}
          </div>
          <div className="form-field">
            <label htmlFor={`${id}-dnf-at`}>Stopped on</label>
            <input
              id={`${id}-dnf-at`}
              type="date"
              value={dnfAt}
              max={today}
              onChange={(event) => setDnfAt(event.target.value)}
              aria-invalid={errors.dnf_at ? true : undefined}
              aria-describedby={describedBy('dnf_at')}
            />
            {fieldError('dnf_at')}
          </div>
          <div className="form-field">
            <label htmlFor={`${id}-note`}>Note (optional)</label>
            <textarea
              id={`${id}-note`}
              rows={2}
              value={dnfNote}
              onChange={(event) => setDnfNote(event.target.value)}
            />
          </div>
        </>
      ) : null}

      {server.summary ? (
        <p className="field-error" role="alert">
          {server.summary}
        </p>
      ) : null}
      <button type="submit" disabled={!changed || update.isPending}>
        {update.isPending ? 'Saving…' : 'Save status'}
      </button>
    </form>
  );
}

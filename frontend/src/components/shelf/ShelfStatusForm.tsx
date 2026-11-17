import { useId, useState, type FormEvent } from 'react';

import type { ShelfChanges } from '../../api/shelf';
import {
  CHOOSABLE_DNF_REASONS,
  DNF_REASON_LABELS,
  SHELF_STATUS_LABELS,
  type DnfReason,
  type ShelfEntry,
  type ShelfStatus,
} from '../../api/types';
import { localDateISO } from '../../dates';
import { useUpdateShelfEntry } from '../../hooks/useShelf';
import { FieldLabel } from '../forms/FieldLabel';
import { useFocusInvalid } from '../forms/useFocusInvalid';
import { describeError } from './useFormErrors';

const STATUSES: ShelfStatus[] = ['want_to_read', 'reading', 'finished', 'dnf'];
const FIELDS = [
  'status',
  'started_at',
  'finished_at',
  'dnf_reason',
  'dnf_page',
  'dnf_at',
  'dnf_note',
] as const;

interface ShelfStatusFormProps {
  entry: ShelfEntry;
  onSaved: (message: string) => void;
}

/**
 * Change shelf status, with the fields the new status needs (start or finish date; DNF
 * reason, page, date, note). Explicit Save: moving out of DNF clears data, so nothing
 * changes on select alone. Only the fields being changed are sent.
 *
 * Every field but the shelf is optional (T-7). Dates are pre-filled with what the API
 * would use (T-8), and a date left blank is not sent, so the API's default applies; so is
 * a blank reason, which the API saves as not_specified.
 */
export function ShelfStatusForm({ entry, onSaved }: ShelfStatusFormProps) {
  const id = useId();
  const today = localDateISO();
  const update = useUpdateShelfEntry();
  const { ref, focusInvalid } = useFocusInvalid();
  const loggedDefault =
    entry.pages_logged > 0
      ? String(
          entry.book.page_count
            ? Math.min(entry.pages_logged, entry.book.page_count)
            : entry.pages_logged,
        )
      : '';
  // Like the API: a re-read starts today; otherwise an existing start date is kept.
  const startDefault = entry.status === 'finished' ? today : (entry.started_at ?? today);

  const [status, setStatus] = useState<ShelfStatus>(entry.status);
  const [startedOn, setStartedOn] = useState(startDefault);
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
    if (update.isPending) return; // Save stays enabled; a second press does nothing
    const problems: Record<string, string> = {};
    const changes: ShelfChanges = { status };
    const date = (field: 'started_at' | 'finished_at' | 'dnf_at', value: string) => {
      if (!value) return; // blank: left out, never null (T-8)
      if (value > today) problems[field] = "This date can't be in the future.";
      changes[field] = value;
    };
    if (!changed) problems.status = 'Choose a different shelf to move this book to.';
    if (status === 'reading') date('started_at', startedOn);
    if (status === 'finished') date('finished_at', finishedOn);
    if (status === 'dnf') {
      if (dnfReason) changes.dnf_reason = dnfReason;
      if (dnfPage !== '') changes.dnf_page = Number(dnfPage);
      date('dnf_at', dnfAt);
      if (dnfNote.trim()) changes.dnf_note = dnfNote.trim();
    }
    setClientErrors(problems);
    if (Object.keys(problems).length) {
      focusInvalid();
      return;
    }
    // mutateAsync, not mutate callbacks: saving re-keys (remounts) this form, and TanStack
    // skips per-call callbacks once a component unmounts. onSaved lives on the page.
    update
      .mutateAsync({ entry, changes })
      .then((saved) => onSaved(`Moved to ${SHELF_STATUS_LABELS[saved.status]}.`))
      .catch(() => focusInvalid()); // the error itself is shown from update.error
  }

  const invalid = (field: string) => (errors[field] ? true : undefined);
  const describedBy = (field: string) => (errors[field] ? `${id}-${field}-error` : undefined);
  const fieldError = (field: string) =>
    errors[field] ? (
      <p id={`${id}-${field}-error`} className="field-error">
        {errors[field]}
      </p>
    ) : null;
  const dateField = (
    field: 'started_at' | 'finished_at' | 'dnf_at',
    label: string,
    value: string,
    set: (value: string) => void,
  ) => (
    <div className="form-field">
      <FieldLabel htmlFor={`${id}-${field}`} need="optional">
        {label}
      </FieldLabel>
      <input
        id={`${id}-${field}`}
        type="date"
        value={value}
        max={today}
        onChange={(event) => set(event.target.value)}
        aria-invalid={invalid(field)}
        aria-describedby={describedBy(field)}
      />
      {fieldError(field)}
    </div>
  );

  return (
    <form
      ref={ref}
      className="panel"
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby={`${id}-title`}
    >
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
          aria-invalid={invalid('status')}
          aria-describedby={describedBy('status')}
        >
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {SHELF_STATUS_LABELS[value]}
            </option>
          ))}
        </select>
        {fieldError('status')}
      </div>

      {changed && entry.status === 'dnf' ? (
        <p className="notice">
          Resuming clears the DNF details (reason, page, date and note). Your reading logs stay.
        </p>
      ) : null}
      {changed && entry.status === 'finished' && status === 'reading' ? (
        <p className="notice">
          Re-reading: your rating stays, and the new read starts on the date below.
        </p>
      ) : null}

      {changed && status === 'reading'
        ? dateField('started_at', 'Started on', startedOn, setStartedOn)
        : null}
      {changed && status === 'finished'
        ? dateField('finished_at', 'Finished on', finishedOn, setFinishedOn)
        : null}

      {changed && status === 'dnf' ? (
        <>
          <div className="form-field">
            <FieldLabel htmlFor={`${id}-reason`} need="optional">
              Why did you stop?
            </FieldLabel>
            <select
              id={`${id}-reason`}
              value={dnfReason}
              onChange={(event) => setDnfReason(event.target.value as DnfReason | '')}
              aria-invalid={invalid('dnf_reason')}
              aria-describedby={describedBy('dnf_reason')}
            >
              <option value="">{DNF_REASON_LABELS.not_specified}</option>
              {CHOOSABLE_DNF_REASONS.map((value) => (
                <option key={value} value={value}>
                  {DNF_REASON_LABELS[value]}
                </option>
              ))}
            </select>
            {fieldError('dnf_reason')}
          </div>
          <div className="form-field">
            <FieldLabel htmlFor={`${id}-page`} need="optional">
              Stopped at page
            </FieldLabel>
            <input
              id={`${id}-page`}
              type="number"
              inputMode="numeric"
              min={0}
              max={entry.book.page_count ?? undefined}
              value={dnfPage}
              onChange={(event) => setDnfPage(event.target.value)}
              aria-invalid={invalid('dnf_page')}
              aria-describedby={describedBy('dnf_page')}
            />
            {fieldError('dnf_page')}
          </div>
          {dateField('dnf_at', 'Stopped on', dnfAt, setDnfAt)}
          <div className="form-field">
            <FieldLabel htmlFor={`${id}-note`} need="optional">
              Note
            </FieldLabel>
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
      <button type="submit">{update.isPending ? 'Saving…' : 'Save status'}</button>
    </form>
  );
}

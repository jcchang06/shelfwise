import { useId, useState, type FormEvent } from 'react';

import type { ShelfChanges } from '../../api/shelf';
import {
  CHOOSABLE_DNF_REASONS,
  DNF_REASON_LABELS,
  type DnfReason,
  type ShelfEntry,
} from '../../api/types';
import { formatDate, localDateISO } from '../../dates';
import { useUpdateShelfEntry } from '../../hooks/useShelf';
import { FieldLabel } from '../forms/FieldLabel';
import { useFocusInvalid } from '../forms/useFocusInvalid';
import { describeError } from './useFormErrors';

const FIELDS = ['started_at', 'finished_at', 'dnf_reason', 'dnf_page', 'dnf_at', 'dnf_note'];
type DateField = 'started_at' | 'finished_at' | 'dnf_at';

interface ShelfDetailsFormProps {
  entry: ShelfEntry;
  onSaved: (message: string) => void;
}

/**
 * Edit dates, and the DNF details while the book is DNF. Sends only changed fields.
 *
 * Every field is optional (T-7). A date left blank is not sent (T-8), so it keeps the
 * saved date; the field says so. A blank reason is saved as not_specified.
 */
export function ShelfDetailsForm({ entry, onSaved }: ShelfDetailsFormProps) {
  const id = useId();
  const today = localDateISO();
  const update = useUpdateShelfEntry();
  const { ref, focusInvalid } = useFocusInvalid();
  const isDnf = entry.status === 'dnf';
  const savedReason = entry.dnf_reason === 'not_specified' ? '' : entry.dnf_reason;

  const [dates, setDates] = useState<Record<DateField, string>>({
    started_at: entry.started_at ?? '',
    finished_at: entry.finished_at ?? '',
    dnf_at: entry.dnf_at ?? '',
  });
  const [dnfReason, setDnfReason] = useState<DnfReason | ''>(savedReason);
  const [dnfPage, setDnfPage] = useState(entry.dnf_page === null ? '' : String(entry.dnf_page));
  const [dnfNote, setDnfNote] = useState(entry.dnf_note);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const [nothingToSave, setNothingToSave] = useState(false);

  const { fields: serverFields, summary } = describeError(update.error, FIELDS);
  const errors = { ...serverFields, ...clientErrors };

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (update.isPending) return; // Save stays enabled; a second press does nothing
    const problems: Record<string, string> = {};
    const changes: ShelfChanges = {};
    const dateFields: DateField[] = isDnf
      ? ['started_at', 'finished_at', 'dnf_at']
      : ['started_at', 'finished_at'];
    for (const field of dateFields) {
      const value = dates[field];
      if (!value || value === (entry[field] ?? '')) continue; // blank: never sent as null
      if (value > today) problems[field] = "This date can't be in the future.";
      changes[field] = value;
    }
    if (isDnf) {
      if (dnfReason !== savedReason) changes.dnf_reason = dnfReason || 'not_specified';
      const page = dnfPage === '' ? null : Number(dnfPage);
      if (page !== entry.dnf_page) changes.dnf_page = page;
      if (dnfNote !== entry.dnf_note) changes.dnf_note = dnfNote;
    }
    setClientErrors(problems);
    if (Object.keys(problems).length) {
      setNothingToSave(false);
      focusInvalid();
      return;
    }
    const empty = Object.keys(changes).length === 0;
    setNothingToSave(empty);
    if (empty) return;
    update
      .mutateAsync({ entry, changes })
      .then(() => onSaved('Saved the details.'))
      .catch(() => focusInvalid()); // the error itself is shown from update.error
  }

  const describedBy = (field: string, hint = false) =>
    [errors[field] ? `${id}-${field}-error` : '', hint ? `${id}-${field}-hint` : '']
      .filter(Boolean)
      .join(' ') || undefined;
  const fieldError = (field: string) =>
    errors[field] ? (
      <p id={`${id}-${field}-error`} className="field-error">
        {errors[field]}
      </p>
    ) : null;

  function dateField(field: DateField, label: string) {
    const saved = entry[field];
    const keepsSaved = !dates[field] && saved !== null;
    return (
      <div className="form-field">
        <FieldLabel htmlFor={`${id}-${field}`} need="optional">
          {label}
        </FieldLabel>
        <input
          id={`${id}-${field}`}
          type="date"
          value={dates[field]}
          max={today}
          onChange={(event) => setDates({ ...dates, [field]: event.target.value })}
          aria-invalid={errors[field] ? true : undefined}
          aria-describedby={describedBy(field, keepsSaved)}
        />
        {keepsSaved ? (
          <p id={`${id}-${field}-hint`} className="hint">
            Left blank, this keeps {formatDate(saved)}.
          </p>
        ) : null}
        {fieldError(field)}
      </div>
    );
  }

  return (
    <form
      ref={ref}
      className="panel"
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby={`${id}-title`}
    >
      <h2 id={`${id}-title`}>Details</h2>
      {dateField('started_at', 'Started on')}
      {dateField('finished_at', 'Finished on')}
      {isDnf ? (
        <>
          <div className="form-field">
            <FieldLabel htmlFor={`${id}-reason`} need="optional">
              Why did you stop?
            </FieldLabel>
            <select
              id={`${id}-reason`}
              value={dnfReason}
              onChange={(event) => setDnfReason(event.target.value as DnfReason | '')}
              aria-invalid={errors.dnf_reason ? true : undefined}
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
              value={dnfPage}
              onChange={(event) => setDnfPage(event.target.value)}
              aria-invalid={errors.dnf_page ? true : undefined}
              aria-describedby={describedBy('dnf_page')}
            />
            {fieldError('dnf_page')}
          </div>
          {dateField('dnf_at', 'Stopped on')}
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
      {summary ? (
        <p className="field-error" role="alert">
          {summary}
        </p>
      ) : null}
      <p role="status" className="hint">
        {nothingToSave ? 'Nothing has changed yet, so there was nothing to save.' : ''}
      </p>
      <button type="submit">{update.isPending ? 'Saving…' : 'Save details'}</button>
    </form>
  );
}

import { useId, useState, type FormEvent } from 'react';

import type { ShelfChanges } from '../../api/shelf';
import { DNF_REASON_LABELS, type DnfReason, type ShelfEntry } from '../../api/types';
import { localDateISO } from '../../dates';
import { useUpdateShelfEntry } from '../../hooks/useShelf';
import { describeError } from './useFormErrors';

const FIELDS = ['started_at', 'finished_at', 'dnf_reason', 'dnf_page', 'dnf_at', 'dnf_note'];

interface ShelfDetailsFormProps {
  entry: ShelfEntry;
  onSaved: (message: string) => void;
}

/** Edit dates, and the DNF details while the book is DNF. Sends only changed fields. */
export function ShelfDetailsForm({ entry, onSaved }: ShelfDetailsFormProps) {
  const id = useId();
  const today = localDateISO();
  const update = useUpdateShelfEntry();
  const isDnf = entry.status === 'dnf';

  const [startedAt, setStartedAt] = useState(entry.started_at ?? '');
  const [finishedAt, setFinishedAt] = useState(entry.finished_at ?? '');
  const [dnfReason, setDnfReason] = useState<DnfReason | ''>(entry.dnf_reason);
  const [dnfPage, setDnfPage] = useState(entry.dnf_page === null ? '' : String(entry.dnf_page));
  const [dnfAt, setDnfAt] = useState(entry.dnf_at ?? '');
  const [dnfNote, setDnfNote] = useState(entry.dnf_note);

  const changes: ShelfChanges = {};
  if (startedAt !== (entry.started_at ?? '')) changes.started_at = startedAt || null;
  if (finishedAt !== (entry.finished_at ?? '')) changes.finished_at = finishedAt || null;
  if (isDnf) {
    if (dnfReason !== entry.dnf_reason) changes.dnf_reason = dnfReason;
    const page = dnfPage === '' ? null : Number(dnfPage);
    if (page !== entry.dnf_page) changes.dnf_page = page;
    if (dnfAt !== (entry.dnf_at ?? '')) changes.dnf_at = dnfAt || null;
    if (dnfNote !== entry.dnf_note) changes.dnf_note = dnfNote;
  }
  const dirty = Object.keys(changes).length > 0;
  const { fields, summary } = describeError(update.error, FIELDS);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dirty) return;
    update
      .mutateAsync({ entry, changes })
      .then(() => onSaved('Saved the details.'))
      .catch(() => undefined); // shown from update.error
  }

  function dateField(field: string, label: string, value: string, set: (v: string) => void) {
    const errorId = `${id}-${field}-error`;
    return (
      <div className="form-field">
        <label htmlFor={`${id}-${field}`}>{label}</label>
        <input
          id={`${id}-${field}`}
          type="date"
          value={value}
          max={today}
          onChange={(event) => set(event.target.value)}
          aria-invalid={fields[field] ? true : undefined}
          aria-describedby={fields[field] ? errorId : undefined}
        />
        {fields[field] ? (
          <p id={errorId} className="field-error">
            {fields[field]}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Details</h2>
      {dateField('started_at', 'Started on', startedAt, setStartedAt)}
      {dateField('finished_at', 'Finished on', finishedAt, setFinishedAt)}
      {isDnf ? (
        <>
          <div className="form-field">
            <label htmlFor={`${id}-reason`}>Why did you stop?</label>
            <select
              id={`${id}-reason`}
              value={dnfReason}
              onChange={(event) => setDnfReason(event.target.value as DnfReason | '')}
              aria-invalid={fields.dnf_reason ? true : undefined}
              aria-describedby={fields.dnf_reason ? `${id}-dnf_reason-error` : undefined}
            >
              {(Object.keys(DNF_REASON_LABELS) as DnfReason[]).map((value) => (
                <option key={value} value={value}>
                  {DNF_REASON_LABELS[value]}
                </option>
              ))}
            </select>
            {fields.dnf_reason ? (
              <p id={`${id}-dnf_reason-error`} className="field-error">
                {fields.dnf_reason}
              </p>
            ) : null}
          </div>
          <div className="form-field">
            <label htmlFor={`${id}-page`}>Stopped at page</label>
            <input
              id={`${id}-page`}
              type="number"
              inputMode="numeric"
              min={0}
              value={dnfPage}
              onChange={(event) => setDnfPage(event.target.value)}
              aria-invalid={fields.dnf_page ? true : undefined}
              aria-describedby={fields.dnf_page ? `${id}-dnf_page-error` : undefined}
            />
            {fields.dnf_page ? (
              <p id={`${id}-dnf_page-error`} className="field-error">
                {fields.dnf_page}
              </p>
            ) : null}
          </div>
          {dateField('dnf_at', 'Stopped on', dnfAt, setDnfAt)}
          <div className="form-field">
            <label htmlFor={`${id}-note`}>Note</label>
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
      <button type="submit" disabled={!dirty || update.isPending}>
        {update.isPending ? 'Saving…' : 'Save details'}
      </button>
    </form>
  );
}

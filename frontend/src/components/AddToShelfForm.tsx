import { useId, useState, type FormEvent } from 'react';

import { conflictId, fieldErrors, formError } from '../api/errors';
import type { AddToShelfPayload, BookReference } from '../api/shelf';
import { SHELF_STATUS_LABELS, type BookSource, type ShelfStatus } from '../api/types';
import { localDateISO } from '../dates';
import { useAddToShelf } from '../hooks/useAddToShelf';
import { FieldLabel } from './forms/FieldLabel';
import { useFocusInvalid } from './forms/useFocusInvalid';

/** Statuses offered from search. DNF is set on the book page, with its page and reason. */
const ADDABLE: ShelfStatus[] = ['want_to_read', 'reading', 'finished'];

/** A search result (source + maybe book_id) or a catalog book (book_id). */
export interface AddTarget {
  title: string;
  book_id: number | null;
  source?: BookSource;
  source_id?: string;
}

interface AddToShelfFormProps {
  result: AddTarget;
  onAdded: (message: string) => void;
}

function bookReference(target: AddTarget): BookReference {
  if (target.book_id !== null) return { book_id: target.book_id }; // no external API call
  if (target.source && target.source_id) {
    return { source: target.source, source_id: target.source_id };
  }
  throw new Error('An add target needs a book_id or a source and source_id');
}

export function AddToShelfForm({ result, onAdded }: AddToShelfFormProps) {
  const id = useId();
  const today = localDateISO();
  const [status, setStatus] = useState<ShelfStatus>('want_to_read');
  const [finishedOn, setFinishedOn] = useState(today);
  const [dateError, setDateError] = useState<string | null>(null);
  const [alreadyShelved, setAlreadyShelved] = useState(false);
  const add = useAddToShelf();
  const { ref, focusInvalid } = useFocusInvalid();

  if (alreadyShelved) {
    return <p className="shelf-badge">Already on your shelf</p>;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (add.isPending) return; // Save stays enabled; a second press does nothing
    setDateError(null);
    if (status === 'finished' && finishedOn && finishedOn > today) {
      setDateError("The finish date can't be in the future.");
      focusInvalid();
      return;
    }
    const payload: AddToShelfPayload = { ...bookReference(result), status };
    // A blank date is left out, so the API's "today" default applies (T-8).
    if (status === 'finished' && finishedOn) payload.finished_at = finishedOn;

    // mutateAsync, not mutate callbacks: on the book page this form unmounts as soon as
    // the entry exists, and TanStack skips per-call callbacks after unmount.
    add
      .mutateAsync(payload)
      .then(() => onAdded(`Added ${result.title} to ${SHELF_STATUS_LABELS[status]}.`))
      .catch((error: unknown) => {
        if (conflictId(error) !== null) {
          setAlreadyShelved(true); // a 409 means it's there already: not a failure
          onAdded(`${result.title} is already on your shelf.`);
        } else {
          focusInvalid();
        }
      });
  }

  const error = add.isError && conflictId(add.error) === null ? add.error : null;
  const serverDateError = error ? fieldErrors(error).finished_at : undefined;
  const message = error ? formError(error) : null;
  const statusId = `${id}-status`;
  const dateId = `${id}-date`;
  const dateErrorId = `${id}-date-error`;
  const shownDateError = dateError ?? serverDateError;

  return (
    <form ref={ref} className="add-to-shelf" onSubmit={handleSubmit} noValidate>
      <label htmlFor={statusId} className="visually-hidden">
        Shelf for {result.title}
      </label>
      <select
        id={statusId}
        value={status}
        onChange={(event) => setStatus(event.target.value as ShelfStatus)}
        disabled={add.isPending}
      >
        {ADDABLE.map((value) => (
          <option key={value} value={value}>
            {SHELF_STATUS_LABELS[value]}
          </option>
        ))}
      </select>
      {status === 'finished' ? (
        <span className="finished-on">
          <FieldLabel htmlFor={dateId} need="optional">
            Finished on
          </FieldLabel>
          <input
            id={dateId}
            type="date"
            value={finishedOn}
            max={today}
            onChange={(event) => setFinishedOn(event.target.value)}
            aria-invalid={shownDateError ? true : undefined}
            aria-describedby={shownDateError ? dateErrorId : undefined}
            disabled={add.isPending}
          />
        </span>
      ) : null}
      <button type="submit">{add.isPending ? 'Adding…' : 'Add'}</button>
      {shownDateError ? (
        <p id={dateErrorId} className="field-error">
          {shownDateError}
        </p>
      ) : null}
      {message && !serverDateError ? (
        <p className="field-error" role="alert">
          {message}
        </p>
      ) : null}
    </form>
  );
}

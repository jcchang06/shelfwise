import { useId, useState, type FormEvent } from 'react';

import { conflictId, fieldErrors, formError } from '../api/errors';
import type { AddToShelfPayload } from '../api/shelf';
import { SHELF_STATUS_LABELS, type SearchResult, type ShelfStatus } from '../api/types';
import { localDateISO } from '../dates';
import { useAddToShelf } from '../hooks/useAddToShelf';

/** Statuses offered from search. DNF needs a reason, so it's set on the book page. */
const ADDABLE: ShelfStatus[] = ['want_to_read', 'reading', 'finished'];

interface AddToShelfFormProps {
  result: SearchResult;
  onAdded: (message: string) => void;
}

export function AddToShelfForm({ result, onAdded }: AddToShelfFormProps) {
  const id = useId();
  const today = localDateISO();
  const [status, setStatus] = useState<ShelfStatus>('want_to_read');
  const [finishedOn, setFinishedOn] = useState(today);
  const [dateError, setDateError] = useState<string | null>(null);
  const [alreadyShelved, setAlreadyShelved] = useState(false);
  const add = useAddToShelf();

  if (alreadyShelved) {
    return <p className="shelf-badge">Already on your shelf</p>;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDateError(null);
    if (status === 'finished' && finishedOn && finishedOn > today) {
      setDateError("The finish date can't be in the future.");
      return;
    }
    const book =
      result.book_id !== null
        ? { book_id: result.book_id } // already in the catalog: no external API call
        : { source: result.source, source_id: result.source_id };
    const payload: AddToShelfPayload = { ...book, status };
    // An empty date means "today", which the API defaults to anyway.
    if (status === 'finished' && finishedOn) payload.finished_at = finishedOn;

    add.mutate(
      { result, payload },
      {
        onSuccess: () => onAdded(`Added ${result.title} to ${SHELF_STATUS_LABELS[status]}.`),
        onError: (error) => {
          if (conflictId(error) !== null) {
            setAlreadyShelved(true); // a 409 means it's there already: not a failure
            onAdded(`${result.title} is already on your shelf.`);
          }
        },
      },
    );
  }

  const error = add.isError && conflictId(add.error) === null ? add.error : null;
  const serverDateError = error ? fieldErrors(error).finished_at : undefined;
  const message = error ? formError(error) : null;
  const statusId = `${id}-status`;
  const dateId = `${id}-date`;
  const dateErrorId = `${id}-date-error`;
  const shownDateError = dateError ?? serverDateError;

  return (
    <form className="add-to-shelf" onSubmit={handleSubmit} noValidate>
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
          <label htmlFor={dateId}>Finished on</label>
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
      <button type="submit" disabled={add.isPending}>
        {add.isPending ? 'Adding…' : 'Add'}
      </button>
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

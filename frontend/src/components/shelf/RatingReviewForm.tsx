import { useId, useState, type FormEvent } from 'react';

import type { ShelfChanges } from '../../api/shelf';
import type { ShelfEntry } from '../../api/types';
import { useUpdateShelfEntry } from '../../hooks/useShelf';
import { FieldLabel } from '../forms/FieldLabel';
import { StarRatingInput, Stars } from '../Stars';
import { describeError } from './useFormErrors';

interface RatingReviewFormProps {
  entry: ShelfEntry;
  onSaved: (message: string) => void;
}

/**
 * Rating (T-4) can only be set or changed while the book is finished, as the API
 * enforces; during a re-read the kept rating is shown read-only. Reviews work on any
 * status.
 */
export function RatingReviewForm({ entry, onSaved }: RatingReviewFormProps) {
  const id = useId();
  const update = useUpdateShelfEntry();
  const canRate = entry.status === 'finished';
  const [rating, setRating] = useState<number | null>(entry.rating);
  const [review, setReview] = useState(entry.review);

  const changes: ShelfChanges = {};
  if (canRate && rating !== entry.rating) changes.rating = rating;
  if (review !== entry.review) changes.review = review;
  const dirty = Object.keys(changes).length > 0;
  const [nothingToSave, setNothingToSave] = useState(false);
  const { fields, summary } = describeError(update.error, ['rating', 'review']);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (update.isPending) return; // Save stays enabled; a second press does nothing
    setNothingToSave(!dirty);
    if (!dirty) return;
    update
      .mutateAsync({ entry, changes })
      .then(() => onSaved('Saved your rating and review.'))
      .catch(() => undefined); // shown from update.error
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Rating and review</h2>
      {canRate ? (
        <StarRatingInput value={rating} onChange={setRating} disabled={update.isPending} />
      ) : entry.rating !== null ? (
        <p>
          Your rating: <Stars rating={entry.rating} /> (kept from your last read). You can change it
          when you finish this read.
        </p>
      ) : (
        <p className="hint">You can rate this book once it&apos;s finished.</p>
      )}
      {fields.rating ? <p className="field-error">{fields.rating}</p> : null}

      <div className="form-field">
        <FieldLabel htmlFor={`${id}-review`} need="optional">
          Review
        </FieldLabel>
        <textarea
          id={`${id}-review`}
          rows={4}
          value={review}
          onChange={(event) => setReview(event.target.value)}
          aria-invalid={fields.review ? true : undefined}
          aria-describedby={fields.review ? `${id}-review-error` : undefined}
        />
        {fields.review ? (
          <p id={`${id}-review-error`} className="field-error">
            {fields.review}
          </p>
        ) : null}
      </div>

      {summary ? (
        <p className="field-error" role="alert">
          {summary}
        </p>
      ) : null}
      <p role="status" className="hint">
        {nothingToSave ? 'Nothing has changed yet, so there was nothing to save.' : ''}
      </p>
      <button type="submit">{update.isPending ? 'Saving…' : 'Save rating and review'}</button>
    </form>
  );
}

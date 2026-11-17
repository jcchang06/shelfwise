import { useId } from 'react';

/** Read-only stars, announced as "4 out of 5 stars". */
export function Stars({ rating }: { rating: number }) {
  return (
    <span className="stars" role="img" aria-label={`${rating} out of 5 stars`}>
      {'★'.repeat(rating)}
      {'☆'.repeat(5 - rating)}
    </span>
  );
}

interface StarRatingInputProps {
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
}

/**
 * A 1–5 rating as a native radio group: arrow keys move between stars, and each option is
 * announced as "4 stars". "Clear" removes the rating.
 */
export function StarRatingInput({ value, onChange, disabled }: StarRatingInputProps) {
  const name = useId();
  return (
    <fieldset className="star-rating" disabled={disabled}>
      <legend>Your rating</legend>
      <div className="star-rating-options">
        {[1, 2, 3, 4, 5].map((stars) => (
          <label key={stars} className={value !== null && stars <= value ? 'is-filled' : ''}>
            <input
              type="radio"
              name={name}
              value={stars}
              checked={value === stars}
              onChange={() => onChange(stars)}
            />
            <span aria-hidden="true">★</span>
            <span className="visually-hidden">
              {stars} {stars === 1 ? 'star' : 'stars'}
            </span>
          </label>
        ))}
        <button
          type="button"
          className="button-secondary"
          onClick={() => onChange(null)}
          disabled={value === null}
        >
          Clear
        </button>
      </div>
    </fieldset>
  );
}

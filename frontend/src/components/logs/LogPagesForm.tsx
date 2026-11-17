import { useId, useState, type FormEvent } from 'react';

import { SHELF_STATUS_LABELS, type ShelfEntry } from '../../api/types';
import { formatDate, localDateISO } from '../../dates';
import { useLogPages } from '../../hooks/useLogs';
import { FieldLabel } from '../forms/FieldLabel';
import { useFocusInvalid } from '../forms/useFocusInvalid';
import { describeError } from '../shelf/useFormErrors';
import { parsePages } from './parsePages';

interface LogPagesFormProps {
  entry: ShelfEntry;
  onLogged: (message: string) => void;
}

/**
 * "Log pages" (T-3): pages (the one required field) and a date (default today; a blank
 * date is not sent, so the API logs today, T-8). Logging the same day twice adds to that day. Logging a want-to-read book moves it to Reading (the API decides; this form
 * announces it).
 */
export function LogPagesForm({ entry, onLogged }: LogPagesFormProps) {
  const id = useId();
  const today = localDateISO();
  const log = useLogPages();
  const [pages, setPages] = useState('');
  const [date, setDate] = useState(today);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const { ref, focusInvalid } = useFocusInvalid();
  const server = describeError(log.error, ['pages_read', 'log_date']);
  const errors = { ...server.fields, ...clientErrors };

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (log.isPending) return; // Log stays enabled; a second press does nothing
    const problems: Record<string, string> = {};
    const parsed = parsePages(pages);
    if (typeof parsed === 'string') problems.pages_read = parsed;
    if (date && date > today) problems.log_date = "You can't log pages for a future day.";
    setClientErrors(problems);
    if (Object.keys(problems).length || typeof parsed === 'string') {
      focusInvalid();
      return;
    }

    const previousStatus = entry.status;
    // mutateAsync: the page re-keys its shelf forms when the status changes.
    log
      .mutateAsync({
        book_id: entry.book.id,
        pages_read: parsed,
        ...(date ? { log_date: date } : {}),
      })
      .then((saved) => {
        setPages('');
        const day = formatDate(saved.log_date);
        const what =
          saved.pages_read === parsed
            ? `Logged ${parsed} ${parsed === 1 ? 'page' : 'pages'} for ${day}.`
            : `Added ${parsed} to ${day} (now ${saved.pages_read} pages).`;
        const moved =
          saved.shelf_entry && saved.shelf_entry.status !== previousStatus
            ? ` Moved to ${SHELF_STATUS_LABELS[saved.shelf_entry.status]}.`
            : '';
        onLogged(what + moved);
      })
      .catch(() => focusInvalid()); // the error itself is shown from log.error
  }

  const errorId = (field: string) => `${id}-${field}-error`;
  return (
    <form
      ref={ref}
      className="log-form"
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby={`${id}-title`}
    >
      <h3 id={`${id}-title`}>Log pages</h3>
      <div className="log-form-row">
        <div className="form-field">
          <FieldLabel htmlFor={`${id}-pages`} need="required">
            Pages read
          </FieldLabel>
          <input
            id={`${id}-pages`}
            required
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            value={pages}
            onChange={(event) => setPages(event.target.value)}
            aria-invalid={errors.pages_read ? true : undefined}
            aria-describedby={errors.pages_read ? errorId('pages_read') : undefined}
          />
        </div>
        <div className="form-field">
          <FieldLabel htmlFor={`${id}-date`} need="optional">
            Date
          </FieldLabel>
          <input
            id={`${id}-date`}
            type="date"
            value={date}
            max={today}
            onChange={(event) => setDate(event.target.value)}
            aria-invalid={errors.log_date ? true : undefined}
            aria-describedby={errors.log_date ? errorId('log_date') : undefined}
          />
        </div>
        <button type="submit">{log.isPending ? 'Logging…' : 'Log'}</button>
      </div>
      {errors.pages_read ? (
        <p id={errorId('pages_read')} className="field-error">
          {errors.pages_read}
        </p>
      ) : null}
      {errors.log_date ? (
        <p id={errorId('log_date')} className="field-error">
          {errors.log_date}
        </p>
      ) : null}
      {server.summary ? (
        <p className="field-error" role="alert">
          {server.summary}
        </p>
      ) : null}
    </form>
  );
}

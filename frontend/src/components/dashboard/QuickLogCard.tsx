import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import type { ShelfEntry } from '../../api/types';
import { localDateISO } from '../../dates';
import { useLogPages } from '../../hooks/useLogs';
import { BookCover } from '../BookCover';
import { parsePages } from '../logs/parsePages';
import { ReadingProgress } from '../ReadingProgress';
import { describeError } from '../shelf/useFormErrors';

interface QuickLogCardProps {
  entry: ShelfEntry;
  pagesToday: number;
  onLogged: (message: string) => void;
}

/**
 * Log today's pages for one book you're reading: type a number, press Enter. Built for a
 * phone: full-width card, a large numeric input that brings up the number pad. The date
 * is always today; past days are logged on the book page.
 */
export function QuickLogCard({ entry, pagesToday, onLogged }: QuickLogCardProps) {
  const id = useId();
  const log = useLogPages();
  const [pages, setPages] = useState('');
  const [clientError, setClientError] = useState<string | null>(null);
  const server = describeError(log.error, ['pages_read', 'log_date']);
  const error = clientError ?? server.fields.pages_read ?? server.fields.log_date ?? null;
  const title = entry.book.title;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parsePages(pages);
    if (typeof parsed === 'string') {
      setClientError(parsed);
      return;
    }
    setClientError(null);
    log
      .mutateAsync({ book_id: entry.book.id, pages_read: parsed, log_date: localDateISO() })
      .then(() => {
        setPages(''); // cleared after a successful log
        onLogged(`Logged ${parsed} ${parsed === 1 ? 'page' : 'pages'} for ${title} today.`);
      })
      .catch(() => undefined); // shown from log.error
  }

  const errorId = `${id}-error`;
  return (
    <li className="quick-log-card">
      <BookCover url={entry.book.cover_url} />
      <div className="quick-log-body">
        <h3 className="quick-log-title">
          <Link to={`/books/${entry.book.id}`}>{title}</Link>
        </h3>
        <ReadingProgress pagesLogged={entry.pages_logged} pageCount={entry.book.page_count} />
        <p className="quick-log-today">
          {pagesToday > 0
            ? `Today: ${pagesToday} ${pagesToday === 1 ? 'page' : 'pages'}`
            : 'Nothing logged today'}
        </p>
        <form className="quick-log-form" onSubmit={handleSubmit} noValidate>
          <label htmlFor={`${id}-pages`} className="visually-hidden">
            Pages read today for {title}
          </label>
          <input
            id={`${id}-pages`}
            type="number"
            inputMode="numeric"
            enterKeyHint="done"
            min={1}
            step={1}
            placeholder="Pages"
            value={pages}
            onChange={(event) => setPages(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
          <button type="submit" disabled={log.isPending}>
            {log.isPending ? 'Logging…' : 'Log'}
          </button>
        </form>
        {error ? (
          <p id={errorId} className="field-error">
            {error}
          </p>
        ) : null}
        {server.summary && !error ? (
          <p className="field-error" role="alert">
            {server.summary}
          </p>
        ) : null}
      </div>
    </li>
  );
}

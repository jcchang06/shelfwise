import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { shelfPath } from '../shelves';
import { bookSourceLink } from '../api/books';
import { ApiError } from '../api/client';
import { formError } from '../api/errors';
import { SHELF_STATUS_LABELS, type BookDetail, type ShelfEntry } from '../api/types';
import { formatDate, yearOf } from '../dates';
import { AddToShelfForm } from '../components/AddToShelfForm';
import { BookCover } from '../components/BookCover';
import { LogPagesForm } from '../components/logs/LogPagesForm';
import { ReadingLogList } from '../components/logs/ReadingLogList';
import { ReadingProgress } from '../components/ReadingProgress';
import { RatingReviewForm } from '../components/shelf/RatingReviewForm';
import { RemoveFromShelf } from '../components/shelf/RemoveFromShelf';
import { ShelfDetailsForm } from '../components/shelf/ShelfDetailsForm';
import { ShelfStatusForm } from '../components/shelf/ShelfStatusForm';
import { useBook, useShelfEntry } from '../hooks/useShelf';

function BookDetails({ book }: { book: BookDetail }) {
  const link = bookSourceLink(book);
  const meta = [
    book.authors.map((a) => a.name).join(', '),
    book.published_date ? yearOf(book.published_date) : '',
    book.page_count ? `${book.page_count} pages` : '',
  ].filter(Boolean);
  const series = book.series_name
    ? `${book.series_name}${book.series_number ? ` #${book.series_number.replace(/\.0$/, '')}` : ''}`
    : null;

  return (
    <section className="book-details" aria-labelledby="book-title">
      <BookCover url={book.cover_url} size="medium" />
      <div>
        <h1 id="book-title">{book.title}</h1>
        {meta.length ? <p className="book-meta">{meta.join(' · ')}</p> : null}
        {series ? <p className="book-meta">Series: {series}</p> : null}
        {book.genres.length ? <p className="book-meta">{book.genres.join(', ')}</p> : null}
        {link ? (
          <p className="book-meta">
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${link.label} (opens in a new tab)`}
            >
              {link.label}
            </a>
          </p>
        ) : null}
      </div>
      {book.description ? (
        <div className="book-description">
          {book.description.split(/\n{2,}/).map((paragraph, i) => (
            <p key={i}>{paragraph}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ShelfSummary({ entry }: { entry: ShelfEntry }) {
  const dates = [
    entry.started_at ? `Started ${formatDate(entry.started_at)}` : '',
    entry.status === 'finished' && entry.finished_at
      ? `Finished ${formatDate(entry.finished_at)}`
      : '',
  ].filter(Boolean);
  return (
    <div className="shelf-summary">
      <p className="shelf-badge">
        On your shelf ·{' '}
        <Link to={shelfPath(entry.status)}>{SHELF_STATUS_LABELS[entry.status]}</Link>
      </p>
      {dates.length ? <p className="book-meta">{dates.join(' · ')}</p> : null}
      {entry.status === 'reading' ? (
        <ReadingProgress pagesLogged={entry.pages_logged} pageCount={entry.book.page_count} />
      ) : null}
    </div>
  );
}

export default function BookPage() {
  const bookId = Number(useParams().id);
  const valid = Number.isInteger(bookId) && bookId > 0;
  const book = useBook(valid ? bookId : 0);
  const entry = useShelfEntry(valid ? bookId : 0);
  const [announcement, setAnnouncement] = useState('');

  const notFound = !valid || (book.error instanceof ApiError && book.error.status === 404);
  if (notFound) {
    return (
      <>
        <h1>Book not found</h1>
        <p>
          That book isn&apos;t in the catalog. <Link to="/search">Search for it</Link>.
        </p>
      </>
    );
  }
  if (book.isPending) return <p role="status">Loading the book…</p>;
  if (book.isError) {
    return (
      <p className="error-summary" role="alert">
        {formError(book.error)}
      </p>
    );
  }

  return (
    <>
      <BookDetails book={book.data} />
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
      <section className="book-shelf" aria-label="Your shelf">
        {entry.isPending ? <p role="status">Loading your shelf…</p> : null}
        {entry.isError ? (
          <p className="error-summary" role="alert">
            {formError(entry.error)}
          </p>
        ) : null}
        {entry.isSuccess && entry.data === null ? (
          <div className="panel">
            <h2>Add to your shelf</h2>
            <AddToShelfForm
              result={{ title: book.data.title, book_id: book.data.id }}
              onAdded={setAnnouncement}
            />
          </div>
        ) : null}
        {entry.isSuccess && entry.data ? (
          <>
            <ShelfSummary entry={entry.data} />
            {/* First after the summary: logging today's pages is the most common action. */}
            <section className="panel" aria-labelledby="reading-log-title">
              <h2 id="reading-log-title">Reading log</h2>
              <LogPagesForm entry={entry.data} onLogged={setAnnouncement} />
              <ReadingLogList bookId={entry.data.book.id} onChanged={setAnnouncement} />
            </section>
            {/* Keyed so each form resets to the saved values after a save. A log can
                change status and started_at without changing updated_at in the cache, so
                those are in the key too. */}
            <div key={`${entry.data.updated_at}|${entry.data.status}|${entry.data.started_at}`}>
              <ShelfStatusForm entry={entry.data} onSaved={setAnnouncement} />
              <RatingReviewForm entry={entry.data} onSaved={setAnnouncement} />
              <ShelfDetailsForm entry={entry.data} onSaved={setAnnouncement} />
              <RemoveFromShelf entry={entry.data} />
            </div>
          </>
        ) : null}
      </section>
    </>
  );
}

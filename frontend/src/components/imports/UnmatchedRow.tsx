import { useId, useState, type FormEvent } from 'react';

import { MIN_QUERY_LENGTH, sourcePageUrl } from '../../api/books';
import { conflictId, formError } from '../../api/errors';
import type { ImportRow } from '../../api/imports';
import type { BookReference } from '../../api/shelf';
import { SHELF_STATUS_LABELS, type SearchResult } from '../../api/types';
import { formatDate, yearOf } from '../../dates';
import { useBookSearch } from '../../hooks/useBookSearch';
import { useDismissRow, useResolveRow } from '../../hooks/useImports';
import { BookCover } from '../BookCover';
import { SearchAttribution } from '../SearchAttribution';

const SOURCE_NAMES = { google_books: 'Google Books', open_library: 'Open Library' } as const;

interface UnmatchedRowProps {
  importId: number;
  row: ImportRow;
  onHandled: (message: string) => void;
}

function rowSummary(row: ImportRow): string {
  const parts = [SHELF_STATUS_LABELS[row.status]];
  if (row.rating) parts.push(`${row.rating}★`);
  if (row.date_read) parts.push(`read ${formatDate(row.date_read)}`);
  if (row.isbn_13) parts.push(`ISBN ${row.isbn_13}`);
  return parts.join(' · ');
}

/** One Goodreads row that needs a person: why, a pre-filled search, and Use / Dismiss. */
export function UnmatchedRow({ importId, row, onHandled }: UnmatchedRowProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(row.search_query);
  const [query, setQuery] = useState('');
  const search = useBookSearch(query);
  const resolve = useResolveRow();
  const dismiss = useDismissRow();
  const results = search.data?.pages[0]?.results ?? [];
  const source = search.data?.pages[0]?.source;
  const busy = resolve.isPending || dismiss.isPending;
  const actionError = resolve.error ?? dismiss.error;

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.trim().length >= MIN_QUERY_LENGTH) setQuery(draft.trim());
  }

  function use(result: SearchResult) {
    const book: BookReference =
      result.book_id !== null
        ? { book_id: result.book_id }
        : { source: result.source, source_id: result.source_id };
    resolve
      .mutateAsync({ importId, rowId: row.id, arg: book })
      .then((outcome) =>
        onHandled(
          `${row.title}: ${outcome.row.state === 'failed' ? outcome.row.note : 'matched and added to your shelf.'}`,
        ),
      )
      .catch(() => undefined);
  }

  function skip() {
    dismiss
      .mutateAsync({ importId, rowId: row.id, arg: null })
      .then(() => onHandled(`Dismissed ${row.title}.`))
      .catch(() => undefined);
  }

  return (
    <li className="unmatched-row">
      <h3 className="unmatched-title">{row.title}</h3>
      <p className="book-meta">
        {[row.author, row.year_published ? String(row.year_published) : '']
          .filter(Boolean)
          .join(' · ')}
      </p>
      <p className="book-meta">{rowSummary(row)}</p>
      {row.note ? <p className="unmatched-note">{row.note}</p> : null}

      <div className="unmatched-actions">
        <button
          type="button"
          onClick={() => {
            setOpen(true);
            if (!query) setQuery(row.search_query); // search right away with the pre-filled query
          }}
          aria-expanded={open}
          aria-controls={`${id}-search`}
          disabled={busy}
        >
          Find a match
        </button>
        <button
          type="button"
          className="button-secondary"
          onClick={skip}
          disabled={busy}
          aria-label={`Dismiss ${row.title}`}
        >
          Dismiss
        </button>
      </div>
      {actionError && conflictId(actionError) === null ? (
        <p className="field-error" role="alert">
          {formError(actionError)}
        </p>
      ) : null}

      {open ? (
        <div id={`${id}-search`} className="unmatched-search">
          <form role="search" onSubmit={handleSearch} noValidate>
            <label htmlFor={`${id}-q`}>Search for {row.title}</label>
            <div className="search-form-row">
              <input
                id={`${id}-q`}
                type="search"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button type="submit">Search</button>
            </div>
          </form>
          {search.isFetching ? <p role="status">Searching…</p> : null}
          {search.isError ? (
            <p className="field-error" role="alert">
              {formError(search.error)}
            </p>
          ) : null}
          {search.isSuccess && results.length === 0 ? (
            <p className="hint">No books found. Try the ISBN or a shorter title.</p>
          ) : null}
          {source && results.length ? (
            <>
              <SearchAttribution source={source} />
              <ol className="match-candidates">
                {results.slice(0, 8).map((result) => (
                  <li key={`${result.source}:${result.source_id}`} className="match-candidate">
                    <BookCover url={result.cover_url} />
                    <div className="search-result-body">
                      <p className="match-candidate-title">{result.title}</p>
                      <p className="book-meta">
                        {[
                          result.authors.join(', '),
                          result.published_date ? yearOf(result.published_date) : '',
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                      <p className="book-meta">
                        <a
                          href={sourcePageUrl(result)}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`View ${result.title} on ${SOURCE_NAMES[result.source]} (opens in a new tab)`}
                        >
                          View on {SOURCE_NAMES[result.source]}
                        </a>
                      </p>
                      <button
                        type="button"
                        onClick={() => use(result)}
                        disabled={busy}
                        aria-label={`Use ${result.title} for ${row.title}`}
                      >
                        Use this book
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

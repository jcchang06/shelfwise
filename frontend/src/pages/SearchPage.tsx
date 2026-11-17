import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';

import { MIN_QUERY_LENGTH } from '../api/books';
import { fieldErrors, formError } from '../api/errors';
import { SearchAttribution as Attribution } from '../components/SearchAttribution';
import { SearchResultItem } from '../components/SearchResultItem';
import { useBookSearch } from '../hooks/useBookSearch';

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = (params.get('q') ?? '').trim();
  const [draft, setDraft] = useState(q);
  const [inputError, setInputError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const search = useBookSearch(q);

  // Back/forward changes ?q=; keep the box showing the query being displayed.
  useEffect(() => {
    setDraft(q);
    setInputError(null);
  }, [q]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = draft.trim();
    if (next.length < MIN_QUERY_LENGTH) {
      setInputError(`Enter at least ${MIN_QUERY_LENGTH} characters.`);
      return;
    }
    setInputError(null);
    setAnnouncement('');
    setParams({ q: next });
  }

  const pages = search.data?.pages ?? [];
  const results = pages.flatMap((page) => page.results);
  const source = pages[0]?.source;
  const qError = search.isError ? fieldErrors(search.error).q : undefined;
  const pageError = search.isError && !qError ? formError(search.error) : null;
  const shownInputError = inputError ?? qError;

  let status = '';
  if (search.isFetching && !search.isFetchingNextPage) status = 'Searching…';
  else if (search.isSuccess && source) {
    const label =
      source === 'google_books' ? 'Google Books search results' : 'results from Open Library';
    status = results.length
      ? `${results.length} ${label} for “${q}”.`
      : `No books found for “${q}”. Try the ISBN.`;
  }

  return (
    <>
      <h1>Search books</h1>
      <form role="search" className="search-form" onSubmit={handleSubmit} noValidate>
        <label htmlFor="search-q">Title, author or ISBN</label>
        <div className="search-form-row">
          <input
            id="search-q"
            type="search"
            name="q"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            aria-invalid={shownInputError ? true : undefined}
            aria-describedby={shownInputError ? 'search-q-error' : undefined}
          />
          <button type="submit">Search</button>
        </div>
        {shownInputError ? (
          <p id="search-q-error" className="field-error">
            {shownInputError}
          </p>
        ) : null}
      </form>

      {!q ? (
        <p className="hint">Search by title, author or ISBN to add books to your shelf.</p>
      ) : null}

      {/* Result counts and "Added …" messages are announced to screen readers. */}
      <p className="search-status" role="status">
        {status}
      </p>
      <p className="visually-hidden" role="status">
        {announcement}
      </p>

      {pageError ? (
        <p className="error-summary" role="alert">
          {pageError}
        </p>
      ) : null}

      {source && results.length ? (
        <>
          <Attribution source={source} />
          <ol className="search-results">
            {results.map((result) => (
              <SearchResultItem
                key={`${result.source}:${result.source_id}`}
                result={result}
                onAdded={setAnnouncement}
              />
            ))}
          </ol>
          {search.hasNextPage ? (
            <button
              type="button"
              className="button-secondary more-results"
              onClick={() => void search.fetchNextPage()}
              disabled={search.isFetchingNextPage}
            >
              {search.isFetchingNextPage ? 'Loading more…' : 'More results'}
            </button>
          ) : null}
        </>
      ) : null}
    </>
  );
}

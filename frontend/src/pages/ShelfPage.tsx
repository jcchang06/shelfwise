import { useRef } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';

import { formError } from '../api/errors';
import {
  RATING_FILTERS,
  SHELF_SORTS,
  type RatingFilter,
  type ShelfFilters,
  type ShelfSort,
} from '../api/shelf';
import { SHELF_STATUS_LABELS, type ShelfStatus } from '../api/types';
import { ShelfRow } from '../components/ShelfRow';
import { useShelfList } from '../hooks/useShelf';
import { isShelf, parseAuthorParam } from '../shelves';

const EMPTY: Record<ShelfStatus, string> = {
  reading: "You're not reading anything right now.",
  want_to_read: 'Nothing on your want-to-read list yet.',
  finished: "You haven't finished any books yet.",
  dnf: 'No books marked DNF.',
};

function isSort(value: string | null): value is ShelfSort {
  return value !== null && value in SHELF_SORTS;
}

export interface ShelfLocationState {
  announce?: string; // e.g. "Removed Dune from your shelf." after a removal
}

function isRating(value: string | null): value is RatingFilter {
  return RATING_FILTERS.some((option) => option.value === value);
}

export default function ShelfPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const rawStatus = params.get('status');
  const rawSort = params.get('sort');
  const rawRating = params.get('rating');
  const status: ShelfStatus = isShelf(rawStatus) ? rawStatus : 'reading';
  const sort: ShelfSort = isSort(rawSort) ? rawSort : 'updated';
  const filters: ShelfFilters = {
    author: parseAuthorParam(params.get('author')),
    rating: isRating(rawRating) ? rawRating : null,
  };
  const filtered = filters.author !== null || filters.rating !== null;
  const shelf = useShelfList(status, sort, filters);

  const entries = shelf.data?.pages.flatMap((page) => page.results) ?? [];
  const author = shelf.data?.pages[0]?.filters.author ?? null;
  const announce = (location.state as ShelfLocationState | null)?.announce ?? '';

  /** Change some URL options, keeping the rest; null removes one. */
  function update(changes: { sort?: string; author?: null; rating?: string | null }) {
    const next = new URLSearchParams(params);
    next.set('status', status);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  }

  function clearFilters(which: 'author' | 'all') {
    update(which === 'author' ? { author: null } : { author: null, rating: null });
    headingRef.current?.focus(); // the button disappears; keep focus on the page
  }

  return (
    <>
      {/* The shelves themselves are in the shelf bar (ShelfBar) on every page. */}
      <h1 ref={headingRef} tabIndex={-1}>
        Your shelf: {SHELF_STATUS_LABELS[status]}
      </h1>
      <p className="visually-hidden" role="status">
        {announce}
      </p>

      {filters.author !== null ? (
        <p className="active-filter">
          By {author ? author.name : 'this author'}{' '}
          <button
            type="button"
            className="link-button"
            aria-label="Clear the author filter"
            onClick={() => clearFilters('author')}
          >
            Clear
          </button>
        </p>
      ) : null}

      <div className="shelf-controls">
        <div className="shelf-sort">
          <label htmlFor="shelf-sort">Sort by</label>
          <select
            id="shelf-sort"
            value={sort}
            onChange={(event) => update({ sort: event.target.value })}
          >
            {(Object.keys(SHELF_SORTS) as ShelfSort[]).map((value) => (
              <option key={value} value={value}>
                {SHELF_SORTS[value].label}
              </option>
            ))}
          </select>
        </div>
        <div className="shelf-sort">
          <label htmlFor="shelf-rating">Rating</label>
          <select
            id="shelf-rating"
            value={filters.rating ?? ''}
            onChange={(event) => update({ rating: event.target.value || null })}
          >
            <option value="">Any rating</option>
            {RATING_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {shelf.isPending ? <p role="status">Loading your shelf…</p> : null}
      {shelf.isError ? (
        <p className="error-summary" role="alert">
          {formError(shelf.error)}
        </p>
      ) : null}

      {shelf.isSuccess && entries.length === 0 ? (
        filtered ? (
          <p className="hint">
            No {SHELF_STATUS_LABELS[status].toLowerCase()} books match these filters.{' '}
            <button type="button" className="link-button" onClick={() => clearFilters('all')}>
              Clear filters
            </button>
          </p>
        ) : (
          <p className="hint">
            {EMPTY[status]} <Link to="/search">Find a book</Link>
          </p>
        )
      ) : null}

      {entries.length ? (
        <ul className="shelf-list">
          {entries.map((entry) => (
            <ShelfRow key={entry.id} entry={entry} />
          ))}
        </ul>
      ) : null}

      {shelf.hasNextPage ? (
        <button
          type="button"
          className="button-secondary more-results"
          onClick={() => void shelf.fetchNextPage()}
          disabled={shelf.isFetchingNextPage}
        >
          {shelf.isFetchingNextPage ? 'Loading more…' : 'Load more'}
        </button>
      ) : null}
    </>
  );
}

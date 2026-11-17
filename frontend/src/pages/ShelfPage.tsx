import { Link, useLocation, useSearchParams } from 'react-router-dom';

import { formError } from '../api/errors';
import { SHELF_SORTS, type ShelfSort } from '../api/shelf';
import { SHELF_STATUS_LABELS, type ShelfStatus } from '../api/types';
import { ShelfRow } from '../components/ShelfRow';
import { useShelfList } from '../hooks/useShelf';
import { isShelf } from '../shelves';

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

export default function ShelfPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const rawStatus = params.get('status');
  const rawSort = params.get('sort');
  const status: ShelfStatus = isShelf(rawStatus) ? rawStatus : 'reading';
  const sort: ShelfSort = isSort(rawSort) ? rawSort : 'updated';
  const shelf = useShelfList(status, sort);

  const entries = shelf.data?.pages.flatMap((page) => page.results) ?? [];
  const announce = (location.state as ShelfLocationState | null)?.announce ?? '';

  return (
    <>
      {/* The shelves themselves are in the shelf bar (ShelfBar) on every page. */}
      <h1>Your shelf: {SHELF_STATUS_LABELS[status]}</h1>
      <p className="visually-hidden" role="status">
        {announce}
      </p>

      <div className="shelf-sort">
        <label htmlFor="shelf-sort">Sort by</label>
        <select
          id="shelf-sort"
          value={sort}
          onChange={(event) => setParams({ status, sort: event.target.value })}
        >
          {(Object.keys(SHELF_SORTS) as ShelfSort[]).map((value) => (
            <option key={value} value={value}>
              {SHELF_SORTS[value].label}
            </option>
          ))}
        </select>
      </div>

      {shelf.isPending ? <p role="status">Loading your shelf…</p> : null}
      {shelf.isError ? (
        <p className="error-summary" role="alert">
          {formError(shelf.error)}
        </p>
      ) : null}

      {shelf.isSuccess && entries.length === 0 ? (
        <p className="hint">
          {EMPTY[status]} <Link to="/search">Find a book</Link>
        </p>
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

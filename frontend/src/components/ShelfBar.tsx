import { Link, useLocation, useSearchParams } from 'react-router-dom';

import { isShelf, SHELF_BAR_LABELS, SHELVES, shelfPath } from '../shelves';

/**
 * The four shelves, one click away on every logged-in page. Plain links in their own
 * "Shelves" landmark: Tab reaches them, and there's no menu to open. On the shelf page the
 * current shelf is marked aria-current and the sort order carries over.
 */
export function ShelfBar() {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const onShelfPage = pathname === '/shelf';
  const raw = params.get('status');
  const current = onShelfPage ? (isShelf(raw) ? raw : 'reading') : null;
  const sort = onShelfPage ? params.get('sort') : null;

  return (
    <nav aria-label="Shelves" className="shelf-bar">
      <ul>
        {SHELVES.map((status) => (
          <li key={status}>
            <Link
              to={shelfPath(status, sort)}
              aria-current={status === current ? 'page' : undefined}
            >
              {SHELF_BAR_LABELS[status]}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

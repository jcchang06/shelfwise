import { Link } from 'react-router-dom';

import { sourcePageUrl } from '../api/books';
import { SHELF_STATUS_LABELS, type SearchResult } from '../api/types';
import { yearOf } from '../dates';
import { AddToShelfForm } from './AddToShelfForm';
import { AuthorNames } from './AuthorNames';
import { BookCover } from './BookCover';
import { MetaParts } from './MetaParts';

interface SearchResultItemProps {
  result: SearchResult;
  onAdded: (message: string) => void;
}

const SOURCE_NAMES = { google_books: 'Google Books', open_library: 'Open Library' } as const;

export function SearchResultItem({ result, onAdded }: SearchResultItemProps) {
  const meta = [
    result.author_links.length ? <AuthorNames authors={result.author_links} /> : '',
    result.published_date ? yearOf(result.published_date) : '',
    result.page_count ? `${result.page_count} pages` : '',
  ].filter(Boolean);

  return (
    <li className="search-result">
      <BookCover url={result.cover_url} />
      <div className="search-result-body">
        <h2 className="search-result-title">{result.title}</h2>
        {meta.length ? (
          <p className="search-result-meta">
            <MetaParts parts={meta} />
          </p>
        ) : null}
        {result.description ? (
          <p className="search-result-description">{result.description}</p>
        ) : null}
        <p className="search-result-source">
          <a
            href={sourcePageUrl(result)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`View ${result.title} on ${SOURCE_NAMES[result.source]} (opens in a new tab)`}
          >
            View on {SOURCE_NAMES[result.source]}
          </a>
        </p>
        {result.shelf && result.book_id !== null ? (
          <p className="shelf-badge">
            <Link to={`/books/${result.book_id}`}>
              On your shelf · {SHELF_STATUS_LABELS[result.shelf.status]}
            </Link>
          </p>
        ) : (
          <AddToShelfForm result={result} onAdded={onAdded} />
        )}
      </div>
    </li>
  );
}

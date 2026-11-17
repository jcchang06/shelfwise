import { Link } from 'react-router-dom';

import { sourcePageUrl } from '../api/books';
import { SHELF_STATUS_LABELS, type SearchResult } from '../api/types';
import { yearOf } from '../dates';
import { AddToShelfForm } from './AddToShelfForm';
import { BookCover } from './BookCover';

interface SearchResultItemProps {
  result: SearchResult;
  onAdded: (message: string) => void;
}

const SOURCE_NAMES = { google_books: 'Google Books', open_library: 'Open Library' } as const;

export function SearchResultItem({ result, onAdded }: SearchResultItemProps) {
  const meta = [
    result.authors.join(', '),
    result.published_date ? yearOf(result.published_date) : '',
    result.page_count ? `${result.page_count} pages` : '',
  ].filter(Boolean);

  return (
    <li className="search-result">
      <BookCover url={result.cover_url} />
      <div className="search-result-body">
        <h2 className="search-result-title">{result.title}</h2>
        {meta.length ? <p className="search-result-meta">{meta.join(' · ')}</p> : null}
        {result.description ? (
          <p className="search-result-description">{result.description}</p>
        ) : null}
        <p className="search-result-source">
          <a href={sourcePageUrl(result)} target="_blank" rel="noopener noreferrer">
            View on {SOURCE_NAMES[result.source]}
            <span className="visually-hidden">: {result.title} (opens in a new tab)</span>
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

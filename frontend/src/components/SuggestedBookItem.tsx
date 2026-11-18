import { Link } from 'react-router-dom';

import type { SuggestedBook } from '../api/recommendations';
import { SHELF_STATUS_LABELS } from '../api/types';
import { yearOf } from '../dates';
import { AddToShelfForm } from './AddToShelfForm';
import { AuthorNames } from './AuthorNames';
import { BookCover } from './BookCover';
import { MetaParts } from './MetaParts';

/** One suggested book: cover, title, authors, year, and either its shelf or Add. */
export function SuggestedBookItem({
  book,
  onAdded,
  headingLevel = 2,
}: {
  book: SuggestedBook;
  onAdded: (message: string) => void;
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  const authors = book.author_links ?? [];
  return (
    <li className="suggestion">
      <BookCover url={book.cover_url} />
      <div className="suggestion-body">
        <Heading className="suggestion-title">
          <Link to={`/books/${book.id}`}>{book.title}</Link>
        </Heading>
        <p className="suggestion-meta">
          <MetaParts
            parts={[
              authors.length ? <AuthorNames authors={authors} /> : '',
              book.published_date ? yearOf(book.published_date) : '',
            ]}
          />
        </p>
        {book.shelf ? (
          <p className="shelf-badge">
            <Link to={`/books/${book.id}`}>
              On your shelf · {SHELF_STATUS_LABELS[book.shelf.status]}
            </Link>
          </p>
        ) : (
          <AddToShelfForm result={{ title: book.title, book_id: book.id }} onAdded={onAdded} />
        )}
      </div>
    </li>
  );
}

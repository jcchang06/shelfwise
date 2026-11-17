import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import type { AuthorDetail, AuthorWork } from '../api/authors';
import { ApiError } from '../api/client';
import { formError } from '../api/errors';
import { SHELF_STATUS_LABELS } from '../api/types';
import { AddToShelfForm, type AddTarget } from '../components/AddToShelfForm';
import { BookCover } from '../components/BookCover';
import { MetaParts } from '../components/MetaParts';
import { useAuthor } from '../hooks/useAuthor';

function seriesNumber(number: string | null): string {
  return number ? `#${number.replace(/\.0$/, '')}` : '';
}

function addTarget(work: AuthorWork): AddTarget | null {
  if (work.book_id !== null) return { title: work.title, book_id: work.book_id };
  if (work.work_key) {
    return {
      title: work.title,
      book_id: null,
      source: 'open_library',
      source_id: work.work_key,
    };
  }
  return null;
}

function WorkItem({ work, onAdded }: { work: AuthorWork; onAdded: (message: string) => void }) {
  const target = addTarget(work);
  return (
    <li className="author-work">
      <BookCover url={work.cover_url} />
      <div className="author-work-body">
        <h3 className="author-work-title">
          {work.book_id !== null ? (
            <Link to={`/books/${work.book_id}`}>{work.title}</Link>
          ) : (
            work.title
          )}
        </h3>
        <p className="author-work-meta">
          <MetaParts
            parts={[
              work.series_name ? `${work.series_name} ${seriesNumber(work.series_number)}` : '',
              work.first_publish_year ? String(work.first_publish_year) : '',
            ]}
          />
        </p>
        {work.shelf && work.book_id !== null ? (
          <p className="shelf-badge">
            <Link to={`/books/${work.book_id}`}>
              On your shelf · {SHELF_STATUS_LABELS[work.shelf.status]}
            </Link>
          </p>
        ) : target ? (
          <AddToShelfForm result={target} onAdded={onAdded} />
        ) : null}
      </div>
    </li>
  );
}

function groupHeading(seriesName: string | null, onlyGroup: boolean): string {
  if (seriesName) return `${seriesName} series`;
  return onlyGroup ? 'Books' : 'Other books';
}

function AuthorWorks({ author }: { author: AuthorDetail }) {
  const [announcement, setAnnouncement] = useState('');
  const count = author.groups.reduce((sum, group) => sum + group.works.length, 0);
  return (
    <>
      <h1>{author.name}</h1>
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
      {author.works_unavailable ? (
        <p className="notice">
          Couldn&apos;t reach Open Library, so only books already in Shelfwise are listed. Try again
          later for the full list.
        </p>
      ) : author.open_library_key ? (
        <p className="hint">
          {count} {count === 1 ? 'book' : 'books'}, from Open Library and your catalog.{' '}
          <a href={author.open_library_url ?? undefined} target="_blank" rel="noopener noreferrer">
            {author.name} on Open Library
            <span className="visually-hidden"> (opens in a new tab)</span>
          </a>
        </p>
      ) : (
        <p className="notice">
          Couldn&apos;t match this author on Open Library, so only books already in Shelfwise are
          listed.
        </p>
      )}
      {author.groups.map((group, index) => {
        const heading = groupHeading(group.series_name, author.groups.length === 1);
        const headingId = `author-group-${index}`;
        return (
          <section key={group.series_name ?? ''} aria-labelledby={headingId}>
            <h2 id={headingId}>{heading}</h2>
            <ul className="author-works">
              {group.works.map((work) => (
                <WorkItem
                  key={work.work_key ?? `book-${work.book_id}`}
                  work={work}
                  onAdded={setAnnouncement}
                />
              ))}
            </ul>
          </section>
        );
      })}
      {count === 0 ? <p className="hint">No books found for this author.</p> : null}
    </>
  );
}

/** /authors/:id (C-5): the author's books, grouped by series, with add to shelf. */
export default function AuthorPage() {
  const authorId = Number(useParams().id);
  const valid = Number.isInteger(authorId) && authorId > 0;
  const author = useAuthor(valid ? authorId : 0);

  const notFound = !valid || (author.error instanceof ApiError && author.error.status === 404);
  if (notFound) {
    return (
      <>
        <h1>Author not found</h1>
        <p>
          <Link to="/search">Search for a book</Link>
        </p>
      </>
    );
  }
  if (author.isPending) {
    return <p role="status">Loading the author’s books… The first look can take a few seconds.</p>;
  }
  if (author.isError) {
    return (
      <p className="error-summary" role="alert">
        {formError(author.error)}
      </p>
    );
  }
  return <AuthorWorks author={author.data} />;
}

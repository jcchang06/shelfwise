import { Fragment } from 'react';
import { Link } from 'react-router-dom';

import type { AuthorLink } from '../api/types';

/**
 * "A, B" with each author that has a catalog id linked to their page (C-5). Authors not
 * in the catalog yet (search results only) stay plain text.
 */
export function AuthorNames({ authors }: { authors: AuthorLink[] }) {
  return (
    <>
      {authors.map((author, index) => (
        <Fragment key={`${author.id ?? 'x'}-${author.name}`}>
          {index > 0 ? ', ' : null}
          {author.id !== null ? (
            <Link to={`/authors/${author.id}`}>{author.name}</Link>
          ) : (
            author.name
          )}
        </Fragment>
      ))}
    </>
  );
}

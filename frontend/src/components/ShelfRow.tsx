import { Link } from 'react-router-dom';

import { DNF_REASON_LABELS, type ShelfEntry } from '../api/types';
import { formatDate, formatTimestampDate } from '../dates';
import { BookCover } from './BookCover';
import { ReadingProgress } from './ReadingProgress';
import { Stars } from './Stars';

/** The one line that matters for each shelf. */
function StatusLine({ entry }: { entry: ShelfEntry }) {
  switch (entry.status) {
    case 'reading':
      return <ReadingProgress pagesLogged={entry.pages_logged} pageCount={entry.book.page_count} />;
    case 'finished':
      return (
        <p className="shelf-row-status">
          {entry.finished_at ? `Finished ${formatDate(entry.finished_at)}` : 'Finished'}
          {entry.rating ? (
            <>
              {' · '}
              <Stars rating={entry.rating} />
            </>
          ) : null}
        </p>
      );
    case 'dnf': {
      const reason = entry.dnf_reason ? DNF_REASON_LABELS[entry.dnf_reason] : null;
      const stopped = entry.dnf_page !== null ? `Stopped at page ${entry.dnf_page}` : 'Stopped';
      return <p className="shelf-row-status">{reason ? `${stopped} · ${reason}` : stopped}</p>;
    }
    case 'want_to_read':
      return <p className="shelf-row-status">Added {formatTimestampDate(entry.created_at)}</p>;
  }
}

export function ShelfRow({ entry }: { entry: ShelfEntry }) {
  return (
    <li className="shelf-row">
      <BookCover url={entry.book.cover_url} />
      <div className="shelf-row-body">
        <h2 className="shelf-row-title">
          <Link to={`/books/${entry.book.id}`}>{entry.book.title}</Link>
        </h2>
        {entry.book.authors.length ? (
          <p className="shelf-row-meta">{entry.book.authors.join(', ')}</p>
        ) : null}
        <StatusLine entry={entry} />
      </div>
    </li>
  );
}

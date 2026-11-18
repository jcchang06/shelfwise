import { useState } from 'react';
import { Link } from 'react-router-dom';

import { formError } from '../api/errors';
import { formatTimestampDate } from '../dates';
import { SuggestedBookItem } from '../components/SuggestedBookItem';
import { useRecommendations } from '../hooks/useRecommendations';

/** /for-you (R-2): the reader's picks from last night's build. */
export default function RecommendationsPage() {
  const picks = useRecommendations();
  const [announcement, setAnnouncement] = useState('');

  return (
    <>
      <h1>For you</h1>
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
      {picks.isPending ? <p role="status">Loading your picks…</p> : null}
      {picks.isError ? (
        <p className="error-summary" role="alert">
          {formError(picks.error)}
        </p>
      ) : null}
      {picks.isSuccess && picks.data.computed_at === null ? (
        <p className="hint">Your picks appear after the first nightly update.</p>
      ) : null}
      {picks.isSuccess && picks.data.computed_at !== null && picks.data.results.length === 0 ? (
        <p className="hint">
          Rate a few finished books 4★ or higher, and your picks will appear after the next nightly
          update. <Link to="/shelf?status=finished">Your finished books</Link>
        </p>
      ) : null}
      {picks.isSuccess && picks.data.results.length ? (
        <>
          <p className="hint">
            Books like the ones you rated highly, updated nightly
            {picks.data.computed_at
              ? ` (last updated ${formatTimestampDate(picks.data.computed_at)})`
              : ''}
            .
          </p>
          <ol className="suggestions">
            {picks.data.results.map((pick) => (
              <SuggestedBookItem key={pick.book.id} book={pick.book} onAdded={setAnnouncement} />
            ))}
          </ol>
        </>
      ) : null}
    </>
  );
}

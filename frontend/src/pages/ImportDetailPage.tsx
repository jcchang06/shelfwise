import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { ApiError } from '../api/client';
import { formError } from '../api/errors';
import { ImportProgress } from '../components/imports/ImportProgress';
import { ImportSummary } from '../components/imports/ImportSummary';
import { UnmatchedRow } from '../components/imports/UnmatchedRow';
import { importKey, useImport, useImportRows, useImportRunner } from '../hooks/useImports';

function FailedRows({ importId }: { importId: number }) {
  const failed = useImportRows(importId, 'failed');
  const rows = failed.data?.pages.flatMap((page) => page.results) ?? [];
  if (!rows.length) return null;
  return (
    <details className="panel">
      <summary>
        {rows.length} {rows.length === 1 ? 'row' : 'rows'} couldn&apos;t be imported
      </summary>
      <ul className="failed-rows">
        {rows.map((row) => (
          <li key={row.id}>
            <strong>Row {row.row_number}:</strong> {row.title} — {row.note}
          </li>
        ))}
      </ul>
    </details>
  );
}

function UnmatchedSection({
  importId,
  onHandled,
}: {
  importId: number;
  onHandled: (m: string) => void;
}) {
  const unmatched = useImportRows(importId, 'unmatched');
  const rows = unmatched.data?.pages.flatMap((page) => page.results) ?? [];
  if (unmatched.isPending) return <p role="status">Loading the books that need a match…</p>;
  if (unmatched.isError) {
    return (
      <p className="error-summary" role="alert">
        {formError(unmatched.error)}
      </p>
    );
  }
  if (!rows.length) return null;
  return (
    <section aria-labelledby="unmatched-title">
      <h2 id="unmatched-title">
        Books that need a match ({unmatched.data?.pages[0]?.count ?? rows.length})
      </h2>
      <p className="hint">
        These couldn&apos;t be matched automatically. Search for each one and pick the right book,
        or dismiss it.
      </p>
      <ul className="unmatched-list">
        {rows.map((row) => (
          <UnmatchedRow key={row.id} importId={importId} row={row} onHandled={onHandled} />
        ))}
      </ul>
      {unmatched.hasNextPage ? (
        <button
          type="button"
          className="button-secondary more-results"
          onClick={() => void unmatched.fetchNextPage()}
          disabled={unmatched.isFetchingNextPage}
        >
          {unmatched.isFetchingNextPage ? 'Loading…' : 'Show more'}
        </button>
      ) : null}
    </section>
  );
}

/** /import/:id — live progress while running; then the summary, unmatched and failed rows. */
export default function ImportDetailPage() {
  const importId = Number(useParams().id);
  const valid = Number.isInteger(importId) && importId > 0;
  const goodreadsImport = useImport(valid ? importId : 0);
  const runner = useImportRunner(goodreadsImport.data);
  const queryClient = useQueryClient();
  const [announcement, setAnnouncement] = useState('');

  const notFound =
    !valid || (goodreadsImport.error instanceof ApiError && goodreadsImport.error.status === 404);
  if (notFound) {
    return (
      <>
        <h1>Import not found</h1>
        <p>
          <Link to="/import">Back to imports</Link>
        </p>
      </>
    );
  }
  if (goodreadsImport.isPending) return <p role="status">Loading the import…</p>;
  if (goodreadsImport.isError) {
    return (
      <p className="error-summary" role="alert">
        {formError(goodreadsImport.error)}
      </p>
    );
  }

  const data = goodreadsImport.data;
  // Retry a paused or stalled import: mark it pending locally so the runner starts again.
  const retry = () =>
    queryClient.setQueryData(importKey(data.id), { ...data, status: 'pending' as const });

  return (
    <>
      <h1>Goodreads import</h1>
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
      <p>
        <Link to="/import">All imports</Link>
      </p>
      {data.status === 'done' ? (
        <ImportSummary goodreadsImport={data} />
      ) : (
        <ImportProgress
          goodreadsImport={data}
          busyElsewhere={runner.busyElsewhere}
          runnerError={runner.error}
          onRetry={retry}
        />
      )}
      {data.status === 'failed' ? (
        <p className="error-summary" role="alert">
          This import failed: {data.error || 'something went wrong.'}
        </p>
      ) : null}
      <UnmatchedSection importId={data.id} onHandled={setAnnouncement} />
      <FailedRows importId={data.id} />
    </>
  );
}

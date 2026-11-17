import { Link, useNavigate } from 'react-router-dom';

import { formError } from '../api/errors';
import type { ImportStatus } from '../api/imports';
import { fmt } from '../components/charts/summaries';
import { UploadForm } from '../components/imports/UploadForm';
import { formatTimestampDate } from '../dates';
import { useImports } from '../hooks/useImports';

const IMPORT_STATUS_LABELS: Record<ImportStatus, string> = {
  pending: 'Waiting to start',
  running: 'In progress',
  paused: 'Paused',
  done: 'Finished',
  failed: 'Failed',
};

/** /import — upload a Goodreads export, and see past imports. */
export default function ImportPage() {
  const navigate = useNavigate();
  const imports = useImports();
  const past = imports.data?.results ?? [];

  return (
    <>
      <h1>Import</h1>
      <UploadForm onUploaded={(created) => navigate(`/import/${created.id}`)} />

      <section aria-labelledby="past-imports-title">
        <h2 id="past-imports-title">Past imports</h2>
        {imports.isPending ? <p role="status">Loading…</p> : null}
        {imports.isError ? (
          <p className="error-summary" role="alert">
            {formError(imports.error)}
          </p>
        ) : null}
        {imports.isSuccess && past.length === 0 ? <p className="hint">No imports yet.</p> : null}
        {past.length ? (
          <ul className="past-imports">
            {past.map((item) => (
              <li key={item.id}>
                <Link to={`/import/${item.id}`}>{formatTimestampDate(item.created_at)}</Link>
                {' · '}
                {IMPORT_STATUS_LABELS[item.status]}
                {' · '}
                {fmt(item.processed_rows)} of {fmt(item.total_rows)} rows
                {item.unmatched_count > 0 ? ` · ${fmt(item.unmatched_count)} need a match` : ''}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </>
  );
}

import { Link } from 'react-router-dom';

import type { GoodreadsImport } from '../../api/imports';
import { formError } from '../../api/errors';
import { fmt } from '../charts/summaries';

interface ImportProgressProps {
  goodreadsImport: GoodreadsImport;
  busyElsewhere: boolean;
  runnerError: unknown;
  onRetry: () => void;
}

/** The progress bar while an import runs, and what to do when it pauses or stalls. */
export function ImportProgress({
  goodreadsImport,
  busyElsewhere,
  runnerError,
  onRetry,
}: ImportProgressProps) {
  const { processed_rows: done, total_rows: total, status } = goodreadsImport;
  const percent = total ? Math.round((done / total) * 100) : 0;

  return (
    <section className="panel" aria-labelledby="import-progress-title">
      <h2 id="import-progress-title">
        {status === 'paused' ? 'Import paused' : 'Importing your Goodreads library'}
      </h2>
      <div className="progress">
        <progress value={done} max={total || 1} aria-label="Import progress" />
        <span className="progress-text" role="status">
          {fmt(done)} of {fmt(total)} rows ({percent}%)
        </span>
      </div>
      {status === 'paused' ? (
        <p className="notice">
          {goodreadsImport.error || 'The import paused.'} It will continue automatically tonight, or
          you can{' '}
          <button type="button" className="link-button" onClick={onRetry}>
            try again now
          </button>
          .
        </p>
      ) : busyElsewhere ? (
        <p className="hint" role="status">
          Another process is working on this import right now. Waiting for it…
        </p>
      ) : (
        <p className="hint">
          Keep this page open to import faster. If you close it, the rest is imported tonight.{' '}
          <Link to="/shelf">Go to your shelf</Link>
        </p>
      )}
      {runnerError ? (
        <p className="field-error" role="alert">
          {formError(runnerError)}{' '}
          <button type="button" className="link-button" onClick={onRetry}>
            Try again
          </button>
        </p>
      ) : null}
    </section>
  );
}

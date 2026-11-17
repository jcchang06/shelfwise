import { Link } from 'react-router-dom';

import type { GoodreadsImport } from '../../api/imports';
import { formatTimestampDate } from '../../dates';
import { fmt } from '../charts/summaries';

/** The counts when an import is done, plus the follow-ups worth doing. */
export function ImportSummary({ goodreadsImport }: { goodreadsImport: GoodreadsImport }) {
  const g = goodreadsImport;
  const tiles = [
    { label: 'Added to your shelf', value: g.created_count },
    { label: 'Updated', value: g.updated_count },
    { label: 'Skipped', value: g.skipped_count },
    { label: 'Need a match', value: g.unmatched_count },
    { label: "Couldn't import", value: g.failed_count },
  ];
  return (
    <section className="panel" aria-labelledby="import-summary-title">
      <h2 id="import-summary-title">Import finished</h2>
      <p className="hint">
        {fmt(g.total_rows)} rows from Goodreads
        {g.finished_at ? `, finished ${formatTimestampDate(g.finished_at)}` : ''}.
      </p>
      <dl className="totals-row">
        {tiles.map((tile) => (
          <div key={tile.label} className="stat-tile">
            <dt>{tile.label}</dt>
            <dd>{fmt(tile.value)}</dd>
          </div>
        ))}
      </dl>
      {g.placeholder_dnf_count > 0 ? (
        <p className="notice">
          {fmt(g.placeholder_dnf_count)} imported{' '}
          {g.placeholder_dnf_count === 1 ? 'DNF still has' : 'DNFs still have'} the placeholder
          reason “Imported from Goodreads”. Real reasons make your recommendations better.{' '}
          <Link to="/shelf?status=dnf">Set reasons on your DNF shelf</Link>
        </p>
      ) : null}
    </section>
  );
}

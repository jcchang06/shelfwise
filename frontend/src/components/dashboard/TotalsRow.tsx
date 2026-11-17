import type { Stats } from '../../api/stats';
import { fmt } from '../charts/summaries';

/** The year's headline numbers as stat tiles (label + value). */
export function TotalsRow({ totals }: { totals: Stats['totals'] }) {
  const tiles = [
    { label: 'Pages read', value: fmt(totals.pages) },
    { label: 'Books finished', value: fmt(totals.finished) },
    { label: 'Did not finish', value: fmt(totals.dnf) },
    {
      label: 'Average rating',
      value: totals.average_rating !== null ? totals.average_rating.toFixed(1) : '—',
    },
  ];
  return (
    <dl className="totals-row">
      {tiles.map((tile) => (
        <div key={tile.label} className="stat-tile">
          <dt>{tile.label}</dt>
          <dd>{tile.value}</dd>
        </div>
      ))}
    </dl>
  );
}

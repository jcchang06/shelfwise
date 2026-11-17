import { lazy, Suspense, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { formError } from '../api/errors';
import { QuickLogCard } from '../components/dashboard/QuickLogCard';
import { TotalsRow } from '../components/dashboard/TotalsRow';
import { localDateISO } from '../dates';
import { useTodayLogs } from '../hooks/useLogs';
import { useShelfList } from '../hooks/useShelf';
import { useStats } from '../hooks/useStats';

// Chart.js lives in its own chunk, downloaded only when the dashboard renders.
const DashboardCharts = lazy(() => import('../components/charts/DashboardCharts'));

const NO_FILTERS = { author: null, rating: null } as const;

function QuickLogSection({ onLogged }: { onLogged: (message: string) => void }) {
  const today = localDateISO();
  const reading = useShelfList('reading', 'updated', NO_FILTERS);
  const todayLogs = useTodayLogs(today);
  const entries = reading.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <section aria-labelledby="quick-log-title" className="quick-log">
      <h2 id="quick-log-title">Log today&apos;s pages</h2>
      {reading.isPending ? <p role="status">Loading the books you&apos;re reading…</p> : null}
      {reading.isError ? (
        <p className="error-summary" role="alert">
          {formError(reading.error)}
        </p>
      ) : null}
      {reading.isSuccess && entries.length === 0 ? (
        <p className="hint">
          You&apos;re not reading anything right now. Start something from your{' '}
          <Link to="/shelf?status=want_to_read">want-to-read list</Link> or{' '}
          <Link to="/search">find a book</Link>.
        </p>
      ) : null}
      {entries.length ? (
        <ul className="quick-log-list">
          {entries.map((entry) => (
            <QuickLogCard
              key={entry.id}
              entry={entry}
              pagesToday={todayLogs.data?.[entry.book.id] ?? 0}
              onLogged={onLogged}
            />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function StatsSection() {
  const [params, setParams] = useSearchParams();
  const currentYear = new Date().getFullYear();
  const requested = Number(params.get('year'));
  const year =
    Number.isInteger(requested) && requested >= 1900 && requested <= currentYear
      ? requested
      : currentYear;
  const stats = useStats(year);

  const years = new Set<number>([currentYear, year]);
  for (const row of stats.data?.books_per_year ?? []) if (row.year !== null) years.add(row.year);
  const yearOptions = [...years].sort((a, b) => b - a);

  return (
    <section aria-labelledby="stats-title" className="stats">
      <div className="stats-header">
        <h2 id="stats-title">Your reading in {year}</h2>
        <div className="stats-year">
          <label htmlFor="stats-year">Year</label>
          <select
            id="stats-year"
            value={year}
            onChange={(event) => setParams({ year: event.target.value })}
          >
            {yearOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
      </div>
      {stats.isPending ? <p role="status">Loading your stats…</p> : null}
      {stats.isError ? (
        <p className="error-summary" role="alert">
          {formError(stats.error)}
        </p>
      ) : null}
      {stats.data ? (
        <>
          <TotalsRow totals={stats.data.totals} />
          <Suspense fallback={<p role="status">Loading charts…</p>}>
            <DashboardCharts stats={stats.data} />
          </Suspense>
        </>
      ) : null}
    </section>
  );
}

export default function DashboardPage() {
  const [announcement, setAnnouncement] = useState('');
  return (
    <>
      <h1>Dashboard</h1>
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
      {/* Quick logging first: it's the daily action, and it's what a phone screen shows. */}
      <QuickLogSection onLogged={setAnnouncement} />
      <StatsSection />
    </>
  );
}
